"""Read the host's accepted submission seam, never a prompt or model value."""

from __future__ import annotations

from dataclasses import dataclass

from .refs import LearnerRef, QuestionRef


@dataclass(frozen=True, slots=True)
class AcceptedSubmission:
    message_id: int | str
    raw_content: str
    session_id: str
    turn_id: str
    client_submission_id: str | None = None

    @property
    def response_id(self) -> str:
        # Reference representation of a real host row, never a text identity.
        return str(self.message_id)

    def text_content(self) -> str:
        return self.raw_content


@dataclass(frozen=True, slots=True)
class EpisodeIdentity:
    """Trusted DI input. Session-to-episode resolution belongs to Capability-02."""

    episode_id: str
    learner: LearnerRef
    question_ref: QuestionRef
