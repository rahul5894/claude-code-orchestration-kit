"""python bench/mutate.py <clone> --ticket <t> [--n 40] [--seed 1]

How much do the tests an arm wrote protect its code? Seeds one small bug (a mutant) at a time
into the arm's package - a flipped comparison, and/or swapped, + and - swapped, an int off by
one, a `not` dropped, a `raise` replaced by `pass` - and runs two suites against it: the hidden
tests and the arm's own tests (`python -m unittest` in the clone, as check.py does).

Only mutants the hidden tests kill count: they are real bugs. An equivalent mutant, or one the
spec does not care about, never counts against an arm. Prints one JSON line; `caught` is the
share of real bugs the arm's own tests caught.
"""
import argparse
import ast
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time

from score import fixture_of

HERE = os.path.dirname(os.path.abspath(__file__))
SWAP = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt, ast.Eq: ast.NotEq,
        ast.NotEq: ast.Eq, ast.In: ast.NotIn, ast.NotIn: ast.In, ast.Is: ast.IsNot,
        ast.IsNot: ast.Is}
ARITH = {ast.Add: ast.Sub, ast.Sub: ast.Add}


def kind(node):
    if isinstance(node, ast.Compare) and type(node.ops[0]) in SWAP:
        return "cmp"
    if isinstance(node, ast.BoolOp):
        return "bool"
    if isinstance(node, ast.BinOp) and type(node.op) in ARITH:
        return "arith"
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return "not"
    if isinstance(node, ast.Raise):
        return "raise"
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return "int"
    return None


def replace(tree, old, new):
    for parent in ast.walk(tree):
        for field, value in ast.iter_fields(parent):
            if value is old:
                setattr(parent, field, new)
                return
            if isinstance(value, list) and any(v is old for v in value):
                value[[i for i, v in enumerate(value) if v is old][0]] = new
                return
    raise AssertionError("node has no parent")


def mutant(source, index):
    """The source with the index-th mutable node (ast.walk order) changed."""
    tree = ast.parse(source)
    node = [n for n in ast.walk(tree) if kind(n)][index]
    k = kind(node)
    if k == "cmp":
        node.ops[0] = SWAP[type(node.ops[0])]()
    elif k == "bool":
        node.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
    elif k == "arith":
        node.op = ARITH[type(node.op)]()
    elif k == "int":
        node.value += 1
    elif k == "not":
        replace(tree, node, node.operand)
    else:  # raise
        replace(tree, node, ast.copy_location(ast.Pass(), node))
    return ast.unparse(ast.fix_missing_locations(tree)), k


def hidden(work, ticket, timeout=240):
    """(passed, total) of every hidden group, or None on a hang."""
    env = dict(os.environ, BENCH_REPO=work, SHOP_API_KEY="bench-key", PYTHONDONTWRITEBYTECODE="1",
               PYTHONIOENCODING="utf-8")
    d = os.path.join(HERE, "hidden", ticket)
    try:
        out = subprocess.run([sys.executable, "-B", os.path.join(HERE, "score.py"), "--child", d,
                              "test_*.py"], cwd=d, env=env, stdin=subprocess.DEVNULL,
                             capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=timeout).stdout
    except subprocess.TimeoutExpired:
        return None
    p, t = re.search(r"^PASSED (\d+)$", out, re.M), re.search(r"^TOTAL (\d+)$", out, re.M)
    return (int(p[1]), int(t[1])) if p and t else (0, -1)


def own(work, timeout=120):
    """True when the arm's own tests pass, False when they fail or hang."""
    try:
        return subprocess.run([sys.executable, "-B", "-m", "unittest"], cwd=work,
                              stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout,
                              env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1")).returncode == 0
    except subprocess.TimeoutExpired:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clone")
    ap.add_argument("--ticket", required=True)
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    pkg = fixture_of(args.ticket)[1]
    work = tempfile.mkdtemp(prefix="bench-mutate-")
    shutil.copytree(args.clone, work, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git"))
    try:
        files = sorted(os.path.relpath(os.path.join(r, f), work).replace("\\", "/")
                       for r, _, fs in os.walk(os.path.join(work, pkg)) for f in fs
                       if f.endswith(".py") and "test" not in f)
        sources = {f: open(os.path.join(work, f), encoding="utf-8").read() for f in files}
        pool = [(f, i) for f in files
                for i in range(sum(1 for n in ast.walk(ast.parse(sources[f])) if kind(n)))]
        picks = random.Random(args.seed).sample(pool, min(args.n, len(pool)))
        start = time.monotonic()
        base_hidden = hidden(work, args.ticket)
        mid = time.monotonic()
        base_own = own(work)
        # a mutant that loops or leaks a lock is a kill either way (sqlite gives up after its 30 s
        # busy timeout and the test fails); waiting it out made one clone take an hour
        h_limit, o_limit = max(20, 4 * (mid - start)), max(20, 4 * (time.monotonic() - mid))
        rec = {"clone": args.clone, "points": len(pool), "sampled": len(picks),
               "base_hidden": base_hidden, "base_own_pass": base_own,
               "limits_s": [round(h_limit), round(o_limit)]}
        if not base_own or not base_hidden or base_hidden[1] < 0:
            rec["error"] = "unmutated code fails a suite; mutants would prove nothing"
            print(json.dumps(rec))
            return
        real = caught = own_only = hangs = 0
        kinds = {}
        for f, i in picks:
            text, k = mutant(sources[f], i)
            with open(os.path.join(work, f), "w", encoding="utf-8") as fh:
                fh.write(text)
            h = hidden(work, args.ticket, h_limit)
            hangs += h is None
            killed_hidden = h is None or h[0] < base_hidden[0]
            killed_own = not own(work, o_limit)
            with open(os.path.join(work, f), "w", encoding="utf-8") as fh:
                fh.write(sources[f])
            real += killed_hidden
            caught += killed_hidden and killed_own
            own_only += killed_own and not killed_hidden
            if killed_hidden:
                got = kinds.setdefault(k, [0, 0])
                got[0] += killed_own
                got[1] += 1
        rec.update(real_bugs=real, caught=caught, own_only=own_only, hangs=hangs,
                   caught_share=round(caught / real, 3) if real else None,
                   by_kind={k: f"{a}/{b}" for k, (a, b) in sorted(kinds.items())})
        print(json.dumps(rec))
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
