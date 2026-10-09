"""Reuse PR18's frozen protocol and provider instrumentation, outside runtime.

Requires its retained local checkout and previously installed dependencies.
No credentials are read, copied, logged, or put in this repository.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL_HEAD = "b8d2ac2aad38c587859b9bbedabe3fb72c66f4da"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--original-checkout", type=Path, required=True)
    parser.add_argument("--chromium", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--cases", nargs="+", default=[f"S{i}" for i in range(1, 9)])
    args = parser.parse_args()
    if not args.run.replace("-", "").isalnum() or any(
        c not in [f"S{i}" for i in range(1, 9)] for c in args.cases
    ):
        parser.error("Use a plain run name and frozen S1-S8 cases")
    original = args.original_checkout.resolve()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=original, text=True).strip()
    if head != ORIGINAL_HEAD:
        raise RuntimeError("Original experiment checkout differs from pinned PR18")
    script = ROOT / "data" / f"support-eval-{args.run}"
    script.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for name in (
        "provider.py",
        "source.py",
        "protocol.json",
        "launch.py",
        "browser.cjs",
        "export_evidence.py",
    ):
        raw = (original / "evaluation/phase_d_minimal" / name).read_bytes()
        hashes[name] = hashlib.sha256(raw).hexdigest()
        (script / name).write_bytes(raw)
    catalog = original / "data/phase-d-runtime/startup-integrated-S8"
    launch = script / "launch.py"
    code = launch.read_text("utf8")
    # Reuse the very same task's standard Catalog via its existing service.
    code = code.replace(
        'if not catalog_home.is_relative_to(ROOT / "data"):',
        f"if catalog_home != Path({str(catalog)!r}).resolve():",
    )
    code = code.replace(
        '"teaching_and_publication": "unchanged"',
        '"teaching_and_publication": "bounded operation support"',
    )
    launch.write_text(code, "utf8")
    env = {
        **os.environ,
        "PYTHONPATH": str(original / "data/phase-d-deps"),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    for case in args.cases:
        home = ROOT / "data/support-runtime" / args.run / case
        evidence = ROOT / "data/support-evidence" / args.run / case
        if home.exists() or evidence.exists():
            raise RuntimeError("Refuse to overwrite prior run")
        evidence.mkdir(parents=True)
        command = [
            sys.executable,
            str(launch),
            "--arm",
            "integrated",
            "--case",
            case,
            "--home",
            str(home),
            "--evidence",
            str(evidence),
            "--catalog-home",
            str(catalog),
            "--model",
            "deepseek-flash",
            "--port",
            "49302",
            "--allow-paid",
            "--request-limit",
            "20" if case == "S8" else "8",
        ]
        browser = [
            "node",
            str(script / "browser.cjs"),
            "--url",
            "http://127.0.0.1:49310",
            "--case",
            case,
            "--evidence",
            str(evidence),
            "--playwright",
            str(original / "web/node_modules/playwright"),
            "--executable",
            args.chromium,
            "--allow-paid",
        ]
        (evidence / "execution.json").write_text(
            json.dumps(
                {
                    "sha": sha,
                    "working_diff_sha256": hashlib.sha256(
                        subprocess.check_output(["git", "diff"], cwd=ROOT)
                    ).hexdigest(),
                    "original_head": head,
                    "original_script_hashes": hashes,
                    "launch": command,
                    "browser": browser,
                    "python": sys.version,
                },
                indent=2,
            ),
            "utf8",
        )
        print(f"START {case}", flush=True)
        with (evidence / "api.log").open("w", encoding="utf8") as log:
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            try:
                for _ in range(60):
                    if process.poll() is not None:
                        raise RuntimeError("API exited before readiness; retain api.log")
                    try:
                        with urlopen("http://127.0.0.1:49302/health/ready", timeout=1) as response:
                            if response.status == 200:
                                break
                    except Exception:
                        pass
                    time.sleep(1)
                else:
                    raise RuntimeError("API readiness timeout")
                with (evidence / "browser.log").open("w", encoding="utf8") as browser_log:
                    result = subprocess.run(
                        browser,
                        cwd=ROOT,
                        env=env,
                        stdout=browser_log,
                        stderr=subprocess.STDOUT,
                        timeout=1100,
                    )
                exported = subprocess.run(
                    [
                        sys.executable,
                        str(script / "export_evidence.py"),
                        "--home",
                        str(home),
                        "--evidence",
                        str(evidence),
                    ],
                    cwd=ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                )
                (evidence / "export.log").write_text(exported.stdout + exported.stderr, "utf8")
                status = {"browser_exit": result.returncode, "export_exit": exported.returncode}
                (evidence / "result.json").write_text(json.dumps(status), "utf8")
                print(f"END {case} {status}", flush=True)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    main()
