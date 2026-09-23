"""python bench/run_arm.py --arm plain|lean|full --ticket <t> [options]

One arm, one ticket, one fresh clone of bench/fixture: runs `claude -p <ticket>`, scores the
clone with score.py and writes bench/results/<t>-<arm>-<tag>-<UTC>.json plus a .patch beside it.
The clone is kept (its path is printed) unless --cleanup.
"""
import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

from score import VENV_PY, fixture_of, score

HERE = os.path.dirname(os.path.abspath(__file__))
STYLES = {"lean": "kit-lean", "full": "orchestrator"}


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, "-c", "user.name=bench", "-c",
                           "user.email=bench@localhost", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=True).stdout


def make_clone(ticket, arm, claude_md=None):
    clone = tempfile.mkdtemp(prefix=f"bench-{ticket}-{arm}-")
    shutil.copytree(fixture_of(ticket)[0], clone, dirs_exist_ok=True)
    check = os.path.join(clone, "check.py")
    if os.path.isfile(check):  # the project's full check runs its linters from bench/.venv
        with open(check, encoding="utf-8") as f:
            text = f.read().replace("{VENV_PY}", VENV_PY.replace("\\", "/"))
        with open(check, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    if claude_md:
        # part of the base commit, so it never counts as the arm's change
        with open(claude_md, encoding="utf-8") as f:
            text = f.read().replace("{VENV_PY}", VENV_PY.replace("\\", "/"))
        with open(os.path.join(clone, "CLAUDE.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    git(clone, "init", "-q")
    git(clone, "add", "-A")
    git(clone, "commit", "-q", "-m", "base")
    # a real repo has origin/HEAD; /security-review diffs against it and fails without one
    git(clone, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(clone, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    return clone


def style_name(path):
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    if lines and lines[0].strip() == "---":
        for line in lines[1:]:
            if line.strip() == "---":
                break
            if line.startswith("name:"):
                return line.split(":", 1)[1].strip().strip("\"'")
    sys.exit(f"--style-file has no frontmatter name: {path}")


def build_command(args, prompt, clone):
    cmd = ["claude", "-p", prompt, "--model", args.model, "--permission-mode",
           "bypassPermissions", "--output-format", "json"]
    if args.arm == "plain":
        return cmd + ["--safe-mode", "--effort", args.effort or "high"]
    style = STYLES[args.arm]
    if args.style_file:
        dest = os.path.join(clone, ".claude", "output-styles")
        os.makedirs(dest, exist_ok=True)
        shutil.copy(args.style_file, dest)
        style = style_name(args.style_file)
    settings = {"outputStyle": style}
    if args.no_plugin:  # separate the kit from the user's other plugins (e.g. ponytail)
        settings["enabledPlugins"] = {p: False for p in args.no_plugin}
    cmd += ["--settings", json.dumps(settings)]
    return cmd + (["--effort", args.effort] if args.effort else [])


def main():
    parser = argparse.ArgumentParser(description="Run one benchmark arm on one ticket.")
    parser.add_argument("--arm", required=True, choices=["plain", "lean", "full"])
    parser.add_argument("--ticket", required=True)
    parser.add_argument("--model", default="claude-opus-5-5")
    parser.add_argument("--effort", help="plain defaults to high; lean/full pass it only if given")
    parser.add_argument("--style-file", help="an output style to install in the clone (lean/full)")
    parser.add_argument("--claude-md", help="replace the fixture's CLAUDE.md (a gate variant); "
                        "{VENV_PY} in it becomes bench/.venv's python")
    parser.add_argument("--no-plugin", action="append", default=[],
                        help="disable a plugin for this arm (lean/full), e.g. ponytail@ponytail")
    parser.add_argument("--tag", default="run")
    parser.add_argument("--timeout", type=int, default=2700)
    parser.add_argument("--cleanup", action="store_true", help="delete the clone afterwards")
    args = parser.parse_args()
    if args.style_file and args.arm == "plain":
        parser.error("--style-file needs --arm lean or full (plain runs with --safe-mode)")
    if args.no_plugin and args.arm == "plain":
        parser.error("--no-plugin needs --arm lean or full (plain's --safe-mode loads no plugin)")
    with open(os.path.join(HERE, "tickets", f"{args.ticket}.txt"), encoding="utf-8") as f:
        prompt = f.read().strip()
    # score() needs it; found only after the paid run, the run is spent and no record written
    if not os.path.isdir(os.path.join(HERE, "hidden", args.ticket)):
        sys.exit(f"no hidden tests for ticket {args.ticket!r}")

    clone = make_clone(args.ticket, args.arm, args.claude_md)
    cmd = build_command(args, prompt, clone)
    print(f"clone: {clone}", flush=True)
    start = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=clone, stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=args.timeout)
        stdout, stderr, timed_out, returncode = proc.stdout, proc.stderr, False, proc.returncode
    except subprocess.TimeoutExpired as exc:
        # str on Windows with text=True, bytes on POSIX
        stdout, stderr = (b.decode("utf-8", "replace") if isinstance(b, bytes) else b or ""
                          for b in (exc.stdout, exc.stderr))
        timed_out, returncode = True, None
    wall_s = round(time.monotonic() - start, 1)
    try:
        claude = json.loads(stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        claude = {}
    if not isinstance(claude, dict):
        claude = {}

    base = git(clone, "rev-list", "--max-parents=0", "HEAD").split()[-1]
    try:
        line = score(clone, args.ticket)
    except Exception as exc:  # noqa: BLE001 - the run is paid for; the record must still be written
        line = {"ticket": args.ticket, "error": f"{type(exc).__name__}: {exc}"}
    git(clone, "add", "-A")
    patch = git(clone, "diff", "--cached", base, "--", ".", ":(exclude).claude")

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    results = os.path.join(HERE, "results")
    os.makedirs(results, exist_ok=True)
    name = os.path.join(results, f"{args.ticket}-{args.arm}-{args.tag}-{stamp}")
    record = {
        "argv": cmd[:2] + ["<ticket text>"] + cmd[3:],
        "model": args.model,
        "effort": args.effort or ("high" if args.arm == "plain" else None),
        "claude_md": args.claude_md,
        "no_plugin": args.no_plugin,
        "wall_s": wall_s,
        "timed_out": timed_out,
        "returncode": returncode,
        # a crashed, errored or timed-out run keeps its score for reference only
        "valid": bool(claude) and returncode == 0 and not claude.get("is_error") and not timed_out,
        **{k: claude.get(k) for k in ("total_cost_usd", "duration_ms", "num_turns", "session_id",
                                      "is_error", "result")},
        "score": line,
        "clone": clone,
    }
    if not claude:
        record["raw_output"] = (stdout + stderr)[-4000:]
    with open(name + ".json", "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
    with open(name + ".patch", "w", encoding="utf-8", newline="\n") as f:
        f.write(patch)
    if args.cleanup:
        shutil.rmtree(clone, ignore_errors=True)
    print(json.dumps(line))
    print(f"result: {name}.json")


if __name__ == "__main__":
    main()
