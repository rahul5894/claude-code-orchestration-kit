"""python bench/score.py <repo> --ticket <t>

Runs bench/hidden/<t>/test_spec*.py and test_robust*.py against <repo> (each group in its own
child process, BENCH_REPO=<repo>) and prints ONE JSON line on stdout:
{"ticket", "spec", "robust", "security" (each "P/T"), "loc_added", "loc_removed",
"files_changed", "quality"} - quality is measured against bench/fixture with the bench/.venv tools.
LOC is <repo>'s working tree against its first commit, shop/ only, untracked files included.
Test output goes to stderr.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GROUP_TIMEOUT = 600


def child(hidden, pattern):
    sys.path.insert(0, hidden)
    suite = unittest.defaultTestLoader.discover(hidden, pattern=pattern, top_level_dir=hidden)
    print(f"TOTAL {suite.countTestCases()}", flush=True)
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(suite)
    # a failing subTest adds its own entry, so count distinct parent tests
    bad = {getattr(t, "test_case", t).id() for t, _ in result.failures + result.errors + result.skipped}
    print(f"PASSED {result.testsRun - len(bad)}", flush=True)


def run_group(repo, hidden, pattern):
    env = dict(os.environ, BENCH_REPO=repo, SHOP_API_KEY="bench-key",
               PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    try:
        proc = subprocess.run([sys.executable, os.path.abspath(__file__), "--child", hidden, pattern],
                              cwd=hidden, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=GROUP_TIMEOUT)
        out = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout or ""  # str on Windows with text=True, bytes on POSIX
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", "replace")
        out = partial + f"\nTIMED OUT after {GROUP_TIMEOUT} s"
    print(out.rstrip(), file=sys.stderr)
    total = re.search(r"^TOTAL (\d+)$", out, re.M)
    passed = re.search(r"^PASSED (\d+)$", out, re.M)
    # a hang never reaches PASSED; the verbose "... ok" lines still count what passed before it
    done = passed[1] if passed else len(re.findall(r" \.\.\. ok$", out, re.M))
    return f"{done}/{total[1] if total else '?'}"


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=True).stdout


def loc(repo):
    base = git(repo, "rev-list", "--max-parents=0", "HEAD").split()[-1]
    added = removed = files = 0
    # a file whose line endings flipped would otherwise count every line as changed
    for line in git(repo, "diff", "--numstat", "--ignore-cr-at-eol", base, "--", "shop/").splitlines():
        a, r, _ = line.split("\t", 2)
        added += int(a) if a.isdigit() else 0
        removed += int(r) if r.isdigit() else 0
        files += 1
    for path in git(repo, "ls-files", "--others", "--exclude-standard", "--", "shop/").splitlines():
        with open(os.path.join(repo, path), "rb") as f:
            added += len(f.read().splitlines())
        files += 1
    return {"loc_added": added, "loc_removed": removed, "files_changed": files}


def score(repo, ticket):
    repo = os.path.abspath(repo)
    hidden = os.path.join(HERE, "hidden", ticket)
    if not os.path.isdir(hidden):
        sys.exit(f"no hidden tests for ticket {ticket!r}: {hidden}")
    line = {"ticket": ticket, "spec": run_group(repo, hidden, "test_spec*.py")}
    for group in ("robust", "security"):
        has = any(n.startswith(f"test_{group}") and n.endswith(".py") for n in os.listdir(hidden))
        line[group] = run_group(repo, hidden, f"test_{group}*.py") if has else "0/0"
    line.update(loc(repo))
    line["quality"] = quality(repo)
    return line


VENV_PY = os.path.join(HERE, ".venv", "Scripts" if os.name == "nt" else "bin",
                       "python.exe" if os.name == "nt" else "python")
# Lint findings the arm ADDED: unused/undefined names (F), likely bugs (B), simplifiable (SIM),
# outdated syntax (UP), needless comprehensions (C4), perf anti-patterns (PERF), return style
# (RET), no-op code (PIE), functions over complexity 10 (C901).
RUFF_RULES = "F,B,SIM,UP,C4,PERF,RET,PIE,C901"


def _tool(args, cwd):
    proc = subprocess.run([VENV_PY, "-m", *args], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    return proc.stdout


def _metrics(tree):
    """Counts for the shop/ package under `tree`. Each is a count of findings or definitions."""
    import ast
    ruff = json.loads(_tool(["ruff", "check", "--isolated", "--no-cache", "--select", RUFF_RULES,
                             "--target-version", "py312", "--output-format", "json", "shop"], tree) or "[]")
    # At 60% vulture calls every public function of a library dead (it has no callers here), so
    # only what is dead for sure counts: >= 80% (unused import/argument, unreachable code) and an
    # unused PRIVATE name ('_helper'), which nothing outside the module may call.
    dead = [l for l in _tool(["vulture", "shop", "--min-confidence", "60"], tree).splitlines()
            if (m := re.search(r"\((\d+)% confidence", l)) and (int(m[1]) >= 80 or " '_" in l)]
    dup = _tool(["pylint", "--disable=all", "--enable=duplicate-code", "--min-similarity-lines=5",
                 "--score=n", "shop"], tree).count("R0801")
    cc = json.loads(_tool(["radon", "cc", "-j", "shop"], tree) or "{}")
    blocks = {}
    for f, bs in cc.items():
        if not isinstance(bs, list):
            continue
        with open(os.path.join(tree, f), encoding="utf-8", errors="replace") as fh:
            lines = [ln.rstrip() for ln in fh.read().splitlines()]
        for b in bs:
            if b.get("type") in ("function", "method"):
                # the body too: a rewrite that keeps its complexity is still changed code
                body = "\n".join(lines[b["lineno"] - 1:b["endline"]])
                blocks[(f, b.get("classname"), b["name"])] = (b["complexity"], body)
    defs = classes = unparsable = 0
    for root, _, names in os.walk(os.path.join(tree, "shop")):
        for n in names:
            if n.endswith(".py"):
                try:
                    with open(os.path.join(root, n), encoding="utf-8") as f:
                        nodes = list(ast.walk(ast.parse(f.read())))
                except (SyntaxError, ValueError):  # UnicodeDecodeError is a ValueError
                    unparsable += 1  # an arm can leave a broken file; the score must still land
                    continue
                defs += sum(isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef)) for x in nodes)
                classes += sum(isinstance(x, ast.ClassDef) for x in nodes)
    return {"lint": len(ruff), "lint_codes": sorted({r["code"] for r in ruff if r.get("code")}),
            "dead_code": len(dead), "duplicate_blocks": dup, "functions": defs, "classes": classes,
            "unparsable_files": unparsable, "blocks": blocks}


def quality(repo):
    """What the arm added, measured against the untouched fixture: lint findings, vulture dead
    code, pylint duplicate blocks, new functions/classes, and radon complexity of new code."""
    if not os.path.isfile(VENV_PY):
        return "SKIPPED (no bench/.venv: python -m venv bench/.venv, then pip install ruff vulture radon pylint)"
    base, final = _metrics(os.path.join(HERE, "fixture")), _metrics(repo)
    new_cc = [c for k, (c, body) in final["blocks"].items() if base["blocks"].get(k) != (c, body)]
    return {
        "unparsable_files": final["unparsable_files"],
        "lint_added": final["lint"] - base["lint"],
        "lint_codes": [c for c in final["lint_codes"] if c not in base["lint_codes"]],
        "dead_code_added": final["dead_code"] - base["dead_code"],
        "duplicate_blocks_added": final["duplicate_blocks"] - base["duplicate_blocks"],
        "functions_added": final["functions"] - base["functions"],
        "classes_added": final["classes"] - base["classes"],
        "new_or_changed_functions": len(new_cc),
        "cc_max_new": max(new_cc, default=0),
        "cc_mean_new": round(sum(new_cc) / len(new_cc), 1) if new_cc else 0,
        "cc_over_10_new": sum(c > 10 for c in new_cc),
    }


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "--child":
        return child(sys.argv[2], sys.argv[3])
    parser = argparse.ArgumentParser(description="Score one repo against one ticket's hidden tests.")
    parser.add_argument("repo")
    parser.add_argument("--ticket", required=True)
    args = parser.parse_args()
    if not os.path.isdir(args.repo):
        sys.exit(f"not a directory: {args.repo}")
    print(json.dumps(score(args.repo, args.ticket)))


if __name__ == "__main__":
    main()
