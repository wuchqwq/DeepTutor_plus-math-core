"""Thin host adapter between DeepTutor's ``TurnCapability`` seam and the frozen
``tutor_demo`` Math Semantic Core.

This module owns exactly three host-side responsibilities and nothing else:

* the wrong-tree guard that pins the imported math engine to one reviewed
  source checkout *before* any math call is made;
* a thin adapter that drives the existing math owners (ResponseAlignment,
  TrajectoryProjection, MethodConfirmation ledger) for one protected turn;
* the trusted host wiring that binds an authenticated DeepTutor session scope
  to one reviewed math episode.

No math semantics live here. Parsing/alignment, trajectory regions, method
confirmation identity, the option-token -> path mapping and all validation stay
owned by the math engine. The adapter never lets model text, a display label or
a client-supplied ``path_ref`` select a branch.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import os
import subprocess
import sys
from threading import RLock
from typing import Any

# ---------------------------------------------------------------------------
# Wrong-tree guard: the POC must consume one exact frozen math source.
# ---------------------------------------------------------------------------

MATH_ENGINE_REPOSITORY = "wuchqwq/tutor_demo"
MATH_ENGINE_COMMIT = "76d5d9697186d086fb967e79a9e08e394b0d5474"
MATH_ENGINE_SOURCE_ENV = "DEEPTUTOR_MATH_ENGINE_SRC"

#: Modules whose tree identity is load-bearing for the protected path. Every one
#: must resolve inside the pinned ``<root>/src`` and nothing may be pre-imported
#: from another checkout.
_GUARDED_MODULES = (
    "tutor_demo.application.demo_questions",
    "tutor_demo.alignment.service",
    "tutor_demo.math_core.workspace",
    "tutor_demo.teaching_planner.evidence",
    "tutor_demo.teaching_planner.service",
)


class MathEngineSourceError(RuntimeError):
    """The imported math engine is not the intended frozen source."""


@dataclass(frozen=True)
class MathEngineModules:
    """Resolved public math-engine owners used by the adapter."""

    MathWorkspaceStore: Any
    SQLiteLearningStore: Any
    AlignmentStore: Any
    ResponseAlignmentService: Any
    ScriptedResponseAlignmentProvider: Any
    AssessmentRecord: Any
    AuthoredTextAssessor: Any
    LearnerRef: Any
    SourceRef: Any
    LearningGoal: Any
    StudentResponse: Any
    build_teaching_planner_input: Any
    resolve_learner_request: Any
    LearnerEvidenceBoundary: Any
    ReviewedMathTask: Any
    SlimTeachingPlannerStore: Any
    ca02_demo_question: Any
    ca02_problem_model: Any
    reviewed_ca02_workspace: Any
    reviewed_ca02_source: Any

    @property
    def module_paths(self) -> dict[str, str]:
        return {name: str(getattr(sys.modules[name], "__file__", "")) for name in _GUARDED_MODULES}


def _resolve_source_root(source_root: str | None) -> str:
    root = source_root or os.environ.get(MATH_ENGINE_SOURCE_ENV, "")
    if not root:
        raise MathEngineSourceError(
            f"{MATH_ENGINE_SOURCE_ENV} is not set; the protected math engine source is not pinned"
        )
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise MathEngineSourceError(f"math engine source does not exist: {root}")
    try:
        toplevel = subprocess.check_output(
            ["git", "-C", root, "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise MathEngineSourceError(f"math engine source is not a git checkout: {root}") from exc
    if os.path.normcase(os.path.abspath(toplevel)) != os.path.normcase(root):
        raise MathEngineSourceError(f"math engine source is not the repository root: {root}")
    head = subprocess.check_output(
        ["git", "-C", root, "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
    ).strip()
    if head != MATH_ENGINE_COMMIT:
        raise MathEngineSourceError(
            f"math engine source HEAD {head} != expected {MATH_ENGINE_COMMIT}"
        )
    return root


def _assert_module_origin(name: str, src_dir: str) -> None:
    module = sys.modules.get(name)
    if module is None:
        return
    path = os.path.abspath(str(getattr(module, "__file__", "") or ""))
    if not path.startswith(src_dir + os.sep):
        raise MathEngineSourceError(f"imported {name} from an unexpected checkout: {path}")


def load_math_engine(source_root: str | None = None) -> MathEngineModules:
    """Import the math owners from the pinned frozen checkout, or refuse.

    The guard runs before any math object is constructed: an unset source, a
    wrong commit, or a ``tutor_demo`` already imported from another editable
    checkout all raise rather than silently using whatever happens to be on the
    path.
    """
    root = _resolve_source_root(source_root)
    src_dir = os.path.join(root, "src")
    if not os.path.isdir(src_dir):
        raise MathEngineSourceError(f"math engine source has no src/ directory: {root}")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    for name in _GUARDED_MODULES:
        _assert_module_origin(name, src_dir)

    from tutor_demo.alignment import (  # noqa: PLC0415
        AlignmentStore,
        ResponseAlignmentService,
        ScriptedResponseAlignmentProvider,
    )
    from tutor_demo.application.demo_questions import (  # noqa: PLC0415
        ca02_demo_question,
        ca02_problem_model,
        reviewed_ca02_source,
        reviewed_ca02_workspace,
    )
    from tutor_demo.assessment import AssessmentRecord, AuthoredTextAssessor  # noqa: PLC0415
    from tutor_demo.core import LearnerRef, SourceRef  # noqa: PLC0415
    from tutor_demo.decision import LearningGoal  # noqa: PLC0415
    from tutor_demo.durable_store import SQLiteLearningStore  # noqa: PLC0415
    from tutor_demo.math_core import MathWorkspaceStore  # noqa: PLC0415
    from tutor_demo.responses import StudentResponse  # noqa: PLC0415
    from tutor_demo.teaching_planner import (  # noqa: PLC0415
        build_teaching_planner_input,
        resolve_learner_request,
    )
    from tutor_demo.teaching_planner.evidence import (  # noqa: PLC0415
        LearnerEvidenceBoundary,
        ReviewedMathTask,
    )
    from tutor_demo.teaching_planner.service import SlimTeachingPlannerStore  # noqa: PLC0415

    for name in _GUARDED_MODULES:
        _assert_module_origin(name, src_dir)

    return MathEngineModules(
        MathWorkspaceStore=MathWorkspaceStore,
        SQLiteLearningStore=SQLiteLearningStore,
        AlignmentStore=AlignmentStore,
        ResponseAlignmentService=ResponseAlignmentService,
        ScriptedResponseAlignmentProvider=ScriptedResponseAlignmentProvider,
        AssessmentRecord=AssessmentRecord,
        AuthoredTextAssessor=AuthoredTextAssessor,
        LearnerRef=LearnerRef,
        SourceRef=SourceRef,
        LearningGoal=LearningGoal,
        StudentResponse=StudentResponse,
        build_teaching_planner_input=build_teaching_planner_input,
        resolve_learner_request=resolve_learner_request,
        LearnerEvidenceBoundary=LearnerEvidenceBoundary,
        ReviewedMathTask=ReviewedMathTask,
        SlimTeachingPlannerStore=SlimTeachingPlannerStore,
        ca02_demo_question=ca02_demo_question,
        ca02_problem_model=ca02_problem_model,
        reviewed_ca02_workspace=reviewed_ca02_workspace,
        reviewed_ca02_source=reviewed_ca02_source,
    )


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReviewedMathEpisode:
    """Trusted host wiring: one authenticated session bound to one reviewed task.

    ``session_id`` is the authenticated DeepTutor conversation scope the
    capability receives. ``db_path`` is the math engine's own ledger file; the
    engine keeps its episode state there, so DeepTutor stores no math state.
    """

    session_id: str
    workspace_id: str
    db_path: str
    learner_id: str


@dataclass(frozen=True)
class MethodOption:
    """One math-owned option: opaque token + presentation label."""

    token: str
    label: str
    description: str


@dataclass(frozen=True)
class MathTurnOutcome:
    """Bounded result of one protected turn, produced by the math engine."""

    status: str
    trajectory_version: str
    compatible_path_refs: tuple[str, ...]
    applicable_artifact_refs: tuple[str, ...]
    method_labels: tuple[str, ...]
    confirmation_id: str | None
    options: tuple[MethodOption, ...]
    approved_output: str


class MathTurnUnavailable(RuntimeError):
    """The protected turn has no trusted reviewed binding and must fail closed."""


class MathTurnEngine:
    """Thin adapter: DeepTutor turn in, math-engine authority out."""

    def __init__(
        self, episode: ReviewedMathEpisode, modules: MathEngineModules | None = None
    ) -> None:
        self.episode = episode
        self._m = modules or load_math_engine()
        self._lock = RLock()
        self._active = True
        self.workspace = self._m.MathWorkspaceStore(episode.db_path)
        self.learning = self._m.SQLiteLearningStore(episode.db_path)
        self.alignments = self._m.AlignmentStore(self.workspace)
        self.ledger = self._m.SlimTeachingPlannerStore(self.workspace)
        self.question = self._m.ca02_demo_question().question
        self.model = self._m.ca02_problem_model()
        self.learner = self._m.LearnerRef(self.question.scope_id, episode.learner_id)
        self.goal = self._m.LearningGoal(
            "dt-math-turn-goal",
            self.question.target_skill,
            "continue the learner's grounded method",
        )
        self._m.reviewed_ca02_workspace(
            self.workspace, self.model, workspace_id=episode.workspace_id
        )
        # Host liveness state for the resolution guard: the id of the response
        # the authenticated turn is currently parked on. Rebuilt from the math
        # ledger at construction so a restarted adapter resumes the same scope.
        prefix = self._prefix_ids()
        self._latest_response_id: str | None = prefix[-1] if prefix else None
        self.boundary = self._m.LearnerEvidenceBoundary.durable(
            alignment_store=self.alignments,
            learning_store=self.learning,
            learner=self.learner,
            planner_store=self.ledger,
            protected_math=lambda response: (
                response.question_ref.question_id == self.question.ref.question_id
            ),
            reviewed_task=self._reviewed_task,
        )

    # -- scope ---------------------------------------------------------------

    def is_bound(self, session_id: str) -> bool:
        """True only for the authenticated session this episode was wired to."""
        return bool(session_id) and session_id == self.episode.session_id

    def close(self) -> None:
        self._active = False
        self.workspace.close()

    def _reviewed_task(self, response: Any) -> Any:
        prefix = self._prefix_ids()
        if not self._active or response.response_id not in prefix:
            raise ValueError("foreign or inactive math episode response")
        authored = self._m.reviewed_ca02_source(
            self.workspace, self.model, workspace_id=self.episode.workspace_id
        )
        expected_latest = prefix[-1]

        @contextmanager
        def guard(connection: Any) -> Any:
            with self._lock:
                # Host liveness only: never touch the ledger while it holds its
                # write transaction (that would deadlock on the shared file).
                if not self._active or expected_latest != self._latest_response_id:
                    raise ValueError("inactive or stale host scope")
                yield
                # The lock is still held: the ledger has committed inside this
                # scope, so host validation covered scope -> mutation -> commit.
                if connection.in_transaction:  # pragma: no cover - defensive
                    raise ValueError("host scope must be held through ledger commit")

        return self._m.ReviewedMathTask(
            authored,
            self.learner,
            self.question.ref,
            prefix[: response.attempt_number],
            guard,
            trajectory_version="ca02_trajectory_v1",
        )

    # -- response prefix is derived from the math ledger, never from the host --

    def _response_id(self, number: int) -> str:
        return f"dt-response:{self.episode.workspace_id}:{number}"

    def _prefix_ids(self) -> tuple[str, ...]:
        ids: list[str] = []
        number = 1
        while True:
            response = self.learning.get_response_by_id(self._response_id(number))
            if response is None:
                return tuple(ids)
            ids.append(response.response_id)
            number += 1

    # -- turn ----------------------------------------------------------------

    def run_turn(self, session_id: str, learner_text: str) -> MathTurnOutcome:
        """Drive one protected turn through the existing math owners."""
        if not self.is_bound(session_id):
            raise MathTurnUnavailable("authenticated session has no reviewed math binding")
        text = str(learner_text or "").strip()
        if not text:
            raise MathTurnUnavailable("protected math turn requires learner text")
        with self._lock:
            response = self._accept_response(text)
            context = self._build_context(response)
            return self._outcome(context)

    def _accept_response(self, text: str) -> Any:
        number = len(self._prefix_ids()) + 1
        response_id = self._response_id(number)
        response = self.learning.get_response_by_id(response_id)
        if response is None:
            response = self._m.StudentResponse.text(
                response_id, self.learner, self.question.ref, number, text
            )
            response = self.learning.accept_response(response, response_id)
        if not self.learning.assessments_for(response.response_id):
            record = self._m.AssessmentRecord.authored(
                self._m.AuthoredTextAssessor().assess(self.question, response)
            )
            self.learning.record_assessment(record, question=self.question)
        snapshot = self.workspace.load(self.episode.workspace_id)
        response_ref = self._m.SourceRef("student_response", response.response_id)
        alignment = self.alignments.find_for_response(
            response_ref, snapshot.workspace_ref, provider_digest=None, config_digest=None
        )
        if alignment is None:
            proposal = {
                "claims": [
                    {
                        "evidence": {"quote": text},
                        "claim_type": "equation",
                        "parse_status": "parsed",
                    }
                ]
            }
            provider = self._m.ScriptedResponseAlignmentProvider({text: proposal})
            self._m.ResponseAlignmentService(self.alignments, provider).align(response, snapshot)
        self._latest_response_id = response.response_id
        return response

    def _build_context(self, response: Any) -> Any:
        record = self.learning.get_assessment_by_id("assessment:" + response.response_id)
        alignment = self.alignments.find_for_response(
            self._m.SourceRef("student_response", response.response_id),
            self.workspace.load(self.episode.workspace_id).workspace_ref,
            provider_digest=None,
            config_digest=None,
        )
        return self._m.build_teaching_planner_input(
            self.workspace.load(self.episode.workspace_id),
            alignment,
            record.assessment,
            self.goal,
            self._m.resolve_learner_request(explicit="HINT", request_id="dt-math-hint"),
            learner_evidence=self.boundary,
            request_id="dt-math-plan:" + response.response_id,
        )

    def _outcome(self, context: Any) -> MathTurnOutcome:
        trajectory = context.trajectory
        confirmation = trajectory.method_confirmation
        labels = self._method_labels()
        options = (
            tuple(
                MethodOption(token=token, label=labels.get(path_ref, path_ref), description="")
                for token, path_ref in confirmation.option_paths
            )
            if confirmation is not None
            else ()
        )
        return MathTurnOutcome(
            status=trajectory.status,
            trajectory_version=trajectory.version,
            compatible_path_refs=tuple(trajectory.compatible_path_refs),
            applicable_artifact_refs=tuple(trajectory.applicable_artifact_refs),
            method_labels=tuple(labels.get(ref, ref) for ref in trajectory.compatible_path_refs),
            confirmation_id=confirmation.confirmation_id if confirmation is not None else None,
            options=options,
            approved_output=self.render_authorized(trajectory),
        )

    def _method_labels(self) -> dict[str, str]:
        snapshot = self.workspace.load(self.episode.workspace_id, revision=2)
        return {path.path_id: path.method for path in snapshot.paths}

    def render_authorized(self, trajectory: Any) -> str:
        """Render a deterministic outcome strictly from the authorized region.

        The math engine computed ``applicable_artifact_refs`` and
        ``compatible_path_refs``; this only narrates that bounded result. It does
        not dump artifact statements, so the POC cannot leak a withheld answer.
        """
        paths = ", ".join(
            self._method_labels().get(ref, ref) for ref in trajectory.compatible_path_refs
        )
        return (
            f"Protected math turn accepted by the math engine (status={trajectory.status}). "
            f"Authorized region: {len(trajectory.applicable_artifact_refs)} statements across "
            f"path(s): {paths or 'none'}."
        )

    # -- resolution ----------------------------------------------------------

    def resolve(self, session_id: str, confirmation_id: str, option_token: str) -> str:
        """Resolve one method confirmation using the exact math-owned token."""
        if not self.is_bound(session_id):
            raise MathTurnUnavailable("authenticated session has no reviewed math binding")
        with self._lock:
            prefix = self._prefix_ids()
            if not prefix:
                raise MathTurnUnavailable("no accepted math response to resolve against")
            response = self.learning.get_response_by_id(prefix[-1])
            context = self._build_context(response)
            confirmation = self.boundary.resolve_method_confirmation(
                context, confirmation_id=confirmation_id, option_token=option_token
            )
        return str(confirmation.chosen_path_ref)


# ---------------------------------------------------------------------------
# Trusted host wiring
# ---------------------------------------------------------------------------

_config: MathTurnEngine | None = None


def configure_math_turn_engine(engine: MathTurnEngine | None) -> None:
    """Trusted host wiring; the only way a protected math episode is activated.

    Unset (the default) means every protected turn fails closed.
    """
    global _config
    _config = engine


def get_math_turn_engine() -> MathTurnEngine | None:
    return _config


__all__ = [
    "MATH_ENGINE_COMMIT",
    "MATH_ENGINE_REPOSITORY",
    "MATH_ENGINE_SOURCE_ENV",
    "MathEngineModules",
    "MathEngineSourceError",
    "MathTurnEngine",
    "MathTurnOutcome",
    "MathTurnUnavailable",
    "MethodOption",
    "ReviewedMathEpisode",
    "configure_math_turn_engine",
    "get_math_turn_engine",
    "load_math_engine",
]
