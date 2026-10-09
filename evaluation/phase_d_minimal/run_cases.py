"""Sequential real local cases; each process/context gets isolated persistence."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True)
    parser.add_argument('--cases', nargs='+', default=[f'S{i}' for i in range(1, 9)])
    parser.add_argument('--arms', nargs='+', default=['ordinary', 'integrated'])
    parser.add_argument('--executable', required=True)
    args = parser.parse_args()
    if not args.run.replace('-', '').isalnum():
        parser.error('run must be a plain directory name')
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    env = dict(os.environ)
    env['PYTHONPATH'] = str(ROOT / 'data/phase-d-deps')
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    for case in args.cases:
        if case not in [f'S{i}' for i in range(1, 9)]:
            parser.error('Unknown frozen case')
        for arm in args.arms:
            if arm not in ('ordinary', 'integrated'):
                parser.error('Unknown arm')
            home = ROOT / 'data/phase-d-runtime' / args.run / f'{arm}-{case}'
            evidence = ROOT / 'data/phase-d-evidence' / args.run / f'{arm}-{case}'
            if home.exists() or evidence.exists():
                raise RuntimeError('Refuse to overwrite a previous case')
            evidence.mkdir(parents=True)
            launch = [sys.executable, str(SCRIPT/'launch.py'), '--arm', arm, '--case', case, '--home', str(home), '--evidence', str(evidence), '--catalog-home', str(ROOT/'data/phase-d-runtime/startup-integrated-S8'), '--model', 'deepseek-flash', '--port', '49302', '--allow-paid', '--request-limit', '40' if case == 'S8' else '20']
            browser = ['node', str(SCRIPT/'browser.cjs'), '--url', 'http://127.0.0.1:49310', '--case', case, '--evidence', str(evidence), '--executable', args.executable, '--allow-paid']
            (evidence/'execution.json').write_text(json.dumps({'sha': sha, 'launch': launch, 'browser': browser, 'platform': sys.platform, 'python': sys.version, 'runtime_env_names_only': ['PYTHONPATH', 'PYTHONIOENCODING', 'PYTHONDONTWRITEBYTECODE'], 'execution': 'ACTUAL_LOCAL'}, indent=2), encoding='utf-8')
            print(f'START {arm} {case} {evidence}', flush=True)
            with (evidence/'api.log').open('w', encoding='utf-8') as log:
                process = subprocess.Popen(launch, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
                try:
                    ready = False
                    for _ in range(45):
                        if process.poll() is not None:
                            break
                        try:
                            with urlopen('http://127.0.0.1:49302/health/ready', timeout=1) as response:
                                ready = response.status == 200
                        except Exception:
                            pass
                        if ready:
                            break
                        time.sleep(1)
                    if not ready:
                        raise RuntimeError('Own local API did not become ready')
                    with (evidence/'browser.log').open('w', encoding='utf-8') as browser_log:
                        result = subprocess.run(browser, cwd=ROOT, env=env, stdout=browser_log, stderr=subprocess.STDOUT, timeout=1100)
                    exported = subprocess.run([sys.executable, str(SCRIPT/'export_evidence.py'), '--home', str(home), '--evidence', str(evidence)], cwd=ROOT, env=env, capture_output=True, text=True)
                    (evidence/'export.log').write_text(exported.stdout + exported.stderr, encoding='utf-8')
                    status = {'browser_exit': result.returncode, 'export_exit': exported.returncode, 'sha': sha, 'retained': True}
                    (evidence/'result.json').write_text(json.dumps(status, indent=2), encoding='utf-8')
                    print(f'END {arm} {case} {json.dumps(status)}', flush=True)
                finally:
                    # Stop only the API child this script created.
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


if __name__ == '__main__':
    main()
