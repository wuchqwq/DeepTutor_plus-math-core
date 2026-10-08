"""SymPy-backed structural math-claim validation (design §9, FAILURE D).

Asymmetric structural test (§9.3, revision 3): a single ``=`` with asymmetric
free symbols is an assignment/derived relation and is NEVER refuted; a
symmetric equality that fails the identity proof is only ``refuted`` with
independent identity-intent evidence (declared ``algebraic_identity`` plus a
strong marker in gloss/support text), otherwise it is a legitimate
``conditional_equation``. Pure arithmetic without free symbols is decided by
evaluation. Anything the bounded rewrite table cannot translate stays
``not_checkable`` — never guessed (no ``antlr4``, no ``sympy.parsing.latex``).

The rewrite table is the measured probe table (``scratch_latex_sympy_probe``,
``scratch_macro_residue_probe``) extended per §9.3: ``\\binom``, ``\\arcsin``,
``\\arctan``, ``\\Delta``, the ``\\fracNN`` single-token shorthand, claim
separators (``\\Rightarrow``/``\\to``/``\\iff``), and the Unicode math actually
in the corpus — with ``²`` mapped to ``**2`` BEFORE any NFKC pass, which would
otherwise silently turn it into a coefficient 2.

``sympy`` is a lazy optional dependency (§9.7): absent sympy, every claim
routes to ``not_checkable`` with ``scope="verifier_unavailable"`` (§9.6) and
``math_verifier_available()`` reports False; the test suite fails rather than
skips in that state. Symbolic work runs in a worker thread under the per-claim
(2s) and per-turn (5s) deadlines; a timeout is ``not_checkable`` with the
timeout recorded in ``scope``.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as _FutureTimeoutError
from dataclasses import replace
import re
import time
import unicodedata

from deeptutor.math_semantic.expression import MathExpression, MathInputError, _contains_cjk

MATH_VALIDATOR_VERSION = "sympy_claim_check_v3"
STRONG_IDENTITY_MARKERS = ("恒等", "恒成立", "展开为", "展开得")
SYMPY_PER_CLAIM_TIMEOUT_SECONDS = 2.0
SYMPY_PER_TURN_TIMEOUT_SECONDS = 5.0
_CLAIM_SEPARATOR = ";;"
_SUPERSCRIPTS = {
    "⁰": "0",
    "¹": "1",
    "²": "2",
    "³": "3",
    "⁴": "4",
    "⁵": "5",
    "⁶": "6",
    "⁷": "7",
    "⁸": "8",
    "⁹": "9",
    "⁺": "+",
    "⁻": "-",
    "ⁿ": "n",
}
_SUPERSCRIPT_RUN_RE = re.compile("[" + "".join(_SUPERSCRIPTS) + "]+")
_REWRITE_RULES: tuple[tuple[str, str], ...] = (
    ("\\\\Rightarrow|\\\\rightarrow|\\\\implies|\\\\to(?![A-Za-z])", " ;; "),
    ("\\\\iff|\\\\Leftrightarrow|\\\\leftrightarrow", " ;; "),
    ("\\\\left|\\\\right|\\\\,|\\\\;|\\\\!|\\\\quad|\\\\qquad|\\\\displaystyle", ""),
    ("\\\\cdot|\\\\times", "*"),
    ("\\\\div", "/"),
    ("\\\\binom\\{([^{}]*)\\}\\{([^{}]*)\\}", "binomial(\\1,\\2)"),
    ("\\\\d?frac\\{([^{}]*)\\}\\{([^{}]*)\\}", "((\\1)/(\\2))"),
    ("\\\\sqrt\\{([^{}]*)\\}", "sqrt(\\1)"),
    ("\\\\arcsin", "asin"),
    ("\\\\arccos", "acos"),
    ("\\\\arctan", "atan"),
    ("\\\\Delta", "Delta"),
    ("\\\\leq|\\\\le(?![A-Za-z])", "<="),
    ("\\\\geq|\\\\ge(?![A-Za-z])", ">="),
    ("\\\\neq|\\\\ne(?![A-Za-z])", "!="),
    ("\\\\pi", "pi"),
    ("\\^\\{([^{}]*)\\}", "**(\\1)"),
    ("\\^([A-Za-z0-9])", "**\\1"),
    ("_\\{([^{}]*)\\}", "_\\1"),
    ("[{}]", ""),
    ("\\\\d?frac(\\d)(\\d)", "((\\1)/(\\2))"),
)
_STANDALONE_EQUALS_RE = re.compile("(?<![<>!])=")
_RESIDUE_RE = re.compile("\\\\|[^\\x00-\\x7f]")
_MATH_DELIMITERS = ("$", "\\(", "\\)")
_sympy_available: bool | None = None


def math_verifier_available() -> bool:
    """True iff the optional sympy dependency is importable (lazy, cached, §9.7)."""
    global _sympy_available
    if _sympy_available is None:
        try:
            __import__("sympy")
        except Exception:
            _sympy_available = False
        else:
            _sympy_available = True
    return _sympy_available


def _strip_math_delimiters(text: str) -> str:
    out = text.strip()
    changed = True
    while changed:
        changed = False
        for token in _MATH_DELIMITERS:
            if out.startswith(token):
                out = out[len(token) :].lstrip()
                changed = True
            if out.endswith(token):
                out = out[: -len(token)].rstrip()
                changed = True
    return out


def _premap_unicode(text: str) -> str:
    """Unicode math -> ASCII BEFORE NFKC (NFKC would fold ² into a coefficient 2)."""

    def _superscript(match: re.Match[str]) -> str:
        body = "".join((_SUPERSCRIPTS[ch] for ch in match.group(0)))
        return f"**({body})"

    out = _SUPERSCRIPT_RUN_RE.sub(_superscript, text)
    out = out.replace("−", "-")
    out = out.replace("≤", "<=")
    out = out.replace("≥", ">=")
    out = out.replace("Δ", "Delta")
    out = re.sub("[⇒→⇔]", " ;; ", out)
    out = re.sub("\\u221a\\(([^()]*)\\)", "sqrt(\\1)", out)
    out = re.sub("\\u221a([0-9A-Za-z]+)", "sqrt(\\1)", out)
    return out


_INVISIBLE_RE = re.compile(
    "[\\u00ad\\u034f\\u061c\\u180e\\u200b-\\u200f\\u202a-\\u202e\\u2060-\\u2064\\ufeff]"
)
_MATH_VARIANT_FOLD = {
    8722: "-",
    8727: "*",
    8901: "*",
    215: "*",
    8725: "/",
    8260: "/",
    247: "/",
    8804: "<=",
    8805: ">=",
    8800: "!=",
    178: "^2",
    179: "^3",
    185: "^1",
    **{8304 + offset: f"^{digit}" for offset, digit in enumerate("0123456789")},
    **{8320 + offset: f"_{digit}" for offset, digit in enumerate("0123456789")},
}
_STRIPPED_LITERAL_SPACING = "[\\s\u3000，。！？、；：,!?;:#（）()\\[\\]{}]"


def math_text_key(text: str) -> str:
    """Canonical ASCII key used to compare mathematical literals.

    This is a *comparison* form, not an evaluatable form: it drops spacing and
    punctuation and folds spelling variants, so ``x＝2``, ``ｘ＝２``, ``x\\u200b=2``
    and ``x=2`` all reduce to the same key.  Use ``normalize_display`` when the
    text still needs to be parsed or checked for unsupported residue.
    """
    if not isinstance(text, str):
        return ""
    out = _INVISIBLE_RE.sub("", text)
    out = out.translate(_MATH_VARIANT_FOLD)
    out = unicodedata.normalize("NFKC", out)
    return re.sub(_STRIPPED_LITERAL_SPACING, "", out).casefold()


def normalize_display(text: str) -> str:
    """Bounded ordered LaTeX→ASCII rewrite (§9.2/§9.3); never guesses.

    Unsupported macros and non-ASCII characters survive on purpose so the
    residue check can route the claim to ``not_checkable``.
    """
    if not isinstance(text, str):
        return ""
    out = _strip_math_delimiters(text)
    out = _premap_unicode(out)
    out = unicodedata.normalize("NFKC", out)
    for pattern, replacement in _REWRITE_RULES:
        out = re.sub(pattern, replacement, out)
    return re.sub("\\s+", " ", out).strip()


def display_translatable(display: str) -> bool:
    """True iff ``display`` normalizes to pure ASCII with no macro residue."""
    normalized = normalize_display(display)
    return bool(normalized) and (not _RESIDUE_RE.search(normalized))


def identity_intent_corroborated(claim: MathExpression, support_text: str = "") -> bool:
    """Independent identity-intent evidence: kind is ``algebraic_identity`` AND
    a strong identity/expansion marker appears in the gloss or support text."""
    if claim.kind != "algebraic_identity":
        return False
    gloss = claim.gloss or ""
    support = support_text or ""
    return any((marker in gloss or marker in support for marker in STRONG_IDENTITY_MARKERS))


def _parse_symbolic(text: str, *, local_dict: dict | None = None):
    """Guard global-name collisions without changing implicit symbol splitting."""
    import sympy
    from sympy.parsing.sympy_parser import (
        convert_xor,
        implicit_multiplication_application,
        parse_expr,
        standard_transformations,
    )

    names = set(re.findall("[A-Za-z_][A-Za-z0-9_]*", text))
    local = {}
    for name in names | {letter for word in names if word.isalpha() for letter in word}:
        value = vars(sympy).get(name)
        if name in vars(sympy) and (
            not (
                isinstance(value, sympy.FunctionClass)
                or (isinstance(value, sympy.Basic) and value.is_number)
                or name == "sqrt"
            )
        ):
            local[name] = sympy.Symbol(name)
    local.update(local_dict or {})
    return parse_expr(
        text,
        local_dict=local,
        transformations=standard_transformations
        + (convert_xor, implicit_multiplication_application),
    )


def _structural_check(expr_text: str, intent: bool) -> tuple[str, str, str | None]:
    """Asymmetric structural classification of one normalized proposition."""
    from sympy import expand, simplify

    sides = _STANDALONE_EQUALS_RE.split(expr_text)
    if len(sides) != 2:
        return ("not_checkable", "not_single_equality", None)
    left = _parse_symbolic(sides[0].strip())
    right = _parse_symbolic(sides[1].strip())
    if left.free_symbols != right.free_symbols:
        return ("not_checkable", "asymmetric_free_symbols", None)
    delta = expand(left - right)
    zero = delta.is_zero
    if zero is None:
        zero = simplify(delta) == 0
    if zero:
        return ("verified", "identity_proven", None)
    residual = str(simplify(delta))
    if not (left.free_symbols or right.free_symbols):
        return ("refuted", "arithmetic_mismatch", residual)
    if intent:
        return ("refuted", "identity_refuted", residual)
    return ("conditional_equation", "no_identity_intent_evidence", None)


def _run_structural_check(
    expr_text: str, intent: bool, deadline_monotonic: float
) -> tuple[str, str, str | None]:
    budget = deadline_monotonic - time.monotonic()
    if budget <= 0:
        return ("not_checkable", "timeout", None)
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(_structural_check, expr_text, intent)
        try:
            return future.result(timeout=budget)
        except _FutureTimeoutError:
            return ("not_checkable", "timeout", None)
        except Exception as exc:
            return ("not_checkable", type(exc).__name__, None)
    finally:
        executor.shutdown(wait=False)


_STATUS_SEVERITY = ("refuted", "conditional_equation", "not_checkable")


def _compose_outcomes(outcomes: list[tuple[str, str, str | None]]) -> tuple[str, str, str | None]:
    """Multi-part claims (claim separators): each part is checked separately."""
    for status in _STATUS_SEVERITY:
        for outcome in outcomes:
            if outcome[0] == status:
                return outcome
    return ("verified", "identity_proven", None)


def validate_math_claim(
    claim: MathExpression, *, support_text: str = "", turn_deadline_monotonic: float | None = None
) -> MathExpression:
    """Validate one math claim; returns a new MathExpression with status/scope/residual.

    - CJK in ``display`` is a structural MathInputError (§9.2);
    - missing sympy -> not_checkable with scope="verifier_unavailable" (§9.6);
    - untranslatable residue -> not_checkable, never guessed (§9.3);
    - per-claim 2s / per-turn (``turn_deadline_monotonic``) budgets; timeout ->
      not_checkable with the timeout recorded in scope;
    - ``scope`` always names the mechanism and the normalized form (ARCH-13).
    """
    if _contains_cjk(claim.display):
        raise MathInputError(
            f"math claim display must be pure mathematics, prose belongs in gloss (§9.2): {claim.display!r}"
        )
    if not math_verifier_available():
        return replace(claim, status="not_checkable", scope="verifier_unavailable", residual=None)
    normalized = normalize_display(claim.display)
    if not normalized or _RESIDUE_RE.search(normalized):
        return replace(
            claim,
            status="not_checkable",
            scope=f"{MATH_VALIDATOR_VERSION}:untranslatable_display:{normalized}",
            residual=None,
        )
    intent = identity_intent_corroborated(claim, support_text)
    now = time.monotonic()
    turn_remaining = (
        SYMPY_PER_TURN_TIMEOUT_SECONDS
        if turn_deadline_monotonic is None
        else turn_deadline_monotonic - now
    )
    deadline = now + min(SYMPY_PER_CLAIM_TIMEOUT_SECONDS, turn_remaining)
    parts = [part.strip() for part in normalized.split(_CLAIM_SEPARATOR) if part.strip()]
    if not parts:
        return replace(
            claim,
            status="not_checkable",
            scope=f"{MATH_VALIDATOR_VERSION}:empty_display:{normalized}",
            residual=None,
        )
    outcomes = [_run_structural_check(part, intent, deadline) for part in parts]
    status, detail, residual = _compose_outcomes(outcomes)
    return replace(
        claim,
        status=status,
        scope=f"{MATH_VALIDATOR_VERSION}:{detail}:{normalized}",
        residual=residual if status == "refuted" else None,
    )


def _equivalent_worker(left_text: str, right_text: str) -> bool:
    from sympy import Symbol, simplify

    left_parts = _STANDALONE_EQUALS_RE.split(left_text)
    right_parts = _STANDALONE_EQUALS_RE.split(right_text)
    left_is_equation = len(left_parts) == 2
    right_is_equation = len(right_parts) == 2
    if left_is_equation and right_is_equation:
        lhs_one = _parse_symbolic(left_parts[0].strip())
        rhs_one = _parse_symbolic(left_parts[1].strip())
        lhs_two = _parse_symbolic(right_parts[0].strip())
        rhs_two = _parse_symbolic(right_parts[1].strip())
        return simplify(lhs_one - rhs_one - (lhs_two - rhs_two)) == 0
    if not left_is_equation and (not right_is_equation):
        if len(left_parts) != 1 or len(right_parts) != 1:
            return False
        left = _parse_symbolic(left_parts[0].strip())
        right = _parse_symbolic(right_parts[0].strip())
        return simplify(left - right) == 0
    equation_parts = left_parts if left_is_equation else right_parts
    bare_parts = right_parts if left_is_equation else left_parts
    if len(bare_parts) != 1:
        return False
    lhs = _parse_symbolic(equation_parts[0].strip())
    rhs = _parse_symbolic(equation_parts[1].strip())
    bare = _parse_symbolic(bare_parts[0].strip())
    if isinstance(lhs, Symbol):
        return simplify(rhs - bare) == 0
    if isinstance(rhs, Symbol):
        return simplify(lhs - bare) == 0
    return False


def equation_residuals_correspond(left: str, right: str) -> bool:
    """Atomic nonzero polynomial-residual check after Alignment's scope guards."""

    def check():
        from sympy import simplify

        sides = tuple(
            (tuple((_parse_symbolic(p.strip()) for p in text.split("="))) for text in (left, right))
        )
        if any((len(parts) != 2 for parts in sides)):
            return False
        symbols = set().union(*(p.free_symbols for parts in sides for p in parts))
        if len(symbols) < 2 or not all(
            (p.is_polynomial(*symbols) for parts in sides for p in parts)
        ):
            return False
        a, b = (simplify(lhs - rhs) for lhs, rhs in sides)
        return a != 0 and b != 0 and (simplify(a - b) == 0 or simplify(a + b) == 0)

    if not math_verifier_available():
        return False
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        return bool(executor.submit(check).result(timeout=SYMPY_PER_CLAIM_TIMEOUT_SECONDS))
    except Exception:
        return False
    finally:
        executor.shutdown(wait=False)


def answers_equivalent(left: str, right: str) -> bool:
    """Mathematical equivalence of two answer strings; never raises, never guesses.

    Handles expression/expression ("1/2" vs "0.5"), equation/equation
    ("x=1/2" vs "x=0.5") and "var=value" against a bare value ("c=1" vs "1").
    Untranslatable or unparsable input, missing sympy, or a timeout all
    return False (the lexical channel remains the caller's first check).
    """
    if not isinstance(left, str) or not isinstance(right, str):
        return False
    if not left.strip() or not right.strip() or _contains_cjk(left) or _contains_cjk(right):
        return False
    if not math_verifier_available():
        return False
    normalized_left = normalize_display(left)
    normalized_right = normalize_display(right)
    if (
        not normalized_left
        or not normalized_right
        or _RESIDUE_RE.search(normalized_left)
        or _RESIDUE_RE.search(normalized_right)
    ):
        return False
    deadline = time.monotonic() + SYMPY_PER_CLAIM_TIMEOUT_SECONDS
    budget = deadline - time.monotonic()
    if budget <= 0:
        return False
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(_equivalent_worker, normalized_left, normalized_right)
        try:
            return bool(future.result(timeout=budget))
        except Exception:
            return False
    finally:
        executor.shutdown(wait=False)
