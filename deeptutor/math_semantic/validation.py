"""Bounded mathematical validation through neutral request/result values."""

from __future__ import annotations

from dataclasses import dataclass
import multiprocessing
import queue
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .claims import StudentMathClaim
    from .contracts import ToolEvidence
    from .tools import MathToolRegistry
    from .workspace import MathWorkspaceSnapshot


@dataclass(frozen=True, slots=True)
class ValidationRequest:
    statement: str
    claim_kind: str = "derived_equation"
    support_text: str = ""
    turn_deadline_monotonic: float | None = None
    timeout_ms: int = 5000

    def __post_init__(self) -> None:
        if not isinstance(self.statement, str) or not self.statement.strip():
            raise ValueError("validation statement is required")
        if self.timeout_ms < 0:
            raise ValueError("validation timeout cannot be negative")


@dataclass(frozen=True, slots=True)
class ValidationResult:
    status: str
    scope: str
    residual: str | None = None
    failure_type: str | None = None


class MathValidationAdapter:
    """Translate a neutral request to the existing engine in a child process."""

    @staticmethod
    def validate(request: ValidationRequest) -> ValidationResult:
        from deeptutor.math_semantic.verification import (
            MATH_VALIDATOR_VERSION,
            math_verifier_available,
        )

        if not math_verifier_available():
            return ValidationResult(
                "not_checkable", "verifier_unavailable", failure_type="verifier_unavailable"
            )
        remaining_ms = request.timeout_ms
        if request.turn_deadline_monotonic is not None:
            remaining_ms = min(
                remaining_ms,
                max(0, int((request.turn_deadline_monotonic - time.monotonic()) * 1000)),
            )
        if remaining_ms <= 0:
            return ValidationResult(
                "not_checkable", f"{MATH_VALIDATOR_VERSION}:timeout", failure_type="timeout"
            )
        context = multiprocessing.get_context("spawn")
        result_queue = context.Queue(maxsize=1)
        process = context.Process(
            target=_validation_worker, args=(request, remaining_ms, result_queue), daemon=True
        )
        process.start()
        process.join(remaining_ms / 1000)
        if process.is_alive():
            process.terminate()
            process.join(1)
            result_queue.close()
            return ValidationResult(
                "not_checkable", f"{MATH_VALIDATOR_VERSION}:timeout", failure_type="timeout"
            )
        try:
            result = result_queue.get(timeout=0.5)
        except queue.Empty:
            result_queue.close()
            return ValidationResult(
                status="not_checkable",
                scope=f"{MATH_VALIDATOR_VERSION}:adapter_failure:worker_exit",
                failure_type="worker_exit",
            )
        finally:
            result_queue.close()
        status, scope, residual, failure_type = result
        return ValidationResult(status, scope, residual, failure_type)


def validate_request(request: ValidationRequest) -> ValidationResult:
    """Validate a neutral request through the existing math_validation engine."""
    return MathValidationAdapter.validate(request)


# Private student-step checks reuse the typed tools. They never create an
# artifact, path admission, learner verdict, or publication permission.
STEP_VERSION = "grounded_real_polynomial_step_v1"


def step_basis(snapshot: MathWorkspaceSnapshot) -> str:
    """Mathematical scope; evidence-only revisions do not change its meaning."""
    from dataclasses import asdict
    import hashlib
    import json

    value = asdict(snapshot)
    value.pop("tool_evidence")
    value["artifacts"] = [
        a for a in value["artifacts"] if a["claim_kind"] != "operation_description"
    ]
    value["workspace"] = {
        k: v
        for k, v in value["workspace"].items()
        if k not in {"revision", "tool_evidence_refs", "artifact_refs"}
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _polynomial(text: str) -> tuple[str, set[str], Any]:
    """Closed AST grammar, with exact rational arithmetic and small resources."""
    import ast
    from fractions import Fraction
    import re

    from .tools import _safe_expression

    text = _safe_expression(text)
    if re.search(r"[A-Za-z]+\s*\(", text):
        raise ValueError("unsupported_polynomial")
    # In this single-letter scalar grammar, adjacent letters denote products,
    # matching the existing tool parser. Named multi-letter quantities are not
    # accepted as domain declarations or definitions.
    text = re.sub(r"(?<=\d)(?=[A-Za-z])", "*", text)
    text = re.sub(r"\b[A-Za-z]{2,}\b", lambda m: "(" + "*".join(m[0]) + ")", text)
    if len(text) > 256:
        raise ValueError("polynomial_size")
    tree = ast.parse(text.strip(), mode="eval").body
    if len(list(ast.walk(tree))) > 64:
        raise ValueError("polynomial_size")
    names = set()

    def bounded(value):
        if max(value.numerator.bit_length(), value.denominator.bit_length()) > 2048:
            raise ValueError("polynomial_arithmetic_budget")
        return value

    def visit(node, values):
        if (
            isinstance(node, ast.Name)
            and len(node.id) == 1
            and node.id.isascii()
            and node.id.isalpha()
            and node.id not in {"E", "I"}
        ):
            names.add(node.id)
            return values.get(node.id, Fraction(0))
        if isinstance(node, ast.Constant) and type(node.value) is int and abs(node.value) <= 10000:
            return Fraction(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return visit(node.operand, values) * (-1 if isinstance(node.op, ast.USub) else 1)
        if isinstance(node, ast.BinOp):
            left, right = visit(node.left, values), visit(node.right, values)
            if isinstance(node.op, ast.Add):
                return bounded(left + right)
            if isinstance(node.op, ast.Sub):
                return bounded(left - right)
            if isinstance(node.op, ast.Mult):
                return bounded(left * right)
            if isinstance(node.op, ast.Div) and isinstance(node.right, ast.Constant) and right:
                return bounded(left / right)
            if (
                isinstance(node.op, ast.Pow)
                and isinstance(node.right, ast.Constant)
                and type(node.right.value) is int
                and 0 <= node.right.value <= 8
            ):
                if (
                    max(left.numerator.bit_length(), left.denominator.bit_length())
                    * node.right.value
                    > 2048
                ):
                    raise ValueError("polynomial_arithmetic_budget")
                return bounded(left**node.right.value)
        raise ValueError("unsupported_polynomial")

    visit(tree, {})
    return text, names, lambda values: visit(tree, values)


def _step_scope(
    snapshot: MathWorkspaceSnapshot,
) -> tuple[set[str], dict[str, str], list[tuple[str, str, str]], list[tuple[str, str]]]:
    """Use actual explicit facts, never SymPy's default commutativity as a domain."""
    import re

    model = snapshot.problem_model
    if model.parse_status != "parsed" or model.quantifiers:
        raise ValueError("unsupported_problem_scope")
    symbols = set()
    for fact in model.domain:
        if fact.status != "explicit":
            raise ValueError("domain_not_explicit")
        match = re.fullmatch(
            r"([A-Za-z][A-Za-z0-9_]*(?:\s*,\s*[A-Za-z][A-Za-z0-9_]*)*)\s+(?:is|are) real(?: scalars?)?",
            fact.value or "",
        )
        if not match:
            raise ValueError("unsupported_domain")
        symbols.update(s.strip() for s in match[1].split(","))
    if not symbols or len(symbols) > 4:
        raise ValueError("real_scalar_domain_required")
    if any(len(s) != 1 or s in {"E", "I"} for s in symbols):
        raise ValueError("unsupported_scalar_symbol")
    definitions, premises = {}, []
    facts = [
        (f.value, model.model_ref.identifier)
        for f in (*model.givens, *model.constraints, *model.assumptions)
        if f.status == "explicit"
    ]
    if len(facts) != len(model.givens) + len(model.constraints) + len(model.assumptions):
        raise ValueError("premise_not_explicit")
    # A target's explicitly named quantity is a definition, not its answer.
    if model.target and model.target.status == "explicit":
        target = re.fullmatch(r"range of ([A-Za-z][A-Za-z0-9_]*\s*=.+)", model.target.value or "")
        if target:
            facts.append((target[1], model.model_ref.identifier))
    for a in snapshot.artifacts:
        if a.role in {"given", "definition"}:
            if (
                a.verification_status not in {"qualified", "verified"}
                or a.assumptions
                or not set(a.provenance) & set(model.provenance)
            ):
                raise ValueError("unsupported_premise")
            facts.append((a.statement, a.artifact_id))
    if len(facts) > 12:
        raise ValueError("premise_budget")
    for text, ref in facts:
        parts = re.split(r"(<=|>=|!=|=|<|>)", text or "")
        if len(parts) != 3:
            raise ValueError("unsupported_constraint")
        left, op, right = parts
        left, ln, _ = _polynomial(left)
        right, rn, _ = _polynomial(right)
        if op == "=" and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", left) and left not in symbols:
            if left in rn or (left in definitions and definitions[left][0] != right):
                raise ValueError("conflicting_definition")
            definitions[left] = (right, ref)
        else:
            premises.append((f"({left})-({right})", op, ref))
    # Inline only finite, acyclic explicit definitions; no constraint solving.
    resolved = {}

    def resolve(name, stack=()):
        if name in stack:
            raise ValueError("cyclic_definition")
        text = definitions[name][0]
        for other in sorted(_polynomial(text)[1] - symbols):
            if other not in definitions:
                raise ValueError("undefined_symbol")
            text = re.sub(
                r"\b" + re.escape(other) + r"\b", "(" + resolve(other, (*stack, name)) + ")", text
            )
        _polynomial(text)
        return text

    for name in definitions:
        resolved[name] = resolve(name)
    return symbols, resolved, premises, facts


def check_student_step(
    claim: StudentMathClaim,
    snapshot: MathWorkspaceSnapshot,
    registry: MathToolRegistry,
    *,
    deadline: float,
    timeout_ms: int = 2000,
) -> tuple[ToolEvidence, ...]:
    """Identity, explicit-definition relation, verified finite witness, or UNKNOWN."""
    from dataclasses import asdict
    from fractions import Fraction
    from itertools import product
    import json
    import re

    from .contracts import ToolEvidence

    binding = {
        "claim": asdict(claim),
        "episode": snapshot.workspace.workspace_id,
        "revision": snapshot.workspace.revision,
        "math_basis": step_basis(snapshot),
        "model": asdict(snapshot.problem_model),
        "premises": [],
    }
    refs = (
        claim.student_response_ref.identifier,
        claim.claim_id,
        f"{snapshot.workspace.workspace_id}@{snapshot.workspace.revision}",
        snapshot.problem_model.model_ref.identifier,
    )
    proofs = []
    result = {"local_relation": "UNKNOWN", "reason": "unsupported_claim", "witness": None}

    def call(kind, **kwargs):
        remaining = max(0, int((deadline - time.monotonic()) * 1000))
        tool = registry.call(kind, input_refs=refs, timeout_ms=min(timeout_ms, remaining), **kwargs)
        proofs.append(tool.evidence)
        if tool.status != "succeeded":
            raise ValueError(tool.failure_type or tool.status)
        return tool

    try:
        if claim.parse_status != "parsed" or claim.claim_type not in {"identity", "equation"}:
            raise ValueError("unsupported_claim")
        symbols, definitions, premises, facts = _step_scope(snapshot)
        binding["premises"] = facts
        refs += tuple(dict.fromkeys(ref for _, ref in facts))
        parts = re.split(r"(?<![<>=!])=(?!=)", claim.normalized_form)
        if len(parts) != 2:
            raise ValueError("single_equality_required")
        left, ln, _ = _polynomial(parts[0])
        right, rn, _ = _polynomial(parts[1])
        if (ln | rn) - symbols - definitions.keys():
            raise ValueError("undefined_symbol")
        residual = f"({left})-({right})"
        # Check constraints completely before making any positive judgment.
        for text, _, _ in premises:
            if _polynomial(text)[1] - symbols - definitions.keys():
                raise ValueError("undefined_premise_symbol")
        raw = call("expand", expression=residual)
        if str(raw.value) == "0" and (ln | rn) <= symbols:
            result.update(local_relation="IDENTITY", reason="zero_polynomial_over_explicit_reals")
        else:
            if definitions:
                residual = str(
                    call("substitute", expression=residual, substitutions=definitions).value
                )
            checked = call("expand", expression=residual)
            if str(checked.value) == "0":
                result.update(
                    local_relation="CONDITIONAL", reason="zero_after_explicit_definitions"
                )
            else:

                def inline(text):
                    for name, value in definitions.items():
                        text = re.sub(r"\b" + re.escape(name) + r"\b", "(" + value + ")", text)
                    return _polynomial(text)

                constraints = [(inline(text), op) for text, op, _ in premises]
                polynomial = inline(residual)
                if polynomial[1] - symbols:
                    raise ValueError("undefined_symbol")
                satisfied = {
                    "=": lambda v: v == 0,
                    "!=": lambda v: v != 0,
                    "<": lambda v: v < 0,
                    ">": lambda v: v > 0,
                    "<=": lambda v: v <= 0,
                    ">=": lambda v: v >= 0,
                }
                # 81 candidates at most; exact host arithmetic only proposes a
                # point. Existing tools independently verify every applicable
                # constraint and the nonzero claim residual at that same point.
                for values in product((-1, 0, 1), repeat=len(symbols)):
                    if time.monotonic() >= deadline:
                        raise ValueError("timeout")
                    point = dict(zip(sorted(symbols), values))
                    if not polynomial[2](point) or not all(
                        satisfied[op](p[2](point)) for p, op in constraints
                    ):
                        continue
                    full_point = dict(point)
                    full_point.update(
                        {
                            name: str(_polynomial(value)[2](point))
                            for name, value in definitions.items()
                        }
                    )
                    for name, definition in definitions.items():
                        value = call(
                            "substitute",
                            expression=f"({name})-({definition})",
                            substitutions=full_point,
                        )
                        if Fraction(str(value.value)):
                            raise ValueError("witness_definition_failed")
                    for p, op in constraints:
                        value = call("substitute", expression=p[0], substitutions=point)
                        if not satisfied[op](Fraction(str(value.value))):
                            raise ValueError("witness_constraint_failed")
                    value = call("substitute", expression=polynomial[0], substitutions=point)
                    if not Fraction(str(value.value)):
                        raise ValueError("witness_not_unequal")
                    result.update(
                        local_relation="COUNTEREXAMPLE",
                        reason="all_constraints_exactly_checked",
                        witness=full_point,
                    )
                    break
                else:
                    result["reason"] = "finite_search_no_witness"
    except (
        ValueError,
        SyntaxError,
        TypeError,
        RecursionError,
        OverflowError,
        ZeroDivisionError,
    ) as exc:
        result.update(local_relation="UNKNOWN", reason=str(exc), witness=None)
    result["tool_evidence_refs"] = [p.evidence_id for p in proofs]
    envelope = ToolEvidence(
        "student_step_check",
        STEP_VERSION,
        json.dumps(binding, sort_keys=True),
        json.dumps(result, sort_keys=True),
        "local_relation_only_no_admission_or_authority",
        "succeeded" if result["local_relation"] != "UNKNOWN" else "not_checkable",
        input_refs=refs,
        failure_type=result["reason"] if result["local_relation"] == "UNKNOWN" else None,
    )
    return (*proofs, envelope)


def _validation_worker(request: ValidationRequest, timeout_ms: int, result_queue: Any) -> None:
    """Run the semantic validator behind a killable process boundary."""
    from deeptutor.math_semantic.expression import MathExpression
    from deeptutor.math_semantic.verification import MATH_VALIDATOR_VERSION, validate_math_claim

    try:
        checked = validate_math_claim(
            MathExpression(display=request.statement, kind=request.claim_kind),
            support_text=request.support_text,
            turn_deadline_monotonic=time.monotonic() + timeout_ms / 1000,
        )
        failure_type = "verifier_unavailable" if checked.scope == "verifier_unavailable" else None
        result_queue.put((checked.status, checked.scope, checked.residual, failure_type))
    except Exception as exc:
        result_queue.put(
            (
                "not_checkable",
                f"{MATH_VALIDATOR_VERSION}:adapter_failure:{type(exc).__name__}",
                None,
                type(exc).__name__,
            )
        )
