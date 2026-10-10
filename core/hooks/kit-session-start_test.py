"""Self-contained check for kit-session-start.py. Run from anywhere.
Builds its own fixtures in a temp dir: a project with a FAST GATE row, one without, one with
no CLAUDE.md at all. Feeds the hook both ways it is invoked - stdin JSON as Claude Code does,
and `--check <dir>` as verify_live.py does."""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kit-session-start.py")

tmp = tempfile.mkdtemp(prefix="kit-start-")
atexit.register(shutil.rmtree, tmp, True)
WITH = os.path.join(tmp, "with")
WITHOUT = os.path.join(tmp, "without")
NONE = os.path.join(tmp, "none")
for d in (WITH, WITHOUT, NONE):
    os.makedirs(d)
with open(os.path.join(WITH, "CLAUDE.md"), "w", encoding="utf-8") as f:
    f.write("# x\n| **FAST GATE — agents run this** | `make lint` | 4 s |\n")
with open(os.path.join(WITHOUT, "CLAUDE.md"), "w", encoding="utf-8") as f:
    f.write("# x\n## Commands\nnothing named here\n")
# A gated project under a non-ASCII path. Before 2026-09-19 the hook read stdin with the
# locale codec, so this cwd decoded into a path that does not exist and the notice fired on
# a project that is in fact set up.
ACCENT = os.path.join(tmp, "Grüße")
os.makedirs(ACCENT)
with open(os.path.join(ACCENT, "CLAUDE.md"), "w", encoding="utf-8") as f:
    f.write("# x\n| **FAST GATE — agents run this** | `make lint` | 4 s |\n")

CASES = [
    # (want, how, root)
    ("QUIET",  "stdin", ACCENT),
    ("QUIET",  "stdin", WITH),
    ("NOTICE", "stdin", WITHOUT),
    ("NOTICE", "stdin", NONE),
    ("QUIET",  "check", WITH),
    ("NOTICE", "check", WITHOUT),
    ("NOTICE", "check", NONE),
    # Malformed stdin must not crash and must not spam: fail open means silence.
    ("QUIET",  "garbage", WITH),
]

# Task buckets: INDEX.md rows OPEN/BLOCKED are listed for the model and named to the user.
def bucket_project(name, gated, rows):
    root = os.path.join(tmp, name)
    os.makedirs(os.path.join(root, ".claude", "scratch"))
    if gated:
        with open(os.path.join(root, "CLAUDE.md"), "w", encoding="utf-8") as f:
            f.write("# x\n| **FAST GATE — agents run this** | `make lint` | 4 s |\n")
    with open(os.path.join(root, ".claude", "scratch", "INDEX.md"), "w", encoding="utf-8") as f:
        f.write("# Task index\n| slug | status | updated | next action |\n|---|---|---|---|\n")
        for slug, status, nxt in rows:
            f.write(f"| {slug} | {status} | 2026-09-23 | {nxt} |\n")
    return root


BUCKETS = bucket_project("buckets", True, [("live-one", "OPEN", "run builder-02"),
                                           ("old-one", "DONE", "nothing")])
MANY = bucket_project("many", True, [(f"b{i}", "OPEN", f"step {i}") for i in range(10)])
MIX = bucket_project("mix", True, [("blocked-one", "BLOCKED", "wait for the user"),
                                   ("long-one", "OPEN", "y" * 300),
                                   ("pipe-one", "OPEN", r"a \| b"),
                                   ("../x", "OPEN", "escaped the scratch dir")])


PRIVATE_TMP = os.path.join(tmp, "_tmp")  # window records land here, never in the real temp dir
os.makedirs(PRIVATE_TMP)


def run(how, root, project_dir=None, source="startup", pid=None, sid=None, transcript=None, extra=None):
    """Parsed stdout: {} when silent, {"_bad": text} when it is not JSON. `pid` plays the
    window (env CLAUDE_PID); without it the run has none, whatever window runs the test."""
    # The hook prefers CLAUDE_PROJECT_DIR; a caller inside Claude Code has it set, so every run
    # starts from an env without it and only the case that tests it puts it back.
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "CLAUDE_PID")}
    env.update(TEMP=PRIVATE_TMP, TMP=PRIVATE_TMP, TMPDIR=PRIVATE_TMP, **(extra or {}))
    if project_dir:
        env["CLAUDE_PROJECT_DIR"] = project_dir
    if pid:
        env["CLAUDE_PID"] = str(pid)
    if how == "stdin":
        # Raw UTF-8 bytes, the way JSON.stringify feeds the real hook. text=True would
        # encode with the locale codec and the non-ASCII case could never run.
        payload = {"cwd": root, "source": source}
        if sid:
            payload.update(session_id=sid, transcript_path=transcript or "")
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        p = subprocess.run([sys.executable, HOOK], input=raw, capture_output=True, cwd=root, env=env)
    elif how == "check":
        p = subprocess.run([sys.executable, HOOK, "--check", root], capture_output=True, env=env)
    elif how == "cards":
        p = subprocess.run([sys.executable, HOOK, "--cards", root], capture_output=True, env=env)
        return {"_text": p.stdout.decode("utf-8", "replace")}
    else:
        p = subprocess.run([sys.executable, HOOK], input=b"{not json",
                           capture_output=True, cwd=root, env=env)
    out = p.stdout.decode("utf-8", "replace").strip()
    if not out:
        return {}
    try:
        return json.loads(out)
    except ValueError:
        return {"_bad": out}


def context(out):
    spec = out.get("hookSpecificOutput") or {}
    return spec.get("additionalContext", "") if spec.get("hookEventName") == "SessionStart" else ""


def kind(out):
    if "_bad" in out:
        return "BADJSON"
    return "NOTICE" if "FAST GATE" in context(out) else "QUIET"


fails = 0
for want, how, root in CASES:
    got = kind(run(how, root))
    if got != want:
        fails += 1
    print(f"{'ok ' if got == want else 'BAD'} want={want:6} got={got:6} {how:8} {os.path.basename(root)}")

extra = []
o = run("stdin", BUCKETS)
extra.append(("live-one" in context(o) and "run builder-02" in context(o)
              and "old-one" not in context(o) and "FAST GATE" not in context(o)
              and "live-one" in o.get("systemMessage", "") and "continue" in o.get("systemMessage", "")
              and "old-one" not in o.get("systemMessage", ""),
              "INDEX with OPEN + DONE rows -> only the OPEN slug listed, systemMessage names it"))
o = run("stdin", WITHOUT)
extra.append((kind(o) == "NOTICE" and "systemMessage" not in o,
              "no INDEX -> the gate notice alone, no systemMessage"))
# Payload cwd follows the shell's `cd`; CLAUDE_PROJECT_DIR is the launch root (forward
# slashes, as Claude Code sets it) and wins.
o = run("stdin", WITHOUT, project_dir=BUCKETS.replace(os.sep, "/"))
extra.append((kind(o) == "QUIET" and "live-one" in context(o),
              "CLAUDE_PROJECT_DIR = A, payload cwd = B -> A is read"))
o = run("stdin", MIX)
extra.append(("blocked-one" in context(o) and "[BLOCKED]" in context(o),
              "BLOCKED row -> listed with its status"))
extra.append(("y" * 200 in context(o) and "y" * 201 not in context(o),
              "300-char next action -> cut to 200"))
extra.append((r"pipe-one [OPEN]: a \| b" in context(o), r"next action holding an escaped \| -> kept whole"))
extra.append(("../x" not in context(o) and "escaped the scratch dir" not in context(o),
              "slug ../x -> dropped"))
o = run("stdin", MANY)
extra.append(("b0 [OPEN]" not in context(o) and "b1 [OPEN]" not in context(o)
              and all(f"b{i} [OPEN]" in context(o) for i in range(2, 10))
              and "(+2 older: b1, b0 - /continue <name> reaches them)" in context(o)
              and o.get("systemMessage", "").startswith("Open task(s): b9, b8, b7, b6, b5, b4, b3, b2 (+2 older) - "),
              "10 OPEN rows, no STATE.md -> 8 listed (INDEX's later rows first), the other 2 named in one line"))
o = run("stdin", BUCKETS, source="compact")
extra.append(("live-one" in context(o) and "systemMessage" not in o,
              "source compact -> additionalContext, no systemMessage"))
# After a compaction the newest open STATE.md rides along; startup never carries it.
for slug, body in (("live-one", "Next: LIVE-CODEWORD\n"), ("old-one", "DONE-CODEWORD\n")):
    os.makedirs(os.path.join(BUCKETS, ".claude", "scratch", slug), exist_ok=True)
    with open(os.path.join(BUCKETS, ".claude", "scratch", slug, "STATE.md"), "w", encoding="utf-8") as f:
        f.write(body)
o = run("stdin", BUCKETS, source="compact")
extra.append(("LIVE-CODEWORD" in context(o) and "DONE-CODEWORD" not in context(o),
              "source compact -> the open bucket's STATE.md is in the context, a DONE one's is not"))
o = run("stdin", BUCKETS)
extra.append(("LIVE-CODEWORD" not in context(o), "source startup -> no STATE.md content"))
for i, slug in enumerate(("b3", "b7")):
    os.makedirs(os.path.join(MANY, ".claude", "scratch", slug))
    p = os.path.join(MANY, ".claude", "scratch", slug, "STATE.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write(f"STATE-OF-{slug}\n" + ("z" * 9000 if slug == "b7" else ""))
    os.utime(p, (1_700_000_000 + i, 1_700_000_000 + i))
o = run("stdin", MANY, source="compact")
extra.append(("STATE-OF-b7" in context(o) and "STATE-OF-b3" not in context(o)
              and "z" * 5900 in context(o) and "z" * 6001 not in context(o) and "cut at 6000" in context(o),
              "two open STATE.md -> only the newest, cut at 6000 bytes with a marker"))
# The newest "STATE.md" is a directory: the next newest readable one is used instead.
os.makedirs(os.path.join(MANY, ".claude", "scratch", "b9", "STATE.md"))
o = run("stdin", MANY, source="compact")
extra.append(("STATE-OF-b7" in context(o) and "hookSpecificOutput" in o,
              "newest STATE.md is a directory -> falls back to the older readable one"))
# A cut in the middle of a UTF-8 character must not break the JSON or silence the hook.
CUT = bucket_project("cut", True, [("u8", "OPEN", "x")])
os.makedirs(os.path.join(CUT, ".claude", "scratch", "u8"))
with open(os.path.join(CUT, ".claude", "scratch", "u8", "STATE.md"), "wb") as f:
    f.write(b"a" * 5999 + "é".encode("utf-8") + b"tail\xff\xfe")
o = run("stdin", CUT, source="compact")
extra.append(("_bad" not in o and "a" * 5999 in context(o) and "u8 [OPEN]" in context(o),
              "multi-byte char cut at the cap, invalid bytes -> valid JSON, text kept"))
# kit-off in the project silences the new path too.
open(os.path.join(CUT, ".claude", "kit-off"), "w").close()
o = run("stdin", CUT, source="compact")
extra.append(("a" * 100 not in context(o), "kit-off + compact -> no STATE.md content"))
# A cloned repo's STATE.md as a symlink to a file outside the scratch dir is never read.
LINK = bucket_project("link", True, [("ln", "OPEN", "x")])
os.makedirs(os.path.join(LINK, ".claude", "scratch", "ln"))
secret = os.path.join(tmp, "secret.txt")
with open(secret, "w", encoding="utf-8") as f:
    f.write("SECRET-OUTSIDE-SCRATCH\n")
try:
    os.symlink(secret, os.path.join(LINK, ".claude", "scratch", "ln", "STATE.md"))
except OSError:
    print("SKIP symlinked STATE.md (this machine cannot create symlinks); total drops by one")
else:
    o = run("stdin", LINK, source="compact")
    extra.append(("SECRET-OUTSIDE-SCRATCH" not in context(o) and "ln [OPEN]" in context(o),
                  "STATE.md symlinked outside the scratch dir -> not read, bucket still listed"))
# Launched in a parent dir, then cd into the repo: the launch root has no scratch, cwd does.
o = run("stdin", BUCKETS, project_dir=WITHOUT.replace(os.sep, "/"))
extra.append(("live-one" in context(o),
              "CLAUDE_PROJECT_DIR without .claude/scratch, payload cwd with it -> cwd's buckets"))
# INDEX shapes models write besides the /task table (2026-09-29: Strem-setup's bullet INDEX left
# all 3 open buckets unseen, and `IN PROGRESS` was skipped as not OPEN/BLOCKED).
BUL = os.path.join(tmp, "bullets")
for slug in ("fail-over", "stall", "gone"):
    os.makedirs(os.path.join(BUL, ".claude", "scratch", slug))
with open(os.path.join(BUL, "CLAUDE.md"), "w", encoding="utf-8") as f:
    f.write("# x\n| **FAST GATE — agents run this** | `make lint` | 4 s |\n")
with open(os.path.join(BUL, ".claude", "scratch", "INDEX.md"), "w", encoding="utf-8") as f:
    f.write("# Buckets\n- fail-over — OPEN — copy failover next\n- stall — BLOCKED — waits on the user\n"
            "- gone — DONE — in _closed/\n- see the notes — for background\n")
o = run("stdin", BUL)
extra.append(("fail-over [OPEN]: copy failover next" in context(o) and "stall [BLOCKED]" in context(o)
              and "gone" not in context(o) and "see" not in o.get("systemMessage", ""),
              "bullet INDEX -> OPEN and BLOCKED listed, DONE and a prose bullet are not"))
PROG = bucket_project("progress", True, [("doing", "IN PROGRESS", "next step"), ("fin", "COMPLETED", "x"),
                                         ("OPEN", "active", "legend row")])
os.makedirs(os.path.join(PROG, ".claude", "scratch", "doing"))
o = run("stdin", PROG)
extra.append(("doing [IN PROGRESS]" in context(o) and "fin" not in context(o)
              and "legend row" not in context(o),
              "IN PROGRESS with its folder -> open; COMPLETED and a legend row | OPEN | active | -> not"))
# /continue resumes the newest handoff without asking; a STATE.md that says CLOSED is skipped.
NEW = bucket_project("newest", True, [("older", "OPEN", "a"), ("newer", "OPEN", "b"), ("shut", "OPEN", "c")])
for i, (slug, body) in enumerate((("older", "Status: OPEN\n"), ("newer", "Status: OPEN\n"),
                                  ("shut", "Updated: x   Status: CLOSED 2026-09-29\n"))):
    os.makedirs(os.path.join(NEW, ".claude", "scratch", slug))
    p = os.path.join(NEW, ".claude", "scratch", slug, "STATE.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write(body)
    os.utime(p, (1_700_000_000 + i, 1_700_000_000 + i))
o = run("stdin", NEW)
extra.append(("newer [OPEN]: b (newest handoff) · last " in context(o) and "older [OPEN]: a · last " in context(o)
              and "shut [OPEN]: c · last " in context(o) and "RECOMMEND one" in context(o)
              and o.get("systemMessage", "").endswith("it asks which (newest: newer)."),
              "3 open, newest STATE.md says CLOSED -> 2 free handoffs: newest marked, /continue recommends + asks"))
with open(os.path.join(NEW, ".claude", "scratch", "older", "STATE.md"), "w", encoding="utf-8") as f:
    f.write("# STATE\nUpdated: x   Status: OPEN   Priority: P1\n")
o = run("stdin", NEW)
extra.append(("older [OPEN]: a (newest handoff) · last " in context(o)
              and context(o).split("older [OPEN]: a")[1].split("\n")[0].endswith(" · P1"),
              "a STATE.md header's Priority: P1 shows on its row, for the recommendation"))
os.remove(os.path.join(NEW, ".claude", "scratch", "older", "STATE.md"))
o = run("stdin", NEW)
extra.append((o.get("systemMessage", "").endswith("resume newer."),
              "one free handoff left -> /continue resumes it unasked"))

# Task cards (bucket continue-router): each open task's own short description from its STATE.md,
# with fallbacks for the shapes real STATE.md files have; the tasks closed in the last 14 days.
def state(root, slug, body, age_days=0, base=None):
    d = os.path.join(root, ".claude", "scratch", *([base] if base else []), slug)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "STATE.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write(body)
    t = time.time() - age_days * 86400
    os.utime(p, (t, t))


def ago(days):
    return time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400))


def lines_after(text, start):
    """The lines that follow the first line starting with `start`."""
    ls = text.split("\n")
    i = next((j for j, s in enumerate(ls) if s.startswith(start)), None)
    return ls[i + 1:] if i is not None else None


CARD = bucket_project("cards", True, [("about-one", "OPEN", "commit is left"),
                                      ("obj-one", "BLOCKED", "wait for the delays"),
                                      ("title-one", "OPEN", "see STATE.md"),
                                      ("bare-one", "OPEN", "x")])
state(CARD, "about-one", "# STATE — about-one\n<!-- c -->\nAbout: **Dark mode** for the login page\n"
                         "Updated: x   Status: OPEN — code done, commit left   Priority: P2\n## Objective\nnot this\n"
                         "## Next action\nOnly the commit is left: run the gate, then commit\n")
state(CARD, "obj-one", "# STATE — obj-one\n**Status:** BLOCKED on the user\n## Objective\n<!-- c -->\n\n"
                       "- Retry failed payments 3 times\n## Next action\nwait for the delays\n")
state(CARD, "title-one", "# STATE — title-one (NPN-88 Pima County AZ)\nUpdated: x   Status: OPEN\n## Done\n- a\n")
state(CARD, "bare-one", "# F-603 — STATE\n- **Item:** x\n")
os.makedirs(os.path.join(CARD, ".claude", "scratch", "about-one", "digests"))
for name in ("s1.json", "s2.json", "s1.md"):
    open(os.path.join(CARD, ".claude", "scratch", "about-one", "digests", name), "w").close()
state(CARD, "closed-new", f"# STATE\nAbout: Avatar upload with a square crop\nStatus: CLOSED {ago(2)}\n", 2)
state(CARD, "closed-old", f"# STATE\nAbout: old work\nStatus: CLOSED {ago(20)}\n", 20)
state(CARD, "closed-moved", f"# STATE — closed-moved\n## Objective\nCSV export\nStatus: CLOSED {ago(1)}\n", 1, "_closed")
state(CARD, "closed-nodate", "# STATE\nStatus: CLOSED\n", 1)
state(CARD, "open-unlisted", "# STATE\nStatus: OPEN\n")
c = context(run("stdin", CARD))
extra.append(("  about: Dark mode for the login page" in c and "  state: OPEN — code done, commit left" in c
              and "  next step: Only the commit is left: run the gate, then commit" in c
              and " · 2 sessions" in c.split("- about-one [OPEN]")[1].split("\n")[0],
              "card: About line (bold dropped), a Status that says more, the STATE next step, 2 sessions"))
extra.append(("  about: Retry failed payments 3 times" in c and "  state: BLOCKED on the user" in c
              and "next step: wait for the delays" not in c and "  about: NPN-88 Pima County AZ" in c,
              "card fallbacks: Objective's first line, the title's words; a next step the row has is not repeated"))
extra.append(((lines_after(c, "- bare-one [OPEN]: x") or ["  "])[0][:2] != "  " and "  state: OPEN\n" not in c,
              "a STATE.md that gives no about, state or step adds no line - nothing guessed"))
extra.append(("- closed-new (closed " + ago(2) + "): Avatar upload with a square crop" in c
              and "- closed-moved (closed " + ago(1) + "): CSV export" in c and "- closed-nodate (closed " in c
              and "closed-old" not in c and "open-unlisted" not in c and "Closed in the last 14 days" in c,
              "closed in the last 14 days are listed (also in _closed/, no date = mtime); older and open ones are not"))
c = context(run("stdin", CARD, source="compact"))
extra.append(("about-one [OPEN]" in c and "  about:" not in c and "closed-new" not in c,
              "after a compaction: the short rows, no card lines, no closed list"))
t = run("cards", CARD)["_text"]
extra.append(("  about: Dark mode for the login page" in t and "- closed-new (closed " in t
              and "Choose from the cards" not in t and not t.lstrip().startswith("{"),
              "--cards prints the cards as plain text, without the routing note"))
with open(os.path.join(PRIVATE_TMP, "kit-window-424242.json"), "w", encoding="utf-8") as f:
    json.dump({"sid": "s", "root": CARD, "transcript": "", "bucket": "obj-one"}, f)
t = run("cards", CARD, pid=424242)["_text"]
extra.append(("- obj-one [BLOCKED]: wait for the delays (this window's task)" in t
              and json.load(open(os.path.join(PRIVATE_TMP, "kit-window-424242.json"), encoding="utf-8"))["sid"] == "s",
              "--cards marks this window's task from its record, and writes no window record"))
DONE = bucket_project("cards-done", True, [("fin", "DONE", "none")])
state(DONE, "fin", f"# STATE\nAbout: the finished one\nStatus: CLOSED {ago(3)}\n", 3)
extra.append(("- fin (closed " in run("cards", DONE)["_text"] and run("stdin", DONE) == {}
              and "No task buckets here" in run("cards", WITH)["_text"],
              "--cards lists closed tasks with none open (the note stays silent); no scratch -> says so"))
BIG = bucket_project("cards-big", True, [(f"t{i}", "OPEN", "n" * 300) for i in range(10)])
for i in range(10):
    state(BIG, f"t{i}", f"# STATE\nAbout: {'a' * 300}\nUpdated: x   Status: OPEN {'s ' * 150}\n## Next action\n{'q' * 300}\n",
          age_days=i / 100)
state(BIG, "t9", "# STATE\nStatus: OPEN\n" + "z" * 7000, 0)
c = context(run("stdin", BIG))
cc = context(run("stdin", BIG, source="compact"))
extra.append((len(c) <= 9500 and all(f"- t{i} [OPEN]" in c for i in (9, 0, 1, 2, 3, 4, 5, 6))
              and "(+2 older: t7, t8 - " in c and "RECOMMEND one" in c
              and len(cc) <= 10000 and "z" * 1000 in cc and "cut to fit" in cc,
              f"10 long cards fit the 10,000-character hook cap ({len(c)} chars, the 8 newest rows kept); "
              f"compact + a 7 KB STATE.md too ({len(cc)})"))

# Row choice (D007): INDEX.md's order says nothing about recency. my-scraper-project adds new rows
# on TOP, and "the last 8 rows" hid its 4 most recently worked tasks of 12 (2026-10-10).
REC = bucket_project("recent", True, [(f"r{i:02d}", "OPEN", f"step r{i:02d}") for i in range(12)])
for i in range(12):
    state(REC, f"r{i:02d}", f"# STATE\nAbout: task r{i:02d}\nStatus: OPEN\n", age_days=i + 0.5)
o = run("stdin", REC)
extra.append((all(f"- r{i:02d} [OPEN]" in context(o) for i in range(8))
              and not any(f"- r{i:02d} [OPEN]" in context(o) for i in range(8, 12))
              and "(+4 older: r08, r09, r10, r11 - /continue <name> reaches them)" in context(o)
              and context(o).index("- r00 ") < context(o).index("- r07 "),
              "12 open, newest rows on TOP of INDEX.md -> the 8 newest STATE.md shown, newest first; "
              "the 4 oldest named"))
# A P1 always gets a row: the recommendation picks P1 first, and it cannot pick a hidden one.
state(REC, "r09", "# STATE\nAbout: task r09\nUpdated: x   Status: OPEN   Priority: P1\n", age_days=9.5)
c = context(run("stdin", REC))
extra.append(("- r09 [OPEN]: step r09" in c and c.split("- r09 [OPEN]: step r09")[1].split("\n")[0].endswith(" · P1")
              and "(+4 older: r07, r08, r10, r11 - " in c,
              "an old P1 is kept among the 8; the next oldest is named instead"))
t = run("cards", REC)["_text"]
extra.append((all(f"- r{i:02d} [OPEN]" in t for i in range(12)) and "older:" not in t
              and t.index("- r00 ") < t.index("- r11 "),
              "--cards shows up to 20 rows: all 12, newest first"))
# This window's task and a task open in another window always get a row, however old. r00 tops
# INDEX.md (the last-8 rule hid it, and with it the window's own task after /clear) and its
# STATE.md is now the oldest: a task resumed here but not handed off yet.
os.utime(os.path.join(REC, ".claude", "scratch", "r00", "STATE.md"), (time.time() - 30 * 86400,) * 2)
sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
try:
    for pid, rec in ((515151, {"sid": "s-prev", "root": REC, "transcript": "", "bucket": "r00"}),
                     (sleeper.pid, {"sid": "s-other", "root": REC, "transcript": "", "bucket": "r10"})):
        with open(os.path.join(PRIVATE_TMP, f"kit-window-{pid}.json"), "w", encoding="utf-8") as f:
            json.dump(rec, f)
    o = run("stdin", REC, source="clear", pid=515151, sid="s-new", transcript=os.path.join(tmp, "s-new.jsonl"))
    c = context(o)
    extra.append((c.split("\n")[1].startswith("- r00 [OPEN]: step r00 (this window's task) · last ")
                  and " · idle 30d" in c.split("\n")[1]
                  and "- r10 [OPEN]: step r10 (open in another window)" in c and "- r09 [OPEN]" in c
                  and all(f"- r{i:02d} [OPEN]" in c for i in range(1, 6))
                  and "(+4 older: r06, r07, r08, r11 - " in c
                  and o.get("systemMessage", "").endswith("(+4 older) - type /continue to resume r00 "
                                                          "(this window's task). Open in another window: r10."),
                  "/clear: this window's task - top of INDEX, oldest STATE.md - on top and marked; open in "
                  "another window and P1 kept with their marks; the 5 newest fill the rest"))
finally:
    sleeper.kill()
    sleeper.wait()
IDL = bucket_project("idle", True, [("stale", "OPEN", "s"), ("edge", "OPEN", "e"), ("fresh", "OPEN", "f")])
for slug, days in (("stale", 20), ("edge", 14.5), ("fresh", 1)):
    state(IDL, slug, "# STATE\nStatus: OPEN\n", age_days=days)
c = context(run("stdin", IDL))


def row_of(text, slug):
    return text.split(f"- {slug} [OPEN]")[1].split("\n")[0]


extra.append((row_of(c, "stale").endswith(" · idle 20d") and "idle" not in row_of(c, "edge")
              and "idle" not in row_of(c, "fresh") and "never an idle one over a fresh one unless it is P1" in c,
              "STATE.md untouched 20 days -> ` · idle 20d` on its row (14.5 days, 1 day: none); "
              "the note: idle never beats fresh unless P1"))

# Timeline upkeep (bucket handoff-timeline): a session whose window died with no SessionEnd is
# finished at the next start; the previous session of THIS window is never touched (its own
# SessionEnd may still be running).
REP = bucket_project("repair", True, [("alpha", "OPEN", "go")])
CFG = os.path.join(tmp, "cfg")
os.makedirs(os.path.join(CFG, "projects", "p"))
gone = subprocess.Popen([sys.executable, "-c", "pass"])
gone.wait()
old = __import__("time").time() - 600
for rsid in ("eeeeeeee-0000-4000-8000-000000000001", "eeeeeeee-0000-4000-8000-000000000002"):
    tpath = os.path.join(CFG, "projects", "p", rsid + ".jsonl")
    target = os.path.join(REP, ".claude", "scratch", "alpha", "STATE.md")
    with open(tpath, "w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "user", "sessionId": rsid, "timestamp": "2026-10-09T05:00:00Z",
                            "message": {"content": "words of " + rsid}}) + "\n")
        f.write(json.dumps({"type": "assistant", "sessionId": rsid, "timestamp": "2026-10-09T05:01:00Z",
                            "message": {"content": [{"type": "tool_use", "id": "w", "name": "Write",
                                                     "input": {"file_path": target, "content": "# STATE\n"}}]}}) + "\n")
    d = os.path.join(REP, ".claude", "scratch", "alpha", "digests")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, rsid + ".json"), "w", encoding="utf-8") as f:
        json.dump({"sid": rsid, "joined": "2026-10-09T05:01:00Z", "last": "2026-10-09T05:01:00Z", "end": None,
                   "pid": str(gone.pid), "transcript": tpath, "wrote_state": True}, f)
    os.utime(os.path.join(d, rsid + ".json"), (old, old))
with open(os.path.join(PRIVATE_TMP, f"kit-window-{os.getpid()}.json"), "w", encoding="utf-8") as f:
    json.dump({"sid": "eeeeeeee-0000-4000-8000-000000000002", "root": REP}, f)  # this window's previous session
run("stdin", REP, source="clear", pid=os.getpid(), sid="fresh-session", transcript=os.path.join(tmp, "fresh.jsonl"),
    extra={"CLAUDE_CONFIG_DIR": CFG})
dg = os.path.join(REP, ".claude", "scratch", "alpha", "digests")
extra.append((os.path.isfile(os.path.join(dg, "eeeeeeee-0000-4000-8000-000000000001.md"))
              and json.load(open(os.path.join(dg, "eeeeeeee-0000-4000-8000-000000000001.json")))["end"]
              and "eeeeeeee-0000-4000-8000-000000000001" in open(os.path.join(REP, ".claude", "scratch", "alpha", "SESSIONS.md"), encoding="utf-8").read(),
              "a session whose window died with no SessionEnd is finished at the next start: end, digest, timeline"))
extra.append((not os.path.isfile(os.path.join(dg, "eeeeeeee-0000-4000-8000-000000000002.md")),
              "this window's previous session is left to its own SessionEnd"))

# Parallel windows (D001): two windows each hand off and /clear; each gets ITS task back, not the
# one newest handoff. A window is env CLAUDE_PID; both must be live processes.
PAR = bucket_project("parallel", True, [("task-x", "OPEN", "x next"), ("task-y", "OPEN", "y next")])


def wrote_state(name, slug, read=False):
    """A transcript in which a session wrote (or only read) <slug>/STATE.md."""
    path = os.path.join(tmp, name + ".jsonl")
    target = os.path.join(PAR, ".claude", "scratch", slug, "STATE.md")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if not os.path.isfile(target):
        with open(target, "w", encoding="utf-8") as f:
            f.write(f"# STATE - {slug}\nStatus: OPEN\nSTATE-OF-{slug}\n")
    use = {"type": "tool_use", "id": name, "name": "Read" if read else "Write", "input": {"file_path": target}}
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "assistant", "isSidechain": False, "message": {"content": [use]}}) + "\n")
    return path


tx, ty = wrote_state("tx", "task-x"), wrote_state("ty", "task-y")
os.utime(os.path.join(PAR, ".claude", "scratch", "task-x", "STATE.md"), (1_700_000_000, 1_700_000_000))
win_a = os.getpid()                       # this test process: alive for every run below
other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
win_b = other.pid
dead = subprocess.Popen([sys.executable, "-c", "pass"])
dead.wait()
try:
    run("stdin", PAR, pid=win_a, sid="sa1", transcript=tx)          # window A works on task-x
    run("stdin", PAR, pid=win_b, sid="sb1", transcript=ty)          # window B on task-y (newest)
    a2 = run("stdin", PAR, source="clear", pid=win_a, sid="sa2", transcript=os.path.join(tmp, "sa2.jsonl"))
    b2 = run("stdin", PAR, source="clear", pid=win_b, sid="sb2", transcript=os.path.join(tmp, "sb2.jsonl"))
    extra.append(("task-x [OPEN]: x next (this window's task)" in context(a2)
                  and "task-y [OPEN]: y next (open in another window)" in context(a2)
                  and "resume task-x (this window's task)" in a2.get("systemMessage", ""),
                  "window A /clear -> its own task-x, task-y is open in window B (not the newest)"))
    extra.append(("task-y [OPEN]: y next (this window's task)" in context(b2)
                  and "task-x [OPEN]: x next (open in another window)" in context(b2),
                  "window B /clear -> its own task-y; task-x held by A's lineage before A's new session touched it"))
    c = run("stdin", PAR, pid=dead.pid, sid="sc1", transcript=os.path.join(tmp, "sc1.jsonl"))
    extra.append(("next (this window's task)" not in context(c) and "x next (open in another window)" in context(c) and "y next (open in another window)" in context(c)
                  and "<slug> to take one here" in c.get("systemMessage", ""),
                  "a third window at startup -> both tasks busy, nothing resumed unasked"))
    # A closed window holds nothing: its record is dropped and its bucket is free again.
    other.kill()
    other.wait()
    d = run("stdin", PAR, pid=win_a, sid="sa3", transcript=tx, source="compact")
    extra.append(("task-y [OPEN]: y next (newest handoff)" in context(d)
                  and not os.path.exists(os.path.join(PRIVATE_TMP, f"kit-window-{win_b}.json")),
                  "window B closed -> its claim is dropped, task-y is free again"))
    extra.append(("task-x's STATE.md" in context(d) and "STATE-OF-task-x" in context(d)
                  and "STATE-OF-task-y" not in context(d),
                  "compact -> this session's own STATE.md rides along, not the newer one of another task"))
    e = run("stdin", PAR, source="clear", pid=99999999, sid="se", transcript=os.path.join(tmp, "se.jsonl"))
    extra.append(("next (this window's task)" not in context(e) and e.get("systemMessage", "").endswith(
                  "resume task-y. Open in another window: task-x.")
                  and "task-x [OPEN]: x next (open in another window)" in context(e),
                  "/clear in a window with no record -> no lineage; task-x busy in A, task-y free"))
    rx = wrote_state("rx", "task-x", read=True)
    f2 = run("stdin", PAR, source="resume", pid=win_a, sid="sa4", transcript=rx)
    extra.append(("task-x [OPEN]: x next (this window's task)" in context(f2),
                  "resume of a session that only READ task-x's STATE.md (a /continue) -> task-x is its own"))
finally:
    other.kill()
for good, label in extra:
    if not good:
        fails += 1
    print(f"{'ok ' if good else 'BAD'} {label}")
total = len(CASES) + len(extra)
print(f"\n{total - fails}/{total} passed")
sys.exit(1 if fails else 0)
