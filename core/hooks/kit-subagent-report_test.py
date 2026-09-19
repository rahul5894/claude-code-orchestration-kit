"""Self-contained check for kit-subagent-report.py. Run from anywhere:
python kit-subagent-report_test.py
Builds its own fixture repos (one with .claude/scratch/, one without) in a temp dir."""
import datetime
import json
import os
import subprocess
import sys
import tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kit-subagent-report.py")


def repo(with_scratch=True):
    d = tempfile.mkdtemp(prefix="kit-subagent-report-")
    if with_scratch:
        os.makedirs(os.path.join(d, ".claude", "scratch"))
    return d


def run(payload):
    """Raw UTF-8 bytes on stdin, the way Node's JSON.stringify feeds the real hook.
    ensure_ascii=True would escape every non-ASCII character and hide the cp1252 defect."""
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return subprocess.run([sys.executable, HOOK], input=raw, capture_output=True)


def inbox(d):
    p = os.path.join(d, ".claude", "scratch", "_inbox")
    return (p, sorted(os.listdir(p)) if os.path.isdir(p) else [])


def tree(d):
    return [os.path.join(r, n) for r, _, names in os.walk(d) for n in names]


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

cases.append((quiet, "stdout is empty on every run"))

fails = sum(1 for ok, _ in cases if not ok)
for ok, label in cases:
    print(f"{'ok ' if ok else 'BAD'} {label}")
print(f"\n{len(cases) - fails}/{len(cases)} passed")
sys.exit(1 if fails else 0)
