"""Provider request guidance is speech-act context, never relaxed response authority."""

from dataclasses import asdict
import json

import pytest

from deeptutor.math_semantic.alignment import AlignmentEvaluator
from deeptutor.math_semantic.proposals import AlignmentProposal, resolve_evidence

from .test_state_oracle import snapshot


def test_native_projection_serializes_guidance_without_changing_math_context():
    source = snapshot("ca02")
    text = "My submitted equality is p+1=q. I am unsure; can you check it?"
    projected = AlignmentEvaluator._project(text, source)
    wire = json.loads(json.dumps(asdict(projected)))
    assert isinstance(wire.pop("extraction_guidance"), str)
    assert wire["response_text"] == text
    assert wire["workspace_id"] == source.workspace.workspace_id
    assert wire["workspace_revision"] == source.workspace.revision
    assert wire["projected_refs"] == list(projected.projected_refs)
    assert wire["artifacts"] == json.loads(json.dumps([asdict(a) for a in projected.artifacts]))
    assert source == snapshot("ca02")


@pytest.mark.parametrize(
    "text,quote,interaction",
    [
        ("Which algebra step should I try?", None, "question"),
        ("Please explain the worksheet's p+1=q; I am only quoting it.", None, "question"),
        ("My line is p+1=q. I am unsure; can you check it?", "p+1=q", "answer"),
        (
            "The worksheet says p+1=q. My submitted line is p-1=r. Can you check my line?",
            "p-1=r",
            "answer",
        ),
        (
            "My submitted step is (m+2)^2=m^2+4*m+4. Could you check it?",
            "(m+2)^2=m^2+4*m+4",
            "answer",
        ),
    ],
)
def test_existing_response_schema_preserves_assertion_and_exact_speech_span(
    text, quote, interaction
):
    claims = (
        [
            {
                "evidence": {"quote": quote, "occurrence": 0},
                "claim_type": "equation",
                "parse_status": "parsed",
                "uncertainty": 0.8,
            }
        ]
        if quote
        else []
    )
    result = AlignmentProposal.from_value(
        {"claims": claims, "novel_paths": [], "interaction_type": interaction}
    )
    assert result.interaction_type == interaction
    assert len(result.claims) == len(claims)
    if quote:
        assert resolve_evidence(text, result.claims[0].evidence).quote == quote
        assert result.claims[0].uncertainty == 0.8
    # These are schema fixtures, not evidence that a real model classifies text.


@pytest.mark.parametrize("interaction", ["question", "clarification"])
def test_guidance_does_not_repair_or_discard_illegal_question_claims(interaction):
    raw = {
        "claims": [{"evidence": {"quote": "p+1=q"}, "claim_type": "equation"}],
        "novel_paths": [],
        "interaction_type": interaction,
    }
    before = json.dumps(raw, sort_keys=True)
    with pytest.raises(
        ValueError, match="questions must not be represented as asserted math claims"
    ):
        AlignmentProposal.from_value(raw)
    assert json.dumps(raw, sort_keys=True) == before


def test_request_guidance_is_not_an_accepted_response_field():
    raw = {"claims": [], "interaction_type": "question", "extraction_guidance": "use answer"}
    with pytest.raises(ValueError, match="alignment proposal contains unknown fields"):
        AlignmentProposal.from_value(raw)
