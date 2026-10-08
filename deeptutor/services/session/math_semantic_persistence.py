"""Optional math domain adapter for the audited host mutation port.

No capability registers or calls this in product routing. Composition supplies
reviewed episode/source and the complete accepted episode prefix; resolving
those bindings is deferred to MATH-TURN-CAPABILITY-02. SQL stays in this host
owner. The mathematical value has no SQLite/connection/commit dependency.
"""

from __future__ import annotations

from collections.abc import Callable
import json
from typing import TypeVar, cast

from deeptutor.core.context import TurnMutationSQL, TurnRuntimeContext
from deeptutor.math_semantic.accepted import AcceptedSubmission
from deeptutor.math_semantic.state import MathMutation, MathMutationAuthority, ReviewedSource

Result = TypeVar("Result")


def accepted_submission(runtime: TurnRuntimeContext, *, session_id: str) -> AcceptedSubmission:
    if runtime.accepted_user_message_id is None or runtime.accepted_user_content is None:
        raise ValueError("this execution has no newly accepted submission")
    if not session_id or not runtime.turn_id:
        raise ValueError("accepted submission requires host session and turn identity")
    return AcceptedSubmission(
        runtime.accepted_user_message_id,
        runtime.accepted_user_content,
        session_id,
        runtime.turn_id,
        runtime.client_submission_id,
    )


def sqlite_math_mutation(
    runtime: TurnRuntimeContext,
    *,
    session_id: str,
    source: ReviewedSource,
    accepted_prefix: tuple[int, ...],
) -> MathMutationAuthority:
    submission = accepted_submission(runtime, session_id=session_id)
    host_mutation = runtime.run_durable_turn_mutation
    if host_mutation is None:
        raise ValueError("mathematical mutation requires protected host commit authority")
    if type(submission.message_id) is not int:
        raise ValueError("SQLite mathematical persistence requires a native SQLite message ID")
    if (
        not accepted_prefix
        or any(type(message_id) is not int for message_id in accepted_prefix)
        or len(accepted_prefix) > 32
        or len(set(accepted_prefix)) != len(accepted_prefix)
        or accepted_prefix[-1] != submission.message_id
    ):
        raise ValueError("complete bounded accepted episode prefix is required")

    def read_submission(sql: TurnMutationSQL, message_id: int) -> AcceptedSubmission:
        rows = sql(
            "SELECT id, session_id, role, content, metadata_json FROM messages WHERE id = ?",
            (message_id,),
        )
        if len(rows) != 1 or rows[0][1] != session_id or rows[0][2] != "user":
            raise ValueError("accepted evidence row is missing or foreign")
        metadata = json.loads(rows[0][4])
        value = AcceptedSubmission(
            rows[0][0],
            rows[0][3],
            session_id,
            metadata.get("turn_id", ""),
            metadata.get("client_submission_id"),
        )
        if message_id == submission.message_id and value != submission:
            raise ValueError("accepted submission differs from the durable user row")
        return value

    async def run(mutation: Callable[[MathMutation], Result]) -> Result:
        def commit(sql: TurnMutationSQL) -> Result:
            prefix = tuple(read_submission(sql, message_id) for message_id in accepted_prefix)
            records = sql(
                "SELECT session_id, math_revision, payload_json FROM math_semantic_episodes WHERE episode_id = ?",
                (source.identity.episode_id,),
            )
            if records and records[0][0] != session_id:
                raise ValueError("mathematical episode belongs to a foreign host session")
            state = MathMutation(source, submission, prefix, records[0][2] if records else None)
            result = mutation(state)
            if records:
                rows = sql(
                    "UPDATE math_semantic_episodes SET math_revision = ?, payload_json = ? WHERE episode_id = ? AND session_id = ? AND math_revision = ? RETURNING episode_id",
                    (
                        state.snapshot().workspace.revision,
                        state.serialize(),
                        source.identity.episode_id,
                        session_id,
                        records[0][1],
                    ),
                )
                if len(rows) != 1:
                    raise ValueError("mathematical persistence basis changed")
            else:
                sql(
                    "INSERT INTO math_semantic_episodes (episode_id, session_id, math_revision, payload_json) VALUES (?, ?, ?, ?)",
                    (
                        source.identity.episode_id,
                        session_id,
                        state.snapshot().workspace.revision,
                        state.serialize(),
                    ),
                )
            return result

        return cast(Result, await host_mutation(commit))

    return run
