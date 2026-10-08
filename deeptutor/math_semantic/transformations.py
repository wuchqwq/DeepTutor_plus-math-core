"""Bounded rational linear transformations; no eval, provider, or learner state.

Verification proves equivalence to a named premise, never that an arbitrary
premise is true. Operation content and resulting equation have separate refs.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from fractions import Fraction
import re

from deeptutor.math_semantic.contracts import MathArtifact, ToolEvidence
from deeptutor.math_semantic.refs import SourceRef

VERSION = "rational_linear_transform_v1"
SCOPE = "one_variable_rational_linear_equivalence_relative_to_input"
KINDS = ("add_both_sides", "subtract_both_sides", "multiply_both_sides", "divide_both_sides")


@dataclass(frozen=True, slots=True)
class TypedTransformationOperation:
    kind: str
    quantity: str

    def __post_init__(self):
        if self.kind not in KINDS or not isinstance(self.quantity, str) or len(self.quantity) > 32:
            raise ValueError("invalid bounded transformation request")

    def to_dict(self):
        return {"kind": self.kind, "quantity": self.quantity, "version": VERSION}


@dataclass(frozen=True, slots=True)
class TransformationValidation:
    status: str
    mechanism: str = VERSION
    scope: str = SCOPE
    detail: str = ""


@dataclass(frozen=True, slots=True)
class MaterializedTransformation:
    operation: TypedTransformationOperation
    operation_ref: SourceRef
    before_artifact_ref: str
    after_artifact_ref: str | None
    validation: TransformationValidation
    workspace_revision: int
    operation_artifact_ref: str | None = None
    artifact: MathArtifact | None = None
    evidence: ToolEvidence | None = None


def _bound(pair):
    if any((v.numerator.bit_length() > 128 or v.denominator.bit_length() > 128 for v in pair)):
        raise ValueError("rational_resource_limit")
    return pair


def _linear(text: str, variable: str | None):
    if not text or len(text) > 128 or (not re.fullmatch("[a-z0-9+*/(). -]+", text)):
        raise ValueError("unsupported_expression_syntax")
    tree = ast.parse(text.strip(), mode="eval")
    if sum((1 for _ in ast.walk(tree))) > 48:
        raise ValueError("expression_resource_limit")

    def walk(node):
        if (
            isinstance(node, ast.Constant)
            and type(node.value) is int
            and (abs(node.value) <= 1000000)
        ):
            return (Fraction(0), Fraction(node.value))
        if isinstance(node, ast.Name) and variable and (node.id == variable):
            return (Fraction(1), Fraction(0))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            a, b = walk(node.operand)
            return (a, b) if isinstance(node.op, ast.UAdd) else (-a, -b)
        if isinstance(node, ast.BinOp):
            a, b = walk(node.left)
            c, d = walk(node.right)
            if isinstance(node.op, ast.Add):
                return _bound((a + c, b + d))
            if isinstance(node.op, ast.Sub):
                return _bound((a - c, b - d))
            if isinstance(node.op, ast.Mult) and (not a * c):
                return _bound((a * d + b * c, b * d))
            if isinstance(node.op, ast.Div) and (not c) and d:
                return _bound((a / d, b / d))
        raise ValueError("unsupported_linear_expression")

    return walk(tree.body)


def _equation(text):
    if not isinstance(text, str) or len(text) > 256 or text.count("=") != 1:
        raise ValueError("unsupported_equation")
    names = set(re.findall("[a-zA-Z_]+", text))
    if len(names) != 1 or not re.fullmatch("[a-z]", next(iter(names))):
        raise ValueError("requires_one_single_letter_variable")
    variable = next(iter(names))
    lhs, rhs = text.split("=")
    return (variable, _linear(lhs, variable), _linear(rhs, variable))


def _format(pair, variable):
    a, b = pair
    if not a:
        return str(b)
    term = variable if a == 1 else "-" + variable if a == -1 else str(a) + "*" + variable
    return term if not b else term + ("+" if b > 0 else "-") + str(abs(b))


def _evaluate_transformation(before: MathArtifact, operation: TypedTransformationOperation):
    if before.verification_status in {"refuted", "unresolved_conflict"}:
        return (TransformationValidation("not_checkable", detail="unusable_premise"), None, False)
    try:
        variable, left, right = _equation(before.statement)
        _, q = _linear(operation.quantity, None)
        if operation.kind in {"multiply_both_sides", "divide_both_sides"} and (not q):
            return (
                TransformationValidation("invalid_input", detail="nonzero_constant_required"),
                None,
                False,
            )
        factor = Fraction(1)
        shift = Fraction(0)
        if operation.kind == "add_both_sides":
            shift = q
        if operation.kind == "subtract_both_sides":
            shift = -q
        if operation.kind == "multiply_both_sides":
            factor = q
        if operation.kind == "divide_both_sides":
            factor = 1 / q
        result = [_bound((a * factor, b * factor + shift)) for a, b in (left, right)]
        statement = _format(result[0], variable) + "=" + _format(result[1], variable)
        witness = tuple((result[0][i] - result[1][i] for i in (0, 1)))
        expected = tuple(((left[i] - right[i]) * factor for i in (0, 1)))
        if witness != expected:
            raise RuntimeError("transformation residual witness mismatch")
        solved = (
            result[0] == (1, 0) and result[1][0] == 0 or (result[1] == (1, 0) and result[0][0] == 0)
        )
        return (
            TransformationValidation("verified", detail="exact_nonzero_scaled_residual"),
            statement,
            solved,
        )
    except (ValueError, SyntaxError, ZeroDivisionError, RecursionError):
        return (
            TransformationValidation(
                "not_checkable", detail="outside_bounded_rational_linear_scope"
            ),
            None,
            False,
        )


def validate_transformation(before: MathArtifact, operation: TypedTransformationOperation):
    validation, statement, _ = _evaluate_transformation(before, operation)
    return (validation, statement)
