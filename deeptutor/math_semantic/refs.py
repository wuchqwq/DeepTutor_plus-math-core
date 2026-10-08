from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LearnerRef:
    space_id: str
    learner_id: str


@dataclass(frozen=True, slots=True)
class QuestionRef:
    question_id: str
    revision: int


@dataclass(frozen=True, slots=True)
class SourceRef:
    kind: str
    identifier: str
