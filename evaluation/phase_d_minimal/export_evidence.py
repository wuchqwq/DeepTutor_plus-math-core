"""Read only the experiment's real chat/Core tables; never runtime credentials."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2] / "data"
    home, evidence = args.home.resolve(), args.evidence.resolve()
    if not all(p.is_relative_to(root) for p in (home, evidence)):
        parser.error("Only this task's ignored data directory is permitted")
    database = home / "data/user/chat_history.db"
    if not database.is_file():
        parser.error("No actual SQLite database exists")
    connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        tables = {}
        for table in ("sessions", "messages", "turns", "turn_submissions", "turn_events", "math_semantic_episodes"):
            exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            if exists:
                tables[table] = [dict(row) for row in connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid')]
    finally:
        connection.close()
    raw = (json.dumps({"database": str(database), "read_only": True, "tables": tables}, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "actual_sqlite_evidence.json").write_bytes(raw)
    summary = {"sha256": hashlib.sha256(raw).hexdigest(), "row_counts": {table: len(rows) for table, rows in tables.items()}, "scope": "actual local persistence, not inferred execution or teaching PASS"}
    (evidence / "sqlite_evidence_hash.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
