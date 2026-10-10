"Finite projection of an existing verified counterexample; never a new checker."

from dataclasses import asdict
from fractions import Fraction
import json
import re

from deeptutor.math_semantic.tools import MathToolRegistry
from deeptutor.math_semantic.validation import _polynomial, _step_scope

COUNTEREXAMPLE_VERSION = "bounded_counterexample_feedback_v1"


def _counterexample_point(snapshot, binding, checked, receipts):
    """Project this checker's finite witness, only with all existing receipts.

    No solver, arithmetic verdict, tool call or independent left/right value
    is created here. Exact nonzero residual and premise receipts already exist.
    Sources carrying a target, objective or answer are outside this first grant.
    """
    if (
        snapshot.problem_model.target
        or snapshot.problem_model.objective
        or any(a.role in {"answer", "answer_candidate", "final_answer"} for a in snapshot.artifacts)
    ):
        return None
    symbols, definitions, premises, facts = _step_scope(snapshot)
    if json.dumps(binding["model"], sort_keys=True) != json.dumps(
        asdict(snapshot.problem_model), sort_keys=True
    ) or binding["premises"] != [list(fact) for fact in facts]:
        return None
    witness = checked["witness"]
    if not isinstance(witness, dict) or set(witness) != symbols | definitions.keys():
        return None
    point = {name: witness[name] for name in sorted(symbols)}
    if any(type(value) is not int or value not in {-1, 0, 1} for value in point.values()):
        return None
    full_point = {**point, **{name: witness[name] for name in definitions}}
    if any(not isinstance(witness[name], str) for name in definitions):
        return None
    if any(
        receipt.tool_version != MathToolRegistry.VERSION
        or receipt.status != "succeeded"
        or receipt.failure_type is not None
        or receipt.scope != MathToolRegistry._scope_for(receipt.tool_name)
        for receipt in receipts
    ):
        return None

    def substitutions(expression, values):
        expected = MathToolRegistry._input_summary(
            {"expression": expression, "substitutions": values}
        )
        return [
            receipt
            for receipt in receipts
            if receipt.tool_name == "substitute" and receipt.input_summary == expected
        ]

    def inline(text):
        for name, value in definitions.items():
            text = re.sub(r"\b" + re.escape(name) + r"\b", "(" + value + ")", text)
        return _polynomial(text)[0]

    for name, definition in definitions.items():
        if not any(
            Fraction(receipt.output_summary) == 0
            for receipt in substitutions(f"({name})-({definition})", full_point)
        ):
            return None
    satisfies = {
        "=": lambda value: value == 0,
        "!=": lambda value: value != 0,
        "<": lambda value: value < 0,
        ">": lambda value: value > 0,
        "<=": lambda value: value <= 0,
        ">=": lambda value: value >= 0,
    }
    for text, operator, _ in premises:
        if not any(
            satisfies[operator](Fraction(receipt.output_summary))
            for receipt in substitutions(inline(text), point)
        ):
            return None
    left, right = binding["claim"]["normalized_form"].split("=")
    left, left_names, _ = _polynomial(left)
    right, right_names, _ = _polynomial(right)
    if (left_names | right_names) - symbols:
        return None
    residual = f"({left})-({right})"
    if definitions:
        replaced = substitutions(residual, definitions)
        if not replaced or len({receipt.output_summary for receipt in replaced}) != 1:
            return None
        residual = replaced[0].output_summary
    if not any(
        Fraction(receipt.output_summary) != 0 for receipt in substitutions(inline(residual), point)
    ):
        return None
    return point
