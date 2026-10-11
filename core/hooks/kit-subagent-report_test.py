"""Self-contained check for kit-subagent-report.py. Run from anywhere:
python kit-subagent-report_test.py
Builds its own fixture repos (one with .claude/scratch/, one without) in a temp dir."""
import atexit
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kit-subagent-report.py")
tmp = tempfile.mkdtemp(prefix="kit-subagent-report-test-")
atexit.register(shutil.rmtree, tmp, True)


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit_off import HEADER, RULES  # noqa: E402


def repo(with_scratch=True):
    """A project with the kit on - the kit is off by default, and /kit-on writes its rules copy
    (kit_off.py) - with or without a scratch dir."""
    d = tempfile.mkdtemp(dir=tmp)
    if with_scratch:
        os.makedirs(os.path.join(d, ".claude", "scratch"))
    os.makedirs(os.path.join(d, ".claude", "rules"), exist_ok=True)
    with open(os.path.join(d, RULES), "wb") as f:
        f.write(HEADER + b" (test) -->\n")
    return d


def run(payload, project_dir=None):
    """Raw UTF-8 bytes on stdin, the way Node's JSON.stringify feeds the real hook.
    ensure_ascii=True would escape every non-ASCII character and hide the cp1252 defect.
    The hook prefers CLAUDE_PROJECT_DIR, and a caller inside Claude Code has it set: without
    stripping it every case below would file into the caller's own repo."""
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    if project_dir:
        env["CLAUDE_PROJECT_DIR"] = project_dir
    # No CLAUDE_PROJECT_DIR: the hook runs where the session is, as Claude Code starts it.
    return subprocess.run([sys.executable, HOOK], input=raw, capture_output=True, env=env,
                          cwd=project_dir or payload.get("cwd") or None)


def inbox(d):
    p = os.path.join(d, ".claude", "scratch", "_inbox")
    return (p, sorted(os.listdir(p)) if os.path.isdir(p) else [])


def tree(d):
    """Every file the hook could have written: the kit's rules copy is the fixture's own."""
    return [os.path.join(r, n) for r, _, names in os.walk(d) for n in names
            if os.path.join(r, n) != os.path.join(d, RULES)]


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


cases = []  # (ok, label)
quiet = True  # last case: stdout must be empty on every single run below

# 1. a bucket repo gets exactly one file, named for the agent, holding the message verbatim
d = repo()
p = run({"cwd": d, "agent_type": "kit-builder", "agent_id": "abcdef1234567890",
         "last_assistant_message": "## CHANGED\n- core/x.py:12 - did the thing"})
quiet &= p.stdout == b""
box, names = inbox(d)
body = read(os.path.join(box, names[0])) if len(names) == 1 else ""
cases.append((len(names) == 1 and "kit-builder" in names[0] and "abcdef12" in names[0]
              and "- core/x.py:12 - did the thing" in body and p.returncode == 0,
              "bucket repo -> one _inbox file named for the agent, body verbatim"))

# 2. a project that does not use buckets is left completely alone
d = repo(with_scratch=False)
p = run({"cwd": d, "agent_type": "kit-builder", "agent_id": "abcdef1234567890",
         "last_assistant_message": "report"})
quiet &= p.stdout == b""
cases.append((tree(d) == [] and p.returncode == 0,
              "no .claude/scratch/ -> nothing written, exit 0"))

# 3. an empty final message is loud, never a blank file
d = repo()
p = run({"cwd": d, "agent_type": "kit-verifier", "agent_id": "0123456789",
         "last_assistant_message": "", "agent_transcript_path": "/tmp/tr-9.jsonl"})
quiet &= p.stdout == b""
box, names = inbox(d)
body = read(os.path.join(box, names[0])) if len(names) == 1 else ""
cases.append(("MISSING REPORT" in body and "/tmp/tr-9.jsonl" in body,
              "empty last_assistant_message -> MISSING REPORT plus transcript path"))

# 4. a hostile agent_type cannot escape _inbox/
d = repo()
p = run({"cwd": d, "agent_type": "../../../evil/x", "agent_id": "../../nope",
         "last_assistant_message": "report"})
quiet &= p.stdout == b""
box, names = inbox(d)
cases.append((len(names) == 1 and tree(d) == [os.path.join(box, names[0])],
              "path separators in agent_type stay inside _inbox/"))

# 5. non-ASCII survives the trip. JSON.stringify does not escape it and the Windows locale
# codec is cp1252, so an arrow arrives as mojibake unless stdin is decoded as UTF-8.
d = repo()
msg = "## CHANGED\n- core/x.py:12 — naïve → explicit"
p = run({"cwd": d, "agent_type": "kit-builder", "agent_id": "abcdef1234567890",
         "last_assistant_message": msg})
quiet &= p.stdout == b""
box, names = inbox(d)
body = read(os.path.join(box, names[0])) if len(names) == 1 else ""
cases.append((msg in body, "a raw UTF-8 payload is written verbatim, not mojibake"))

# 6. two agents of one type finishing in the same second must not overwrite each other.
# Firing the hook twice and hoping both land in one second passes vacuously on a slow
# machine - the second stamp would differ and the OLD code would write two files too. So
# plant the exact file the hook is about to write and check it survives. The retry covers
# the one real race left: the UTC second rolling over between our stamp and the hook's.
d, planted, names = None, "", []
for _ in range(3):
    d = repo()
    box = os.path.join(d, ".claude", "scratch", "_inbox")
    os.makedirs(box, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    planted = os.path.join(box, f"{stamp}-kit-verifier-unknown.md")
    with open(planted, "w", encoding="utf-8") as f:
        f.write("first report")
    p = run({"cwd": d, "agent_type": "kit-verifier", "last_assistant_message": "second report"})
    quiet &= p.stdout == b""
    _, names = inbox(d)
    if len(names) == 2:  # the hook's stamp matched ours, so the collision really happened
        break
cases.append((len(names) == 2 and read(planted) == "first report"
              and any("second report" in read(os.path.join(box, n)) for n in names),
              "a report already on that name survives -> second file, neither lost"))

# 7. a payload shape change (content blocks instead of a string) must be loud, not a repr
d = repo()
p = run({"cwd": d, "agent_type": "kit-verifier", "agent_id": "0123456789",
         "last_assistant_message": [{"type": "text", "text": "report"}],
         "agent_transcript_path": "/tmp/tr-7.jsonl"})
quiet &= p.stdout == b""
box, names = inbox(d)
body = read(os.path.join(box, names[0])) if len(names) == 1 else ""
cases.append(("MISSING REPORT" in body and "'type': 'text'" in body,
              "a non-string last_assistant_message -> MISSING REPORT plus what did arrive"))

# 8 and 9. a git repo that would SHOW the file gets nothing; one that ignores it gets the
# file. Cases 1-7 run in plain temp dirs, which covers the "not a repo, nothing to dirty"
# path. Measured 2026-09-19: two projects on this machine do not ignore .claude/scratch/.
for ignored, want_files, label in ((False, 0, "a repo that does NOT ignore .claude/scratch/ -> nothing written"),
                                   (True, 1, "a repo that ignores .claude/scratch/ -> the file is written")):
    d = repo()
    git = subprocess.run(["git", "init", "-q", d], capture_output=True)
    if ignored:
        with open(os.path.join(d, ".gitignore"), "w", encoding="utf-8") as f:
            f.write(".claude/scratch/\n")
    p = run({"cwd": d, "agent_type": "kit-refuter", "agent_id": "deadbeefcafe",
             "last_assistant_message": "a candidate"})
    quiet &= p.stdout == b""
    _, names = inbox(d)
    cases.append((git.returncode == 0 and len(names) == want_files, label))

# 10. payload cwd follows the shell's `cd` (2026-09-23: two reports lost after
# `cd .claude/scratch`); CLAUDE_PROJECT_DIR is the launch root and wins.
d, elsewhere = repo(), repo(with_scratch=False)
p = run({"cwd": elsewhere, "agent_type": "kit-builder", "agent_id": "abcdef1234567890",
         "last_assistant_message": "report"}, project_dir=d.replace(os.sep, "/"))
quiet &= p.stdout == b""
_, names = inbox(d)
cases.append((len(names) == 1 and tree(elsewhere) == [],
              "CLAUDE_PROJECT_DIR = fixture, payload cwd elsewhere -> filed in the fixture"))

# 11. launched in a parent dir, then cd into the repo: the launch root has no scratch, cwd does.
d, parent = repo(), repo(with_scratch=False)
p = run({"cwd": d, "agent_type": "kit-builder", "agent_id": "abcdef1234567890",
         "last_assistant_message": "report"}, project_dir=parent.replace(os.sep, "/"))
quiet &= p.stdout == b""
_, names = inbox(d)
cases.append((len(names) == 1 and tree(parent) == [],
              "CLAUDE_PROJECT_DIR without scratch, payload cwd with it -> filed under cwd"))


# 12-15. A prompt that names a brief of this project: the message becomes that bucket's
# reports/<NN>-<agent>.md (bucket kit-optimize-pass D001: 44 of 156 briefs had no report).
def agent_transcript(d, prompt):
    p = os.path.join(d, "agent-" + str(len(os.listdir(d))) + ".jsonl")
    with open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "system", "subtype": "init"}) + "\n")
        f.write(json.dumps({"type": "user", "message": {"role": "user", "content": prompt}}) + "\n")
    return p


def bucket(d, slug, brief):
    os.makedirs(os.path.join(d, ".claude", "scratch", slug, "briefs"), exist_ok=True)
    with open(os.path.join(d, ".claude", "scratch", slug, "briefs", brief), "w", encoding="utf-8") as f:
        f.write("# brief\n")
    return os.path.join(d, ".claude", "scratch", slug, "reports")


d = repo()
reports = bucket(d, "fix-login", "02-refute-the-diff.md")
brief_abs = os.path.join(d, ".claude", "scratch", "fix-login", "briefs", "02-refute-the-diff.md")
p = run({"cwd": d, "agent_type": "refuter", "agent_id": "a1b2c3d4e5",
         "agent_transcript_path": agent_transcript(d, f"Your brief is {brief_abs} - read it whole first."),
         "last_assistant_message": "## Candidates\n- none"})
quiet &= p.stdout == b""
got = os.listdir(reports) if os.path.isdir(reports) else []
cases.append((got == ["02-refuter.md"] and "## Candidates\n- none" in read(os.path.join(reports, got[0]))
              and inbox(d)[1] == [],
              "prompt names a brief (absolute path) -> the bucket's reports/02-refuter.md, no _inbox copy"))

p = run({"cwd": d, "agent_type": "verifier", "agent_id": "f6e5d4c3b2",
         "agent_transcript_path": agent_transcript(d, "Brief: .claude/scratch/fix-login/briefs/02-refute-the-diff.md"),
         "last_assistant_message": "second word on 02"})
quiet &= p.stdout == b""
cases.append(((sorted(os.listdir(reports)) if os.path.isdir(reports) else []) == ["02-refuter.md"]
              and len(inbox(d)[1]) == 1,
              "a report for 02 already there -> never overwritten; the message goes to _inbox"))

d = repo()
p = run({"cwd": d, "agent_type": "builder", "agent_id": "0a0b0c0d",
         "agent_transcript_path": agent_transcript(d, "Brief: .claude/scratch/nope/briefs/01-x.md"),
         "last_assistant_message": "built"})
quiet &= p.stdout == b""
cases.append((len(inbox(d)[1]) == 1 and not os.path.isdir(os.path.join(d, ".claude", "scratch", "nope")),
              "a brief that is not in this project -> _inbox, no bucket created"))

d = repo()
box = os.path.join(d, ".claude", "scratch", "_inbox")
os.makedirs(box)
for name, days in (("old.md", 40), ("new.md", 2)):
    with open(os.path.join(box, name), "w", encoding="utf-8") as f:
        f.write("x")
    t = datetime.datetime.now().timestamp() - days * 86400
    os.utime(os.path.join(box, name), (t, t))
p = run({"cwd": d, "agent_type": "researcher", "agent_id": "77", "last_assistant_message": "found"})
quiet &= p.stdout == b""
left = inbox(d)[1]
cases.append(("old.md" not in left and "new.md" in left and len(left) == 2,
              "an _inbox write prunes copies older than 30 days, keeps the rest"))

cases.append((quiet, "stdout is empty on every run"))

fails = sum(1 for ok, _ in cases if not ok)
for ok, label in cases:
    print(f"{'ok ' if ok else 'BAD'} {label}")
print(f"\n{len(cases) - fails}/{len(cases)} passed")
sys.exit(1 if fails else 0)
