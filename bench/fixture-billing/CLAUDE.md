# billing — working rules

Subscription billing service (bench fixture). Python 3.12 stdlib only.

| Purpose | Command | Measured |
|---|---|---|
| FAST GATE | `python check.py` | ~2 s |

`check.py` is the project's full check: ruff (unused and undefined names, syntax), vulture (dead
code) and the unit tests.
