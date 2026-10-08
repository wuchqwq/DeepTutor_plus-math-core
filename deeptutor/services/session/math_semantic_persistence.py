"""Optional math domain adapter for the audited host mutation port.

No capability registers this in product routing. Trusted composition supplies
reviewed episode/source. The port recovers its durable start (or accepts an
explicit start) and certifies the complete prefix in the protected transaction.
The explicit-prefix port remains for extraction contract tests. SQL stays in this
host owner. The mathematical value has no connection/commit dependency.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
from typing import TypeVar, cast

from deeptutor.core.context import CapabilityBinding, TurnMutationSQL, TurnRuntimeContext
from deeptutor.math_semantic.accepted import AcceptedSubmission
from deeptutor.math_semantic.state import MathMutation, MathMutationAuthority, ReviewedSource

Result = TypeVar("Result")


@dataclass(frozen=True, slots=True)
class MathEpisodeBinding:
    """Trusted host DI, never request metadata: one reviewed solving episode.

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
    runtime: TurnRuntimeContext, *, session_id: str, binding: MathEpisodeBinding | ReviewedSource
) -> MathMutationAuthority:
    """Certify an explicit binding, or recover history for reviewed source DI.

    ReviewedSource carries no accepted row/history. Existing aggregates must
    retain their certified start/basis; a new aggregate starts at its earliest
    durably attributed accepted row. Ordinary gaps are not math evidence.
    A damaged existing aggregate is never reinitialized.
    """
    # Fresh composition needs only reviewed identity/content. The accepted
    # start and history are recovered and certified under commit authority.
    if isinstance(binding, ReviewedSource):
        return sqlite_math_mutation(
            runtime, session_id=session_id, source=binding, recover_episode=True
        )
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
    recover_episode: bool = False,
) -> MathMutationAuthority:
    submission = accepted_submission(runtime, session_id=session_id)
    host_mutation = runtime.run_durable_turn_mutation
    if host_mutation is None:
        raise ValueError("mathematical mutation requires protected host commit authority")
    if type(submission.message_id) is not int:
        raise ValueError("SQLite mathematical persistence requires a native SQLite message ID")
    current_message_id = cast(int, submission.message_id)
    if sum((accepted_prefix is not None, first_message_id is not None, recover_episode)) != 1:
        raise ValueError("exactly one accepted prefix, episode start or recovery is required")
    certified_episode = first_message_id is not None or recover_episode
    if certified_episode and runtime.capability_binding != CapabilityBinding(
        "math_turn", source.identity.episode_id
    ):
        raise ValueError("math episode requires the exact trusted host capability binding")
    if first_message_id is not None and (
        type(first_message_id) is not int or first_message_id > current_message_id
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

    def read_submission(
        sql: TurnMutationSQL, message_id: int, legacy_ids: tuple[int, ...]
    ) -> AcceptedSubmission:
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
        if certified_episode:
            turns = sql("SELECT session_id FROM turns WHERE id = ?", (value.turn_id,))
            if len(turns) != 1 or turns[0][0] != session_id:
                raise ValueError("accepted row has no matching host turn")
            marker = {
                "turn_id": value.turn_id,
                "binding": {"capability": "math_turn", "scope_id": source.identity.episode_id},
            }
            if metadata.get("host_capability_binding") != marker and not (
                message_id in legacy_ids and "host_capability_binding" not in metadata
            ):
                raise ValueError("accepted row has no exact host math attribution")
        return value

    async def run(mutation: Callable[[MathMutation], Result]) -> Result:
        def commit(sql: TurnMutationSQL) -> Result:
            records = sql(
                "SELECT session_id, math_revision, payload_json FROM math_semantic_episodes WHERE episode_id = ?",
                (source.identity.episode_id,),
            )
            if records and records[0][0] != session_id:
                raise ValueError("mathematical episode belongs to a foreign host session")
            old = json.loads(records[0][2]) if records else {}
            old_ids = tuple(old.get("host_accepted_message_ids", ()))
            # Existing certified history is frozen at cutover. No unseen row
            # can be grandfathered later, and removing a new marker is never
            # mistaken for old unmarked evidence.
            ownership_version = old.get("host_math_ownership_version")
            if certified_episode and (
                (
                    ownership_version is not None
                    and (type(ownership_version) is not int or ownership_version != 1)
                )
                or ("host_legacy_accepted_message_ids" in old and ownership_version is None)
            ):
                raise ValueError("unsupported host math ownership basis")
            legacy_ids = (
                tuple(old.get("host_legacy_accepted_message_ids", ()))
                if ownership_version is not None
                else old_ids
            )
            if certified_episode and (
                any(type(item) is not int for item in (*old_ids, *legacy_ids))
                or len(old_ids) > 32
                or len(legacy_ids) > 32
                or len(set(old_ids)) != len(old_ids)
                or len(set(legacy_ids)) != len(legacy_ids)
                or not set(legacy_ids) <= set(old_ids)
            ):
                raise ValueError("invalid durable host math ownership basis")
            if certified_episode and ownership_version is None and old_ids:
                placeholders = ",".join("?" for _ in old_ids)
                marked = {
                    row[0]
                    for row in sql(
                        f"SELECT id FROM messages WHERE session_id=? AND id IN ({placeholders}) AND json_type(metadata_json, '$.host_capability_binding') IS NOT NULL",
                        (session_id, *old_ids),
                    )
                }
                legacy_ids = tuple(message_id for message_id in old_ids if message_id not in marked)
            start = first_message_id
            if recover_episode:
                # Attribution can commit before an aggregate exists. Such a
                # failed/lost first math turn still counts as missing evidence.
                if records:
                    recovered_start = old.get("host_episode_first_message_id")
                else:
                    earliest = sql(
                        "SELECT MIN(id) FROM messages WHERE session_id=? AND role='user' AND id<=? AND json_extract(metadata_json, '$.host_capability_binding.binding.capability')='math_turn' AND json_extract(metadata_json, '$.host_capability_binding.binding.scope_id')=?",
                        (session_id, current_message_id, source.identity.episode_id),
                    )
                    recovered_start = earliest[0][0]
                if type(recovered_start) is not int or recovered_start > current_message_id:
                    raise ValueError("durable episode start is missing or invalid")
                start = cast(int, recovered_start)
            ids = accepted_prefix
            if start is not None:
                # Capability columns/request snapshots are advisory. Only
                # exact host-attributed rows (or frozen old certified IDs)
                # belong to this mathematical episode, including failed math
                # turns. Ordinary gaps do not increment Core prefix ordinals.
                pinned = ",".join("?" for _ in old_ids) or "NULL"
                ids = tuple(
                    row[0]
                    for row in sql(
                        f"SELECT id FROM messages WHERE session_id = ? AND role = 'user' AND id >= ? AND id <= ? AND (id IN ({pinned}) OR (json_extract(metadata_json, '$.host_capability_binding.binding.capability') = 'math_turn' AND json_extract(metadata_json, '$.host_capability_binding.binding.scope_id') = ?)) ORDER BY id",
                        (
                            session_id,
                            start,
                            submission.message_id,
                            *old_ids,
                            source.identity.episode_id,
                        ),
                    )
                )
                if not ids or ids[0] != start or ids[-1] != submission.message_id or len(ids) > 32:
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
                            other_start >= start
                            or set(ids) & set(other.get("host_accepted_message_ids", ()))
                        )
                    ):
                        raise ValueError("host episode interval was superseded")
            assert ids is not None
            prefix = tuple(read_submission(sql, message_id, legacy_ids) for message_id in ids)
            if certified_episode and len({item.turn_id for item in prefix}) != len(prefix):
                raise ValueError("accepted prefix repeats a host turn")
            if certified_episode and records:
                if (
                    old.get("host_episode_first_message_id") != start
                    or not old_ids
                    or any(type(item) is not int for item in old_ids)
                    or ids[: len(old_ids)] != old_ids
                ):
                    raise ValueError("host episode binding or accepted basis changed")
            if certified_episode:
                # A fork cannot silently reuse sibling mathematical evidence.
                # Ordinary ancestors are omitted from the mathematical prefix;
                # a different reviewed episode may explicitly start a branch.
                ancestors = {
                    row[0]
                    for row in sql(
                        "WITH RECURSIVE lineage(id, parent_message_id, depth) AS (SELECT id, parent_message_id, 0 FROM messages WHERE id=? AND session_id=? UNION ALL SELECT m.id, m.parent_message_id, l.depth+1 FROM messages m JOIN lineage l ON m.id=l.parent_message_id WHERE m.session_id=? AND l.depth<1024) SELECT id FROM lineage",
                        (current_message_id, session_id, session_id),
                    )
                }
                if not set(ids) <= ancestors:
                    raise ValueError("math episode prefix is outside the accepted branch")
            state = MathMutation(source, submission, prefix, records[0][2] if records else None)
            if records and state.snapshot().workspace.revision != records[0][1]:
                raise ValueError("durable mathematical revision differs from the canonical head")
            result = mutation(state)
            payload = json.loads(state.serialize())
            if start is not None:
                payload["host_episode_first_message_id"] = start
                payload["host_accepted_message_ids"] = ids
                payload["host_math_ownership_version"] = 1
                payload["host_legacy_accepted_message_ids"] = legacy_ids
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
