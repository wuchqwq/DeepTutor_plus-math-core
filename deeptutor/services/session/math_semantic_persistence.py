"""Optional math domain adapter for the audited host mutation port.

No capability registers this in product routing. Trusted composition supplies
reviewed episode/source and its accepted start row; the capability's port
certifies the complete ordered prefix inside the protected transaction. The
explicit-prefix port remains for extraction contract tests. SQL stays in this
host owner. The mathematical value has no connection/commit dependency.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
from typing import TypeVar, cast

from deeptutor.core.context import TurnMutationSQL, TurnRuntimeContext
from deeptutor.math_semantic.accepted import AcceptedSubmission
from deeptutor.math_semantic.state import MathMutation, MathMutationAuthority, ReviewedSource

Result = TypeVar("Result")


@dataclass(frozen=True, slots=True)
class MathEpisodeBinding:
    """Trusted host DI, never request metadata: one contiguous solving episode.

    A new episode starts at a real accepted row, independently of question ID.
    Starting another episode closes the preceding interval to further writes.
    Reviewed learner/question scope must be resolved by the composing host.
    """

    session_id: str
    first_message_id: int
    source: ReviewedSource

    def __post_init__(self) -> None:
        if not self.session_id or type(self.first_message_id) is not int:
            raise ValueError("episode requires a host session and accepted start row")


def sqlite_episode_mutation(
    runtime: TurnRuntimeContext, *, session_id: str, binding: MathEpisodeBinding
) -> MathMutationAuthority:
    if binding.session_id != session_id:
        raise ValueError("foreign host episode binding")
    return sqlite_math_mutation(
        runtime,
        session_id=session_id,
        source=binding.source,
        first_message_id=binding.first_message_id,
    )


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
    accepted_prefix: tuple[int, ...] | None = None,
    first_message_id: int | None = None,
) -> MathMutationAuthority:
    submission = accepted_submission(runtime, session_id=session_id)
    host_mutation = runtime.run_durable_turn_mutation
    if host_mutation is None:
        raise ValueError("mathematical mutation requires protected host commit authority")
    if type(submission.message_id) is not int:
        raise ValueError("SQLite mathematical persistence requires a native SQLite message ID")
    if (accepted_prefix is None) == (first_message_id is None):
        raise ValueError("exactly one accepted prefix or host episode start is required")
    if first_message_id is not None and (
        type(first_message_id) is not int or first_message_id > submission.message_id
    ):
        raise ValueError("episode start must be a prior or current accepted row")
    if accepted_prefix is not None and (
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
        if first_message_id is not None:
            turns = sql("SELECT session_id FROM turns WHERE id = ?", (value.turn_id,))
            if len(turns) != 1 or turns[0][0] != session_id:
                raise ValueError("accepted row has no matching host turn")
        return value

    async def run(mutation: Callable[[MathMutation], Result]) -> Result:
        def commit(sql: TurnMutationSQL) -> Result:
            ids = accepted_prefix
            if first_message_id is not None:
                ids = tuple(
                    row[0]
                    for row in sql(
                        "SELECT id FROM messages WHERE session_id = ? AND role = 'user' AND id >= ? AND id <= ? ORDER BY id",
                        (session_id, first_message_id, submission.message_id),
                    )
                )
                if (
                    not ids
                    or ids[0] != first_message_id
                    or ids[-1] != submission.message_id
                    or len(ids) > 32
                ):
                    raise ValueError("complete bounded host episode prefix is missing")
                # Existing aggregates certify ownership of earlier intervals;
                # no second response ledger or client-supplied assignment.
                for other_id, other_payload in sql(
                    "SELECT episode_id, payload_json FROM math_semantic_episodes WHERE session_id = ?",
                    (session_id,),
                ):
                    other = json.loads(other_payload)
                    other_start = other.get("host_episode_first_message_id")
                    if (
                        other_id != source.identity.episode_id
                        and other_start is not None
                        and (
                            other_start >= first_message_id
                            or set(ids) & set(other.get("host_accepted_message_ids", ()))
                        )
                    ):
                        raise ValueError("host episode interval was superseded")
            assert ids is not None
            prefix = tuple(read_submission(sql, message_id) for message_id in ids)
            if first_message_id is not None and len({item.turn_id for item in prefix}) != len(
                prefix
            ):
                raise ValueError("accepted prefix repeats a host turn")
            records = sql(
                "SELECT session_id, math_revision, payload_json FROM math_semantic_episodes WHERE episode_id = ?",
                (source.identity.episode_id,),
            )
            if records and records[0][0] != session_id:
                raise ValueError("mathematical episode belongs to a foreign host session")
            if first_message_id is not None and records:
                old = json.loads(records[0][2])
                old_ids = tuple(old.get("host_accepted_message_ids", ()))
                if (
                    old.get("host_episode_first_message_id") != first_message_id
                    or ids[: len(old_ids)] != old_ids
                ):
                    raise ValueError("host episode binding or accepted basis changed")
            state = MathMutation(source, submission, prefix, records[0][2] if records else None)
            result = mutation(state)
            payload = json.loads(state.serialize())
            if first_message_id is not None:
                payload["host_episode_first_message_id"] = first_message_id
                payload["host_accepted_message_ids"] = ids
            serialized = json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            if records:
                rows = sql(
                    "UPDATE math_semantic_episodes SET math_revision = ?, payload_json = ? WHERE episode_id = ? AND session_id = ? AND math_revision = ? RETURNING episode_id",
                    (
                        state.snapshot().workspace.revision,
                        serialized,
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
                        serialized,
                    ),
                )
            return result

        return cast(Result, await host_mutation(commit))

    return run
