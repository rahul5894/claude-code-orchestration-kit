"""The project's full check - lint, dead code, unit tests. Run it before every commit:

    python check.py

Exits non-zero when any step fails.
"""
import subprocess
import sys

TOOLS_PY = r"{VENV_PY}"

STEPS = [
    ("lint", [TOOLS_PY, "-m", "ruff", "check", "--isolated", "--select", "F,E9",
              "--target-version", "py312", "billing", "tests"]),
    ("dead code", [TOOLS_PY, "-m", "vulture", "billing", "--min-confidence", "80"]),
    ("tests", [sys.executable, "-m", "unittest", "-q"]),
]

failed = []
for name, cmd in STEPS:
    print(f"== {name}", flush=True)
    if subprocess.run(cmd).returncode != 0:
        failed.append(name)
print("check: FAILED " + ", ".join(failed) if failed else "check: OK")
sys.exit(1 if failed else 0)
