"""Typed, bounded math tools and the scoped validation adapter."""

from __future__ import annotations

from dataclasses import dataclass, replace
import multiprocessing
import queue
import re
import time
from tokenize import TokenError
from typing import Any, Callable, cast

from deeptutor.math_semantic.contracts import MathArtifact, ToolEvidence, VerificationStatus
from deeptutor.math_semantic.validation import ValidationRequest, validate_request
from deeptutor.math_semantic.verification import (
    MATH_VALIDATOR_VERSION,
    _parse_symbolic,
    answers_equivalent,
    display_translatable,
    math_verifier_available,
    normalize_display,
)

_SAFE_EXPRESSION_RE = re.compile("^[A-Za-z0-9_+*/().,=<>!^;\\-\\s]+$")
_SAFE_IDENTIFIER_RE = re.compile("^[A-Za-z][A-Za-z0-9_]*$")
_BLOCKED_IDENTIFIERS = frozenset(
    {"eval", "exec", "compile", "globals", "locals", "open", "input", "import", "__import__"}
)
_ALLOWED_FUNCTIONS = frozenset({"sin", "cos", "tan", "asin", "acos", "atan", "sqrt", "log", "exp"})
_MAX_EXPRESSION_LENGTH = 512
_MAX_INTEGER_EXPONENT = 10000
DEFAULT_TOOL_TIMEOUT_MS = 5000
FINITE_POLYNOMIAL_DOMAIN = "finite_rational_polynomial_v1"


def _safe_expression(text: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("expression must be a non-empty string")
    normalized = normalize_display(text)
    if len(normalized) > _MAX_EXPRESSION_LENGTH:
        raise ValueError("resource_limit: expression is too long")
    if not display_translatable(text) or not _SAFE_EXPRESSION_RE.fullmatch(normalized):
        raise ValueError("expression contains unsupported syntax")
    if re.search("\\.[A-Za-z_]", normalized):
        raise ValueError("attribute access is not supported")
    if any(
        (
            keyword in normalized.casefold().split()
            for keyword in ("lambda", "if", "else", "for", "while", "import")
        )
    ):
        raise ValueError("expression contains unsupported Python syntax")
    exponents = re.findall("\\*\\*\\s*(\\d+)", normalized)
    if any((int(exponent) > _MAX_INTEGER_EXPONENT for exponent in exponents)):
        raise ValueError("resource_limit: exponent is too large")
    identifiers = re.findall("[A-Za-z_][A-Za-z0-9_]*", normalized)
    if any(
        (
            identifier.startswith("__") or identifier.casefold() in _BLOCKED_IDENTIFIERS
            for identifier in identifiers
        )
    ):
        raise ValueError("expression contains a blocked identifier")
    calls = re.findall("([A-Za-z_][A-Za-z0-9_]*)\\s*\\(", normalized)
    if any((name not in _ALLOWED_FUNCTIONS for name in calls)):
        raise ValueError("expression contains an unsupported function")
    return normalized


def _run_operation(operation: str, kwargs: dict[str, Any]) -> Any:
    kwargs = dict(kwargs)
    domain = kwargs.pop("expression_domain", None)
    domain_inputs = kwargs.pop("domain_inputs", ())
    if domain is not None:
        if domain != FINITE_POLYNOMIAL_DOMAIN:
            raise ValueError("unsupported expression domain")
        if not isinstance(domain_inputs, (tuple, list)) or len(domain_inputs) > 8:
            raise ValueError("polynomial domain inputs must be a bounded sequence")
        inputs = [*domain_inputs]
        inputs.extend(kwargs[key] for key in ("expression", "left", "right") if key in kwargs)
        if "substitutions" in kwargs:
            substitutions = kwargs["substitutions"]
            if not isinstance(substitutions, dict):
                raise ValueError("substitutions must be a mapping")
            inputs.extend(str(value) for value in substitutions.values())
        for text in inputs:
            # Keep the unevaluated tree: e.g. an out-of-domain constant raised
            # to zero must not disappear before its domain is checked.
            parsed = _parse_expression(text, evaluate=False)
            _require_finite_polynomial(parsed)
    elif domain_inputs:
        raise ValueError("domain inputs require an expression domain")
    value = _operation_value(operation, kwargs)
    if domain is not None:
        if operation == "check_equivalence":
            if type(value) is not bool:
                raise ValueError("equivalence must return a boolean")
        else:
            _require_finite_polynomial(value)
    return value


def _require_finite_polynomial(value: Any) -> None:
    """Worker-only membership check in QQ[symbols], including constant inputs."""
    import sympy

    if not isinstance(value, sympy.Basic):
        raise ValueError("expression is outside the finite rational polynomial domain")
    for node in sympy.preorder_traversal(value):
        if isinstance(node, sympy.Rational):
            if node.is_finite is not True:
                raise ValueError("expression is outside the finite rational polynomial domain")
        elif not isinstance(node, (sympy.Symbol, sympy.Add, sympy.Mul, sympy.Pow)):
            raise ValueError("expression is outside the finite rational polynomial domain")
    symbols = sorted(value.free_symbols, key=str) or [sympy.Dummy()]
    try:
        polynomial = sympy.Poly(value, *symbols, domain=sympy.QQ)
    except (sympy.PolynomialError, sympy.polys.polyerrors.CoercionFailed) as exc:
        raise ValueError("expression is outside the finite rational polynomial domain") from exc
    if any(coefficient.is_finite is not True for coefficient in polynomial.coeffs()):
        raise ValueError("expression is outside the finite rational polynomial domain")


def _operation_value(operation: str, kwargs: dict[str, Any]) -> Any:
    if operation == "simplify":
        return _simplify_value(**kwargs)
    if operation == "expand":
        return _expand_value(**kwargs)
    if operation == "factor":
        return _factor_value(**kwargs)
    if operation == "substitute":
        return _substitute_value(**kwargs)
    if operation == "check_equivalence":
        return _equivalence_value(**kwargs)
    if operation == "numeric_evaluate":
        return _numeric_value(**kwargs)
    raise ValueError("unsupported operation")


def _operation_worker(operation: str, kwargs: dict[str, Any], result_queue: Any) -> None:
    try:
        result_queue.put(("succeeded", _run_operation(operation, kwargs), None))
    except (ValueError, SyntaxError, TypeError, TokenError) as exc:
        result_queue.put(
            (
                "resource_limit" if str(exc).startswith("resource_limit:") else "invalid_input",
                None,
                str(exc),
            )
        )
    except Exception as exc:
        result_queue.put(("execution_error", None, type(exc).__name__))


def _parse_expression(
    text: str, *, local_dict: dict[str, Any] | None = None, evaluate: bool = True
) -> Any:
    normalized = _safe_expression(text)
    import sympy

    functions = {
        "sin": sympy.sin,
        "cos": sympy.cos,
        "tan": sympy.tan,
        "asin": sympy.asin,
        "acos": sympy.acos,
        "atan": sympy.atan,
        "sqrt": sympy.sqrt,
        "log": sympy.log,
        "exp": sympy.exp,
        "pi": sympy.pi,
    }
    if local_dict:
        functions.update(local_dict)
    return _parse_symbolic(normalized, local_dict=functions, evaluate=evaluate)


def _simplify_value(expression: str) -> Any:
    import sympy

    return sympy.simplify(_parse_expression(expression))


def _expand_value(expression: str) -> Any:
    import sympy

    return sympy.expand(_parse_expression(expression))


def _factor_value(expression: str) -> Any:
    import sympy

    return sympy.factor(_parse_expression(expression))


def _substitute_value(expression: str, substitutions: dict[str, Any] | None = None) -> Any:
    if not isinstance(substitutions, dict):
        raise ValueError("substitutions must be a mapping")
    import sympy

    parsed_substitutions: dict[Any, Any] = {}
    for name, value in substitutions.items():
        if (
            not isinstance(name, str)
            or not _SAFE_IDENTIFIER_RE.fullmatch(name)
            or name in _BLOCKED_IDENTIFIERS
        ):
            raise ValueError("invalid substitution identifier")
        symbol = sympy.Symbol(name)
        parsed_substitutions[symbol] = _parse_expression(str(value))
    return _parse_expression(expression).subs(parsed_substitutions)


def _equivalence_value(left: str, right: str) -> bool:
    for expression in (left, right):
        normalized = _safe_expression(expression)
        parts = re.split("(?<![<>!])=", normalized)
        if len(parts) == 2:
            _parse_expression(parts[0].strip())
            _parse_expression(parts[1].strip())
        elif len(parts) == 1:
            _parse_expression(parts[0].strip())
        else:
            raise ValueError("equivalence input must contain at most one equality")
    return answers_equivalent(left, right)


def _numeric_value(expression: str) -> Any:
    parsed = _parse_expression(expression)
    if parsed.free_symbols:
        raise ValueError("numeric evaluation requires a concrete expression")
    value = parsed.evalf()
    if getattr(value, "is_Integer", False):
        return int(value)
    if getattr(value, "is_Rational", False):
        return float(value)
    return float(value)


@dataclass(frozen=True, slots=True)
class ToolResult:
    operation: str
    status: str
    value: Any
    evidence: ToolEvidence
    failure_type: str | None = None


class MathToolRegistry:
    """Allow-listed math operations; there is deliberately no eval/Python tool."""

    VERSION = "typed_math_tools_v1"

    def __init__(self, *, max_calls: int = 16) -> None:
        if max_calls < 1:
            raise ValueError("max_calls must be positive")
        self.max_calls = max_calls
        self._call_count = 0
        self._operations: dict[str, Callable[..., Any]] = {
            "simplify": self._simplify,
            "expand": self._expand,
            "factor": self._factor,
            "substitute": self._substitute,
            "check_equivalence": self._check_equivalence,
            "numeric_evaluate": self._numeric_evaluate,
        }

    def call(
        self,
        operation: str,
        *,
        timeout_ms: int = DEFAULT_TOOL_TIMEOUT_MS,
        input_refs: tuple[str, ...] = (),
        **kwargs: Any,
    ) -> ToolResult:
        input_summary = self._input_summary(kwargs)
        if self._call_count >= self.max_calls:
            return self._failure(
                operation,
                "resource_limit",
                "typed call budget exhausted",
                input_refs,
                input_summary=input_summary,
            )
        if operation not in self._operations:
            return self._failure(
                operation,
                "unsupported",
                "operation is not in the typed registry",
                input_refs,
                input_summary=input_summary,
            )
        if timeout_ms <= 0:
            return self._failure(
                operation,
                "timeout",
                "typed operation deadline expired",
                input_refs,
                input_summary=input_summary,
            )
        self._call_count += 1
        started = time.perf_counter()
        context = multiprocessing.get_context("spawn")
        result_queue = context.Queue(maxsize=1)
        process = context.Process(
            target=_operation_worker, args=(operation, kwargs, result_queue), daemon=True
        )
        try:
            if not math_verifier_available():
                return self._failure(
                    operation,
                    "not_checkable",
                    "verifier_unavailable",
                    input_refs,
                    input_summary=input_summary,
                )
            process.start()
            process.join(timeout_ms / 1000)
            if process.is_alive():
                process.terminate()
                process.join(1)
                return self._failure(
                    operation,
                    "timeout",
                    "typed operation exceeded deadline",
                    input_refs,
                    input_summary=input_summary,
                )
            try:
                status, value, error_summary = result_queue.get(timeout=0.5)
            except queue.Empty:
                return self._failure(
                    operation,
                    "execution_error",
                    "worker exited without evidence",
                    input_refs,
                    input_summary=input_summary,
                )
            failure_type = None if status == "succeeded" else status
        finally:
            result_queue.close()
        duration_ms = (time.perf_counter() - started) * 1000
        if status == "succeeded":
            output_summary = str(value)
        else:
            output_summary = error_summary
        evidence = ToolEvidence(
            tool_name=operation,
            tool_version=self.VERSION,
            input_summary=self._input_summary(kwargs),
            output_summary=output_summary,
            scope=self._scope_for(operation),
            status=status,
            duration_ms=duration_ms,
            failure_type=failure_type,
            input_refs=input_refs,
        )
        return ToolResult(operation, status, value, evidence, failure_type)

    def _failure(
        self,
        operation: str,
        status: str,
        summary: str,
        input_refs: tuple[str, ...],
        *,
        input_summary: str = "",
    ) -> ToolResult:
        evidence = ToolEvidence(
            tool_name=operation,
            tool_version=self.VERSION,
            input_summary=input_summary,
            output_summary=summary,
            scope=self._scope_for(operation),
            status=status,
            failure_type=status,
            input_refs=input_refs,
        )
        return ToolResult(operation, status, None, evidence, status)

    @staticmethod
    def _input_summary(kwargs: dict[str, Any]) -> str:
        return "; ".join((f"{key}={value}" for key, value in sorted(kwargs.items())))

    @staticmethod
    def _scope_for(operation: str) -> str:
        return {
            "simplify": "symbolic_simplification",
            "expand": "symbolic_expansion",
            "factor": "symbolic_factorization",
            "substitute": "symbolic_substitution",
            "check_equivalence": "symbolic_equivalence",
            "numeric_evaluate": "numeric_evaluation",
        }.get(operation, "typed_math_tool")

    @staticmethod
    def _simplify(expression: str) -> Any:
        return _simplify_value(expression)

    @staticmethod
    def _expand(expression: str) -> Any:
        return _expand_value(expression)

    @staticmethod
    def _factor(expression: str) -> Any:
        return _factor_value(expression)

    @staticmethod
    def _substitute(expression: str, substitutions: dict[str, Any] | None = None) -> Any:
        return _substitute_value(expression, substitutions)

    @staticmethod
    def _check_equivalence(left: str, right: str) -> bool:
        return _equivalence_value(left, right)

    @staticmethod
    def _numeric_evaluate(expression: str) -> Any:
        return _numeric_value(expression)

    def simplify(self, expression: str, **kwargs: Any) -> ToolResult:
        return self.call("simplify", expression=expression, **kwargs)

    def expand(self, expression: str, **kwargs: Any) -> ToolResult:
        return self.call("expand", expression=expression, **kwargs)

    def factor(self, expression: str, **kwargs: Any) -> ToolResult:
        return self.call("factor", expression=expression, **kwargs)

    def substitute(
        self, expression: str, substitutions: dict[str, Any], **kwargs: Any
    ) -> ToolResult:
        return self.call("substitute", expression=expression, substitutions=substitutions, **kwargs)

    def check_equivalence(self, left: str, right: str, **kwargs: Any) -> ToolResult:
        return self.call("check_equivalence", left=left, right=right, **kwargs)

    def numeric_evaluate(self, expression: str, **kwargs: Any) -> ToolResult:
        return self.call("numeric_evaluate", expression=expression, **kwargs)


def validate_artifact(
    artifact: MathArtifact, *, support_text: str = "", turn_deadline_monotonic: float | None = None
) -> tuple[MathArtifact, ToolEvidence]:
    """Adapt the existing precision-first validator to a scoped artifact.

    The validator preserves the frozen normalization and identity semantics.
    """
    if artifact.assumptions:
        status = "not_checkable"
        scope = f"{MATH_VALIDATOR_VERSION}:unsupported_assumptions:{'|'.join(artifact.assumptions)}"
        failure_type: str | None = "unsupported_assumptions"
        duration_ms = 0.0
        evidence = ToolEvidence(
            tool_name="math_validation",
            tool_version=MATH_VALIDATOR_VERSION,
            input_summary=normalize_display(artifact.statement),
            output_summary=status,
            scope=scope,
            status=status,
            duration_ms=duration_ms,
            artifact_refs=(cast(str, artifact.artifact_id),),
            failure_type=failure_type,
        )
        updated = replace(
            artifact,
            verification_scope=scope,
            tool_evidence_refs=artifact.tool_evidence_refs + (cast(str, evidence.evidence_id),),
        )
        return (updated, evidence)
    try:
        _safe_expression(artifact.statement)
    except ValueError as exc:
        detail = str(exc)
        failure_type = "resource_limit" if detail.startswith("resource_limit:") else "invalid_input"
        scope = f"{MATH_VALIDATOR_VERSION}:{failure_type}:{detail}"
        evidence = ToolEvidence(
            tool_name="math_validation",
            tool_version=MATH_VALIDATOR_VERSION,
            input_summary=normalize_display(artifact.statement),
            output_summary="not_checkable",
            scope=scope,
            status="not_checkable",
            artifact_refs=(cast(str, artifact.artifact_id),),
            failure_type=failure_type,
        )
        updated = replace(
            artifact,
            verification_scope=scope,
            tool_evidence_refs=artifact.tool_evidence_refs + (cast(str, evidence.evidence_id),),
        )
        return (updated, evidence)
    started = time.perf_counter()
    result = validate_request(
        ValidationRequest(
            statement=artifact.statement,
            claim_kind=artifact.claim_kind,
            support_text=support_text,
            turn_deadline_monotonic=turn_deadline_monotonic,
        )
    )
    status = result.status
    scope = result.scope
    failure_type = result.failure_type
    duration_ms = (time.perf_counter() - started) * 1000
    evidence = ToolEvidence(
        tool_name="math_validation",
        tool_version=MATH_VALIDATOR_VERSION,
        input_summary=normalize_display(artifact.statement),
        output_summary=status,
        scope=scope or "math_validation:unknown",
        status=status,
        duration_ms=duration_ms,
        artifact_refs=(cast(str, artifact.artifact_id),),
        failure_type=failure_type,
    )
    updated = replace(
        artifact,
        verification_status=cast(VerificationStatus, status),
        verification_scope=evidence.scope,
        tool_evidence_refs=artifact.tool_evidence_refs + (cast(str, evidence.evidence_id),),
    )
    return (updated, evidence)
