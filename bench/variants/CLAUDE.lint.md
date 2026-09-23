# shop — working rules
Order service (bench fixture, lint-gate variant). Python 3 stdlib only.
| Purpose | Command | Measured |
|---|---|---|
| FAST GATE | `python -m compileall -q shop && python -m unittest -q && "{VENV_PY}" -m ruff check --isolated --select F,B,SIM,UP,C4,PERF,RET,PIE,C901 --target-version py312 shop && "{VENV_PY}" -m vulture shop --min-confidence 80` | ~2 s |

The gate's last two steps are linters: ruff (unused names, likely bugs, outdated syntax, needless
complexity) and vulture (unused imports and arguments, unreachable code). A finding in code you wrote is yours to fix; one in code
you did not touch is not.
