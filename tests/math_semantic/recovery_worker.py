"""Independent-process runtime harness; pending mode is killed without cleanup."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from .recovery_support import A, B, C, RecoveryHost, durable


def report(value):
    print("RECOVERY_REPORT " + json.dumps({"pid": os.getpid(), **value}), flush=True)


async def run(args):
    unknown = "unknown" in args.action
    host = RecoveryHost(Path(args.db), unknown=unknown, advance=args.action.startswith("seed"))
    try:
        if args.action.startswith("seed"):
            session, turn = await host.submit(A)
            if args.action != "seed_unknown":
                _, turn = await host.start(B, session_id=session["id"])
                card = await host.choice(turn)
                if args.action == "seed_pending":
                    report(
                        {
                            "session": session["id"],
                            "turn": turn["id"],
                            "card": card,
                            "durable": durable(host.store.db_path),
                        }
                    )
                    # Parent terminates this real worker after the ledger and
                    # waiting_input row commit. No runtime.close/finally runs.
                    await asyncio.Event().wait()
                await host.answer(turn, card)
                await host.finish(turn)
            report(
                {
                    "session": session["id"],
                    "turn": turn["id"],
                    "durable": durable(host.store.db_path),
                    "result": host.result(),
                }
            )
        else:
            # Different, uniquely path-B evidence must not bypass pending.
            content = "unsupported semantic relation" if unknown else C
            session, turn = await host.start(content, session_id=args.session, application=True)
            card = None
            if args.action == "continue_pending":
                card = await host.choice(turn)
                before_reply = durable(host.store.db_path)
                await host.answer(turn, card, token="forged-token")
                await host.finish(turn, error="confirmation token")
            else:
                await host.finish(turn)
                before_reply = None
            old = await host.store.get_turn(args.old_turn)
            report(
                {
                    "session": session["id"],
                    "turn": turn["id"],
                    "durable": durable(host.store.db_path),
                    "history": host.history[-1],
                    "card": card,
                    "before_reply": before_reply,
                    "old_turn": old,
                    "result": None if host.errors else host.result(),
                }
            )
    finally:
        await host.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action")
    parser.add_argument("db")
    parser.add_argument("--session")
    parser.add_argument("--old-turn")
    asyncio.run(run(parser.parse_args()))
