"""Bounded mathematical validation through neutral request/result values."""

from __future__ import annotations

from dataclasses import dataclass
import multiprocessing
import queue
import time
from typing import Any


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
