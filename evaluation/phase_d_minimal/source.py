"""Explicit Phase D mathematical input; no fixture imports or authority upgrade."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from deeptutor.math_semantic.accepted import EpisodeIdentity
from deeptutor.math_semantic.alignment import AlignmentEvaluator
from deeptutor.math_semantic.contracts import MathArtifact, MathWorkspace, ProblemFact, ProblemModel, SolutionPath
from deeptutor.math_semantic.refs import LearnerRef, QuestionRef, SourceRef
from deeptutor.math_semantic.state import ReviewedSource
from deeptutor.math_semantic.workspace import MathWorkspaceSnapshot

QUESTION_ID = "phase_d_quadratic_01"
QUESTION_REVISION = 1
SCOPE = "human-reviewed algebra supplied by dot; no independent machine verification"


def make_source(episode_id: str, learner_id: str) -> ReviewedSource:
    question = SourceRef("question", QUESTION_ID)
    review = SourceRef("experiment_review", "phase_d_dot_math_review_2026_10_09")
    model = ProblemModel(
        problem_id=QUESTION_ID, public_ref=question,
        givens=(ProblemFact("x^2+x*y+y^2=3", provenance=(question,)),),
        target=ProblemFact("range of Q=x^2-x*y+y^2", provenance=(question,)),
        domain=(ProblemFact("x,y are real", provenance=(question,)),),
        provenance=(question,), revision=QUESTION_REVISION,
    )
    # These declarations are explicit experiment resources, not extracted student
    # evidence. Qualified does not become verified because a human checked them.
    statements = [
        ("given", "x^2+x*y+y^2=3", "given", "qualified"),
        ("s", "s=x+y", "definition", "qualified"),
        ("p", "p=x*y", "definition", "qualified"),
        ("s_constraint", "s^2-p=3", "intermediate", "qualified"),
        ("q_p", "Q=3-2*x*y", "intermediate", "qualified"),
        ("p_range", "-3<=p<=1", "intermediate", "qualified"),
        ("square_lower", "3*(x^2-x*y+y^2)-(x^2+x*y+y^2)=2*(x-y)^2", "intermediate", "qualified"),
        ("lower_substitution", "Q-1=(2/3)*(x-y)^2", "intermediate", "qualified"),
        ("square_upper", "3*(x^2+x*y+y^2)-(x^2-x*y+y^2)=2*(x+y)^2", "intermediate", "qualified"),
        ("upper_substitution", "9-Q=2*(x+y)^2", "intermediate", "qualified"),
        ("d", "d=x-y", "definition", "qualified"),
        ("sd_constraint", "3*s^2+d^2=12", "intermediate", "qualified"),
        ("q_s", "Q=12-2*s^2", "intermediate", "qualified"),
        ("s_range", "0<=s^2<=4", "intermediate", "qualified"),
        ("attainability", "For every s^2 in [0,4], choose real d with d^2=12-3*s^2, x=(s+d)/2, y=(s-d)/2; then the constraint holds and all Q in [1,9] are attained.", "intermediate", "not_checkable"),
        ("answer", "Q in [1,9]", "answer", "qualified"),
    ]
    artifacts = tuple(MathArtifact(
        statement=text, role=role,
        claim_kind="definition" if role == "definition" else "derived_equation",
        provenance=(question, review), verification_status=status,
        verification_scope=SCOPE,
    ) for _, text, role, status in statements)
    refs = {name: artifact.artifact_id for (name, *_), artifact in zip(statements, artifacts)}
    paths = (
        SolutionPath(method="symmetric substitution", artifact_refs=tuple(refs[n] for n in ("given", "s", "p", "s_constraint", "q_p", "p_range", "d", "sd_constraint", "q_s", "s_range", "attainability", "answer")), status="authored", completeness="unknown", provenance=(review,)),
        SolutionPath(method="square identities", artifact_refs=tuple(refs[n] for n in ("given", "square_lower", "lower_substitution", "square_upper", "upper_substitution", "attainability", "answer")), status="authored", completeness="unknown", provenance=(review,)),
    )
    workspace = MathWorkspace(episode_id, model.model_ref,
        artifact_refs=tuple(a.artifact_id for a in artifacts),
        solution_path_refs=tuple(p.path_id for p in paths))
    return ReviewedSource(EpisodeIdentity(episode_id, LearnerRef("phase_d_local", learner_id), QuestionRef(QUESTION_ID, QUESTION_REVISION)), MathWorkspaceSnapshot(workspace, model, artifacts=artifacts, paths=paths))


def write_source_evidence(source: ReviewedSource, directory: Path, student_text: str = "") -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    values = {"reviewed_source.json": asdict(source), "alignment_projection.json": asdict(AlignmentEvaluator._project(student_text, source.authored))}
    hashes = {}
    for filename, value in values.items():
        raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        (directory / filename).write_bytes(raw)
        hashes[filename] = hashlib.sha256(raw).hexdigest()
    (directory / "source_hashes.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
    return hashes
