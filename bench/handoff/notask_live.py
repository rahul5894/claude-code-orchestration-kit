"""Live test (bucket kit-records-integration): a chat that opens no task, then /clear, then
/continue resumes THAT chat from the kit's session log (.claude/scratch/_sessions/) in the same
window. Drives the real Claude Code binary (stream-json, chain_live.Window) with this checkout's
hooks run ATTENDED: `claude -p` hands hooks CLAUDE_CODE_SESSION_ATTENDED=0 and the kit's live hooks
skip a headless run, so each hook runs through a shim that sets 1 - what a real window adds.

S1 (no task): a question, then a code word in a SECOND message, answered "OK" only - so the word
is in no session-start line, only in S1's verbatim record. /clear. S2: /continue, then "what was
my code word?". Checked: S1's record holds the word; S2's start marks "(this window's last
session)"; S2 reads the record, asks no question, opens no task, and answers the word.

    python bench/handoff/notask_live.py [--model opus] [--keep]
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import chain_live as cl  # noqa: E402

REPO = cl.REPO
WORD = "MANGO-4217"
SHIM = ("import os, subprocess, sys\nos.environ['CLAUDE_CODE_SESSION_ATTENDED'] = '1'\n"
        "sys.exit(subprocess.run([sys.executable] + sys.argv[1:]).returncode)\n")


def setup():
    root = tempfile.mkdtemp(prefix="kit-notask-")
    with open(os.path.join(root, "CLAUDE.md"), "w", encoding="utf-8") as f:
        f.write("# test project\n| **FAST GATE — agents run this** | `python -c pass` | 0.1 s |\n")
    os.makedirs(os.path.join(root, ".claude", "rules"))
    with open(os.path.join(root, ".claude", "rules", "orchestration-kit.md"), "w", encoding="utf-8") as f:
        f.write("<!-- orchestration-kit (test fixture) -->\n")
    os.makedirs(os.path.join(root, ".claude", "commands"))
    for c in ("continue.md", "task.md"):  # project commands: --setting-sources project skips the user's
        shutil.copy(os.path.join(REPO, "core", "commands", c), os.path.join(root, ".claude", "commands", c))
    os.makedirs(os.path.join(root, ".claude", "scratch"))
    with open(os.path.join(root, ".claude", "scratch", "INDEX.md"), "w", encoding="utf-8") as f:
        f.write("# Task index\n| slug | status | updated | next action |\n|---|---|---|---|\n")
    subprocess.run(["git", "init", "-q"], cwd=root)
    side = tempfile.mkdtemp(prefix="kit-notask-set-")
    shim = os.path.join(side, "attended.py").replace("\\", "/")
    with open(shim, "w", encoding="utf-8") as f:
        f.write(SHIM)
    py, hd = sys.executable.replace("\\", "/"), os.path.join(REPO, "core", "hooks").replace("\\", "/")

    def h(name):
        return [{"type": "command", "command": f"{py} {shim} {hd}/{name}", "timeout": 10}]
    hooks = {"SessionStart": [{"matcher": "startup|resume|clear|compact|fork", "hooks": h("kit-session-start.py")}],
             "Stop": [{"hooks": h("kit-context.py")}], "SessionEnd": [{"hooks": h("kit-session-end.py")}]}
    setfile = os.path.join(side, "settings.json")
    with open(setfile, "w", encoding="utf-8") as f:
        json.dump({"hooks": hooks}, f)
    return root, setfile, side


def transcript(root, sid):
    hits = glob.glob(os.path.join(os.path.expanduser("~/.claude/projects"), "*", sid + ".jsonl"))
    return open(hits[0], encoding="utf-8", errors="replace").read() if hits else ""


def main():
    arg = sys.argv
    model = arg[arg.index("--model") + 1] if "--model" in arg else "opus"
    root, setfile, side = setup()
    print(f"project {root}  model {model}")
    w = cl.Window("A", root, model, setfile)
    checks = []
    try:
        w.say("Quick question, no task needed: what is the capital of Australia? One short sentence.")
        w.say(f"Also, for later: my code word is {WORD}. Reply with just: OK")
        w.say("/clear")
        cont = w.say("/continue")
        word = w.say("What was my code word? Answer with the word only.")
    finally:
        w.close()
    s1, s2 = (w.sids + ["", ""])[:2]
    log = os.path.join(root, ".claude", "scratch", "_sessions", "digests")
    rec = open(os.path.join(log, s1 + ".md"), encoding="utf-8").read() if os.path.isfile(os.path.join(log, s1 + ".md")) else ""
    t2 = transcript(root, s2)
    buckets = [d for d in os.listdir(os.path.join(root, ".claude", "scratch"))
               if os.path.isdir(os.path.join(root, ".claude", "scratch", d)) and not d.startswith("_")]
    checks += [(bool(s1) and bool(s2) and s1 != s2, f"two sessions in one window ({s1[:8]} -> {s2[:8]})"),
               (WORD in rec, "S1 (no task) left its verbatim record in .claude/scratch/_sessions/ with the code word"),
               ("this window's last session" in t2, "S2's session start marks S1 as (this window's last session)"),
               ("_sessions" in t2 and s1 in t2.split("this window's last session", 1)[-1],
                "S2 opened S1's record after /continue"),
               (not buckets, "no task bucket opened for a no-task chat"),
               (WORD in word, f"S2 knows the code word only S1's record holds: {word.strip()[:60]!r}")]
    print("/continue answered:", cont.strip()[:300].replace("\n", " "))
    for good, label in checks:
        print(f"  {'PASS' if good else 'FAIL'}  {label}")
    n = sum(g for g, _ in checks)
    print(f"\nno-task resume: {n}/{len(checks)}")
    if "--keep" not in arg:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(side, ignore_errors=True)
    return 0 if n == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
