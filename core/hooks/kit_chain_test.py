"""Self-contained check for kit_chain.py. Run from anywhere: python kit_chain_test.py
Builds its own projects, transcripts and config dir in a temp dir and deletes them on the way
out. Window records and the prune marker go to a private temp dir, never the real one."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
tmp = tempfile.mkdtemp(prefix="kit-chain-test-")
tempfile.tempdir = os.path.join(tmp, "temp")  # read_window / write_window / prune marker
os.makedirs(tempfile.tempdir)
os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(tmp, "cfg")
for k in ("CLAUDE_PID", "CLAUDE_PROJECT_DIR"):
    os.environ.pop(k, None)
import kit_chain as kc  # noqa: E402
import kit_index as ki  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

cases, skipped = [], []
SID1 = "11111111-1111-4111-8111-111111111111"
SID2 = "00000000-2222-4222-8222-222222222222"   # sorts first by sid, joins later
SID3 = "33333333-3333-4333-8333-333333333333"


def ok(cond, label):
    cases.append((bool(cond), label))


def project(name, slugs=("alpha", "beta")):
    root = os.path.join(tmp, name)
    for s in slugs:
        os.makedirs(os.path.join(root, ".claude", "scratch", s))
        with open(os.path.join(root, ".claude", "scratch", s, "FINDINGS.md"), "w", encoding="utf-8") as f:
            f.write(f"# FINDINGS — {s}\n<!-- Append-only. -->\n<!-- Each: ... -->\n")
        with open(os.path.join(root, ".claude", "scratch", s, "DECISIONS.md"), "w", encoding="utf-8") as f:
            f.write(f"# DECISIONS — {s}\n<!-- Append-only. -->\n<!-- Each: ... -->\n")
    return root


def note(root, slug, name):
    return os.path.join(root, ".claude", "scratch", slug, name)


def u(sid, ts, text, **kw):
    return dict({"type": "user", "isSidechain": False, "sessionId": sid, "timestamp": ts,
                 "message": {"role": "user", "content": text}}, **kw)


def a(sid, ts, *blocks, **kw):
    return dict({"type": "assistant", "isSidechain": False, "sessionId": sid, "timestamp": ts,
                 "message": {"role": "assistant", "content": list(blocks)}}, **kw)


def text(t):
    return {"type": "text", "text": t}


def call(name, **inp):
    return {"type": "tool_use", "id": f"t{time.monotonic_ns()}", "name": name, "input": inp}


def result(sid, ts, out="ok"):
    return {"type": "user", "isSidechain": False, "sessionId": sid, "timestamp": ts,
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": out}]}}


def transcript(sid, lines, folder=None):
    folder = folder or os.path.join(tmp, "cfg", "projects", "proj")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, sid + ".jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for ln in lines:
            f.write((ln if isinstance(ln, str) else json.dumps(ln)) + "\n")
    return path


def state(slug, nxt):
    return f"# STATE — {slug}\nUpdated: 2026-10-09   Status: OPEN\n## Objective\nx\n## Next action\n{nxt}\n## User said\n"


def write_state(root, slug, body):
    with open(note(root, slug, "STATE.md"), "w", encoding="utf-8") as f:
        f.write(body)


def entry(root, slug, sid):
    try:
        with open(note(root, slug, os.path.join("digests", sid + ".json")), encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return None


def view(root, slug):
    try:
        return open(note(root, slug, "SESSIONS.md"), encoding="utf-8").read()
    except OSError:
        return ""


def junction(link, target):
    """A junction (Windows, no admin needed) or a symlink; False when neither can be made."""
    try:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(target, link)
        else:
            os.symlink(target, link)
        return True
    except (OSError, AttributeError, NotImplementedError):
        return False


try:
    # 1. One session: /continue, a typed request, Write STATE.md, append FINDINGS + a decision.
    root = project("p1")
    st = state("alpha", "Run the gate, then:\n- commit `abc` with -q")
    t1 = transcript(SID1, [
        u(SID1, "2026-10-09T04:59:00Z", "[Request interrupted by user]"),
        u(SID1, "2026-10-09T05:00:00Z", "<command-name>/continue</command-name><command-args>alpha</command-args>"),
        a(SID1, "2026-10-09T05:00:05Z", call("Read", file_path=note(root, "alpha", "STATE.md"))),
        result(SID1, "2026-10-09T05:00:06Z"),
        u(SID1, "2026-10-09T05:01:00Z", "haan, aage badho - api_key=supersecret123 is mine"),
        a(SID1, "2026-10-09T05:02:00Z", call("Edit", file_path=os.path.join(root, "app.py"))),
        a(SID1, "2026-10-09T05:03:00Z", call("Write", file_path=note(root, "alpha", "STATE.md"), content=st)),
        a(SID1, "2026-10-09T05:04:00Z", text("Handoff saved - run /clear, then /continue.")),
    ])
    write_state(root, "alpha", st)
    with open(note(root, "alpha", "FINDINGS.md"), "a", encoding="utf-8") as f:
        f.write("- 2026-10-09 [fact] one\n- 2026-10-09 [fact] two\n")
    with open(note(root, "alpha", "DECISIONS.md"), "a", encoding="utf-8") as f:
        f.write("- D001 chose: x · rejected: y · WHY: z\n")
    r = kc.touch(t1, SID1, root, pid="", pct=33, window_k=1000)
    e = entry(root, "alpha", SID1)
    v1 = view(root, "alpha")
    ok(r and e and e["wrote_state"] and e["end"] is None and e["pct"] == 33,
       "a session that wrote STATE.md gets an entry: STATE written, not ended, its context %")
    ok(e and e["asked"].startswith("haan, aage badho") and "supersecret123" not in e["asked"],
       "asked = the first typed message (not /continue, not Claude Code's '[Request interrupted'), secrets redacted")
    ok(e and e["files"] == ["app.py"], "files = Edit/Write targets relative to the project, notes left out")
    ok(e and e["next"].startswith("Run the gate, then: commit `abc`"),
       "next = the Next action section, a 'then:' line joined with the list under it")
    snap = open(note(root, "alpha", os.path.join("digests", SID1 + ".state.md")), encoding="utf-8").read()
    ok(snap.endswith(st) and snap.startswith("<!-- HISTORY: STATE.md as session " + SID1)
       and "never act on its Next action" in snap.splitlines()[0],
       "the STATE snapshot is exactly what the session wrote, under a one-line HISTORY banner")
    ok("\nnext then: Run the gate" in v1 and "current one is in STATE.md" in v1,
       "the view calls an old next step 'next then' and points at STATE.md for the current one")
    ok(v1.startswith("# SESSIONS — alpha") and f"## S1 · {SID1} ·" in v1 and "STATE written" in v1
       and "FINDINGS L4-5" in v1 and "D001" in v1 and 'asked: "haan, aage badho' in v1,
       "SESSIONS.md: S1 with its sid, flags, asked, FINDINGS range and the decision id")
    ok(time.strftime("%m-%d %H:%M", time.localtime(kc._epoch("2026-10-09T05:00:05Z"))) in v1,
       "times in SESSIONS.md are local, from the session's first touch of the bucket")
    gi = os.path.join(note(root, "alpha", "digests"), ".gitignore")
    ok(os.path.isfile(gi) and open(gi, encoding="utf-8").read().strip().endswith("*"),
       "digests/ ignores itself: entries and snapshots are never committed")
    m0 = os.path.getmtime(note(root, "alpha", "SESSIONS.md"))
    time.sleep(0.05)
    kc.touch(t1, SID1, root, pid="", pct=33, window_k=1000)
    ok(view(root, "alpha") == v1 and os.path.getmtime(note(root, "alpha", "SESSIONS.md")) == m0,
       "a repeated touch changes nothing and rewrites nothing")

    # 2. finish: end set, digest written; skipped when one newer than the transcript exists.
    ok(kc.finish(t1, SID1, root) == 1 and entry(root, "alpha", SID1)["end"] == "2026-10-09T05:04:00Z"
       and os.path.isfile(note(root, "alpha", os.path.join("digests", SID1 + ".md"))),
       "finish(): end set to the last line, verbatim digest written beside the entry")
    ok("no verbatim record" not in view(root, "alpha") and "not ended" not in view(root, "alpha"),
       "the view drops 'no verbatim record' and 'not ended' once both exist")
    ok(kc.finish(t1, SID1, root) == 0, "a digest newer than the transcript is not rewritten")

    # 3. A resumed session that goes on past its end is open again.
    with open(t1, "a", encoding="utf-8") as f:
        f.write(json.dumps(a(SID1, "2026-10-09T09:00:00Z", text("resumed and working"))) + "\n")
    kc.touch(t1, SID1, root)
    ok(entry(root, "alpha", SID1)["end"] is None and "not ended" in view(root, "alpha")
       and entry(root, "alpha", SID1)["pct"] == 33,
       "a resumed session past its end is open again; its stored % is kept")

    # 4. Second session joins later (sid sorts first) and overlaps nothing; then appends more.
    kc.finish(t1, SID1, root)  # S1 ends before S2 starts, as /clear does it
    st2 = state("alpha", "Ship it.")
    t2 = transcript(SID2, [
        u(SID2, "2026-10-09T10:00:00Z", "continue the alpha work"),
        a(SID2, "2026-10-09T10:01:00Z", call("Write", file_path=note(root, "alpha", "STATE.md"), content=st2)),
        a(SID2, "2026-10-09T10:02:00Z", call("Bash", command=f"cat >> {note(root, 'alpha', 'FINDINGS.md')} <<'EOF'\nx\nEOF")),
    ])
    write_state(root, "alpha", st2)
    with open(note(root, "alpha", "FINDINGS.md"), "a", encoding="utf-8") as f:
        f.write("- 2026-10-09 [fact] three\n")
    with open(note(root, "alpha", "DECISIONS.md"), "a", encoding="utf-8") as f:
        f.write("- D002 chose: a\n")
    kc.touch(t2, SID2, root)
    v = view(root, "alpha")
    i1, i2 = v.find(f"## S1 · {SID1}"), v.find(f"## S2 · {SID2}")
    ok(0 <= i1 < i2, "order is by first touch of the bucket, not by sid")
    ok("FINDINGS L6-6" in v[i2:] and "D002" in v[i2:] and "D001" not in v[i2:],
       "the second session gets only the FINDINGS lines and decisions added after the first")
    ok(open(note(root, "alpha", os.path.join("digests", SID1 + ".state.md")), encoding="utf-8").read().endswith(st),
       "S1's STATE snapshot survives S2 rewriting STATE.md")

    # 5. Overlapping sessions are marked parallel.
    t3 = transcript(SID3, [
        u(SID3, "2026-10-09T10:00:30Z", "parallel window"),
        a(SID3, "2026-10-09T10:00:40Z", call("Edit", file_path=note(root, "alpha", "STATE.md"))),
        a(SID3, "2026-10-09T10:05:00Z", text("done")),
    ])
    kc.touch(t3, SID3, root)
    v = view(root, "alpha")
    ok("∥ S3" in v[v.find("## S2"):v.find("## S3")] and "∥ S2" in v[v.find("## S3"):],
       "two sessions on one bucket at the same time are marked ∥ each other")
    ok(not os.path.isfile(note(root, "alpha", os.path.join("digests", SID3 + ".state.md"))),
       "an Edit whose STATE.md mtime does not match this session's write is not snapshotted")

    # 6. Read-only session -> flagged entry in the bucket it read; a later write elsewhere drops it.
    sid4 = "44444444-4444-4444-8444-444444444444"
    lines4 = [u(sid4, "2026-10-09T11:00:00Z", "look at beta"),
              a(sid4, "2026-10-09T11:00:10Z", call("Read", file_path=note(root, "beta", "STATE.md")))]
    t4 = transcript(sid4, lines4)
    kc.touch(t4, sid4, root)
    e4 = entry(root, "beta", sid4)
    ok(e4 and not e4["wrote_state"] and "no STATE write" in view(root, "beta"),
       "a session that only read a bucket gets an entry there, flagged 'no STATE write'")
    t4 = transcript(sid4, lines4 + [
        u(sid4, "2026-10-09T11:01:00Z", "no, work on alpha"),
        a(sid4, "2026-10-09T11:02:00Z", call("Edit", file_path=note(root, "alpha", "FINDINGS.md")))])
    kc.touch(t4, sid4, root)
    ok(entry(root, "beta", sid4) is None and entry(root, "alpha", sid4) is not None
       and sid4 not in view(root, "beta"),
       "once it writes another bucket, the read-only entry goes and the view forgets it")

    # 7. Two buckets written: the earlier one's digest is cut where the session left it.
    root2 = project("p2")
    sid5 = "55555555-5555-4555-8555-555555555555"
    t5 = transcript(sid5, [
        u(sid5, "2026-10-09T12:00:00Z", "alpha task words"),
        a(sid5, "2026-10-09T12:01:00Z", call("Write", file_path=note(root2, "alpha", "STATE.md"), content=state("alpha", "a"))),
        u(sid5, "2026-10-09T12:02:00Z", "now the beta task, secret beta words"),
        a(sid5, "2026-10-09T12:03:00Z", call("Write", file_path=note(root2, "beta", "STATE.md"), content=state("beta", "b"))),
        a(sid5, "2026-10-09T12:04:00Z", text("both done")),
    ])
    ok(kc.finish(t5, sid5, root2) == 2, "a session that wrote two buckets gets a digest in each")
    da = open(note(root2, "alpha", os.path.join("digests", sid5 + ".md")), encoding="utf-8").read()
    db = open(note(root2, "beta", os.path.join("digests", sid5 + ".md")), encoding="utf-8").read()
    ok("alpha task words" in da and "secret beta words" not in da and "secret beta words" in db,
       "the bucket it left first never gets the next task's conversation")
    ok(entry(root2, "beta", sid5)["asked"] == "now the beta task, secret beta words"
       and entry(root2, "alpha", sid5)["asked"] == "alpha task words",
       "asked per bucket: the request that led to it")

    # 8. Sidechain and foreign-session lines are ignored; a missing bucket is never created.
    sid6 = "66666666-6666-4666-8666-666666666666"
    t6 = transcript(sid6, [
        u(sid6, "2026-10-09T13:00:00Z", "hi"),
        a(sid6, "2026-10-09T13:00:01Z", call("Write", file_path=note(root2, "alpha", "STATE.md"), content="x"), isSidechain=True),
        a("99999999-9999-4999-8999-999999999999", "2026-10-09T13:00:02Z",
          call("Write", file_path=note(root2, "beta", "STATE.md"), content="x")),
        a(sid6, "2026-10-09T13:00:03Z", call("Write", file_path=note(root2, "gone", "STATE.md"), content="x")),
    ])
    ok(kc.touch(t6, sid6, root2) == {} and entry(root2, "alpha", sid6) is None and entry(root2, "beta", sid6) is None
       and not os.path.exists(note(root2, "gone", "")),
       "sidechain and other-session lines count for nothing; a bucket that is gone is not recreated")

    # 9. Links: a linked scratch, bucket or digests/ is refused.
    root3 = project("p3", slugs=())
    os.makedirs(os.path.join(root3, ".claude"))
    outside = project("outside")
    made = junction(os.path.join(root3, ".claude", "scratch"), os.path.join(outside, ".claude", "scratch"))
    if made:
        t9 = transcript("77777777-7777-4777-8777-777777777777", [
            a("77777777-7777-4777-8777-777777777777", "2026-10-09T14:00:00Z",
              call("Write", file_path=note(root3, "alpha", "STATE.md"), content="x"))])
        ok(not ki.scratch_ok(root3) and kc.touch(t9, "77777777-7777-4777-8777-777777777777", root3) == {}
           and not os.path.isdir(note(outside, "alpha", "digests")),
           "a .claude/scratch that is a link or junction: nothing is written through it")
        root4 = project("p4", slugs=("alpha",))
        os.makedirs(os.path.join(tmp, "elsewhere-" + str(os.getpid())), exist_ok=True)
        made2 = junction(note(root4, "alpha", "digests"), os.path.join(tmp, "elsewhere-" + str(os.getpid())))
        if made2:
            t10 = transcript("88888888-8888-4888-8888-888888888888", [
                a("88888888-8888-4888-8888-888888888888", "2026-10-09T14:00:00Z",
                  call("Write", file_path=note(root4, "alpha", "STATE.md"), content="x"))])
            kc.touch(t10, "88888888-8888-4888-8888-888888888888", root4)
            ok(ki.safe_dir(note(root4, "alpha", ""), "digests") is None
               and os.listdir(os.path.join(tmp, "elsewhere-" + str(os.getpid()))) == [],
               "a digests/ that is a link or junction: nothing is written through it")
        else:
            skipped.append("digests junction (could not create one here)")
    else:
        skipped.append("scratch junction/symlink tests (could not create one here)")

    # 10. Repair takes only a Claude Code transcript path.
    ok(kc._transcript_ok(t1, SID1) and not kc._transcript_ok(t1, SID2)
       and not kc._transcript_ok(os.path.join(tmp, "p1", "x.jsonl"), "x"),
       "repair accepts only <sid>.jsonl under the config dir's projects/")
    stray = os.path.join(tmp, "stray")
    os.makedirs(stray)
    shutil.copy(t1, os.path.join(stray, SID1 + ".jsonl"))
    ok(not kc._transcript_ok(os.path.join(stray, SID1 + ".jsonl"), SID1),
       "a transcript-named file outside projects/ is refused")

    # 11. Repair: a dead window's session is finished; a live current one, a skipped one, a fresh one are not.
    root5 = project("p5", slugs=("alpha",))
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    sids = {"dead": "aaaaaaaa-0000-4000-8000-000000000001", "live": "aaaaaaaa-0000-4000-8000-000000000002",
            "skip": "aaaaaaaa-0000-4000-8000-000000000003", "fresh": "aaaaaaaa-0000-4000-8000-000000000004"}
    pids = {"dead": str(dead.pid), "live": str(os.getpid()), "skip": str(dead.pid), "fresh": str(dead.pid)}
    for k, sid in sids.items():
        tk = transcript(sid, [u(sid, "2026-10-09T15:00:00Z", f"{k} words"),
                              a(sid, "2026-10-09T15:00:01Z", call("Write", file_path=note(root5, "alpha", "STATE.md"), content="s"))])
        kc.touch(tk, sid, root5, pid=pids[k])
        if k != "fresh":
            jp = note(root5, "alpha", os.path.join("digests", sid + ".json"))
            os.utime(jp, (time.time() - 300, time.time() - 300))
    ki.write_window(str(os.getpid()), {"sid": sids["live"]})
    got = [kc.repair(root5, skip={sids["skip"]}) for _ in range(4)]
    ok(got[0] == sids["dead"] and entry(root5, "alpha", sids["dead"])["end"]
       and os.path.isfile(note(root5, "alpha", os.path.join("digests", sids["dead"] + ".md"))),
       "repair finishes a session whose window process is gone: end + digest")
    ok(entry(root5, "alpha", sids["live"])["end"] is None and entry(root5, "alpha", sids["skip"])["end"] is None
       and entry(root5, "alpha", sids["fresh"])["end"] is None and got[1:] == [None, None, None],
       "never a live window's current session, a skipped one, or one touched under a minute ago")
    ki.write_window(str(os.getpid()), {"sid": "someone-else"})
    ok(kc.repair(root5) == sids["live"], "a live window that moved on to another session: its old one is finished")

    # 12. Retention: closed > 7 days loses verbatim records only; open and recent keep all.
    root6 = project("p6", slugs=("old", "recent", "open", "nodate"))
    os.makedirs(os.path.join(root6, ".claude", "scratch", "_closed", "moved", "digests"))
    day = 86400
    for slug, status in (("old", "CLOSED " + time.strftime("%Y-%m-%d", time.localtime(time.time() - 8 * day))),
                         ("recent", "CLOSED " + time.strftime("%Y-%m-%d", time.localtime(time.time() - 6 * day))),
                         ("open", "OPEN"), ("nodate", "CLOSED"),
                         (os.path.join("_closed", "moved"), "CLOSED " + time.strftime("%Y-%m-%d", time.localtime(time.time() - 30 * day)))):
        os.makedirs(note(root6, slug, "digests"), exist_ok=True)
        write_state(root6, slug, f"# STATE\nUpdated: x   Status: {status}\n")
        for f in ("s.json", "s.md", "s.state.md"):
            with open(note(root6, slug, os.path.join("digests", f)), "w", encoding="utf-8") as fh:
                fh.write('{"sid": "s", "joined": "2026-10-01T00:00:00Z"}' if f.endswith("json") else "x")
    os.utime(note(root6, "nodate", "STATE.md"), (time.time() - 9 * day, time.time() - 9 * day))
    oldtmp = note(root6, "open", os.path.join("digests", "x.md.1.2.tmp"))
    newtmp = note(root6, "open", os.path.join("digests", "y.md.1.2.tmp"))
    for p in (oldtmp, newtmp):
        open(p, "w").close()
    os.utime(oldtmp, (time.time() - 7200, time.time() - 7200))
    kc.prune(root6)

    def left(slug):
        return sorted(os.listdir(note(root6, slug, "digests")))
    ok(left("old") == [".gitignore", "s.json"] or left("old") == ["s.json"],
       "closed 8 days ago: digest and snapshot deleted, the entry kept")
    ok(left("recent") == ["s.json", "s.md", "s.state.md"] and "s.md" in left("open"),
       "closed 6 days ago and an open bucket: nothing deleted")
    ok(left(os.path.join("_closed", "moved")) == ["s.json"] and left("nodate") == ["s.json"],
       "a bucket moved to _closed/ is pruned too; no close date = STATE.md's mtime")
    ok(not os.path.exists(oldtmp) and os.path.exists(newtmp), "a tmp file older than an hour goes, a new one stays")
    ok("no verbatim record" in view(root6, "old"), "a pruned bucket's view says the record is gone")
    # The prune flag lives in the project's scratch, never the temp dir; a stale context marker
    # goes, a fresh one, a folder and another tool's file stay.
    t = tempfile.gettempdir()
    kc.maintain(root6, deadline=time.time() + 5)
    aged = {"kit-context-old-sid": 31 * day, "kit-context-new-sid": 29 * day,
            "other-tool-file": 60 * day, "kit-context-test-dir": 60 * day}
    for name, age in aged.items():
        p = os.path.join(t, name)
        os.makedirs(p) if name.endswith("-dir") else open(p, "w").close()
        os.utime(p, (time.time() - age, time.time() - age))
    swept = ki.sweep_context_markers()
    ok(os.path.isfile(os.path.join(root6, ".claude", "scratch", ".kit-pruned"))
       and not [n for n in os.listdir(t) if "prune" in n]
       and swept == 1 and sorted(n for n in os.listdir(t) if n in aged)
       == ["kit-context-new-sid", "kit-context-test-dir", "other-tool-file"],
       "prune flag in scratch, none in temp; a context marker 31 days old goes, the rest stay")

    # 13. A torn entry is skipped, never a crash.
    with open(note(root, "alpha", os.path.join("digests", "torn.json")), "w", encoding="utf-8") as f:
        f.write('{"sid": "torn", "joined": ')
    with open(note(root, "alpha", os.path.join("digests", "bad.json")), "w", encoding="utf-8") as f:
        f.write(json.dumps({"sid": "bad", "joined": "2026-10-09T23:00:00Z", "lines": {"FINDINGS": "x"}}))
    kc.render(note(root, "alpha", ""))
    v = view(root, "alpha")
    ok("torn" not in v and "## S" in v and "bad" in v, "a torn entry is skipped; a bad field is read as nothing")

    # 14. Midnight: both dates shown.
    span = kc._span({"joined": "2026-10-09T18:00:00Z", "last": "2026-10-10T20:00:00Z"})
    ok(span.count("-") == 2 and "→" in span, "a session crossing midnight shows the date at both ends")

    # 15. Two hook processes at once on one bucket: both entries survive, the view lists both.
    root7 = project("p7", slugs=("alpha",))
    ps = []
    for sid in ("bbbbbbbb-0000-4000-8000-000000000001", "bbbbbbbb-0000-4000-8000-000000000002"):
        tk = transcript(sid, [u(sid, "2026-10-09T16:00:00Z", "go"),
                              a(sid, "2026-10-09T16:00:01Z", call("Edit", file_path=note(root7, "alpha", "FINDINGS.md")))])
        ps.append(subprocess.Popen([sys.executable, "-c", f"import sys; sys.path.insert(0, {HERE!r}); import kit_chain; "
                                    f"kit_chain.touch({tk!r}, {sid!r}, {root7!r})"]))
    for p in ps:
        p.wait()
    kc.maintain(root7, deadline=time.time() + 5)
    v = view(root7, "alpha")
    ok("bbbbbbbb-0000-4000-8000-000000000001" in v and "bbbbbbbb-0000-4000-8000-000000000002" in v
       and not [f for f in os.listdir(note(root7, "alpha", "digests")) if f.endswith(".tmp")],
       "two processes writing one bucket at once: both entries, no tmp left, the view lists both")

    # 16. Backfill: sessions already on disk get their records, line counts left out.
    root8 = project("p8", slugs=("alpha",))
    folder = os.path.join(tmp, "cfg", "projects", "p8")
    for sid, ts in (("cccccccc-0000-4000-8000-000000000001", "2026-10-01T10:00:00Z"),
                    ("cccccccc-0000-4000-8000-000000000002", "2026-10-02T10:00:00Z")):
        tk = transcript(sid, [u(sid, ts, "old work"), a(sid, ts, call("Write", file_path=note(root8, "alpha", "STATE.md"), content=state("alpha", "n")))], folder)
        os.utime(tk, (time.time() - 3600, time.time() - 3600))
    ok(kc.backfill(root8, folder) == 2 and view(root8, "alpha").count("## S") == 2
       and "FINDINGS L" not in view(root8, "alpha") and len([f for f in os.listdir(note(root8, "alpha", "digests")) if f.endswith(".md")]) == 4,
       "backfill: every session on disk gets entry, snapshot and digest; no line ranges guessed")

    # 17. Shell commands: a note is written only when it is the write's target (2026-10-10: a
    # `2>/dev/null` made a READ of a closed task's STATE.md a write, and filed the session there).
    S = ".claude/scratch/"
    shapes = [
        (f'"$X" --version 2>/dev/null; head -30 {S}a/STATE.md | cut -c1-300', [("a", "STATE", False)]),
        (f"ls x 2>&1; cat {S}a/FINDINGS.md", [("a", "FINDINGS", False)]),
        (f'grep -n "->" {S}a/STATE.md', [("a", "STATE", False)]),
        (f'python3 -c "print(1 >= 0)"; cat {S}a/STATE.md', [("a", "STATE", False)]),
        (f"cat >> {S}a/FINDINGS.md <<'EOF'\n- see {S}b/STATE.md > x\nEOF", [("a", "FINDINGS", True)]),
        (f"echo x | tee -a {S}a/STATE.md", [("a", "STATE", True)]),
        (f"sed -i 's|a|b|' {S}a/STATE.md", [("a", "STATE", True)]),
        (f"sed -n '1,5p' {S}a/STATE.md", [("a", "STATE", False)]),
        (f"cp /tmp/s.md {S}a/STATE.md", [("a", "STATE", True)]),
        (f"cp {S}a/STATE.md /tmp/s.md", [("a", "STATE", False)]),
        ('Set-Content -Path ".claude\\scratch\\a\\STATE.md" -Value $s', [("a", "STATE", True)]),
        (f"Get-Content {S}a/STATE.md | Select-Object -First 5", [("a", "STATE", False)]),
        (f"python -c \"open('{S}a/DECISIONS.md', 'a').write(x)\"", [("a", "DECISIONS", True)]),
        (f"python -c \"print(open('{S}a/STATE.md').read())\"", [("a", "STATE", False)]),
        (f'echo done > "{S}a/STATE.md"', [("a", "STATE", True)]),
        (f"cat {S}a/STATE.md > /tmp/out.md", [("a", "STATE", False)]),
        (f"wc -l < {S}a/STATE.md", [("a", "STATE", False)]),
        (f"cat {S}a/STATE.md.bak", []),
        (f"cat {S}a/STATE.md; echo x >> {S}b/FINDINGS.md", [("a", "STATE", False), ("b", "FINDINGS", True)]),
        (f"(Get-Content {S}a/STATE.md) -replace 'x','y' | Set-Content {S}a/STATE.md",
         [("a", "STATE", False), ("a", "STATE", True)]),
        (f"cat <<'EOF' | bash\necho x > {S}a/STATE.md\nEOF", [("a", "STATE", True)]),
        (f"git commit -q -F - <<'EOF'\nfix: tee {S}a/STATE.md\nEOF", []),
        (f'printf "%s" "- x" >> "D:/My Projects/p/{S}a/FINDINGS.md"', [("a", "FINDINGS", True)]),
        # a bare name after a cd into the bucket (293 such commands in the user's transcripts)
        (f"cd /d/p/{S}a && cat >> FINDINGS.md <<'EOF'\n- x\nEOF", [("a", "FINDINGS", True)]),
        (f"cd {S}a && grep -c x STATE.md FINDINGS.md", [("a", "STATE", False), ("a", "FINDINGS", False)]),
        (f"cd {S}a && cd /tmp && cat STATE.md", []),
        # code that writes through a name, and a script file written to run next
        (f"python - <<'EOF'\np = r'{S}a/STATE.md'\nt = open(p, encoding='utf-8').read()\n"
         f"open(p, 'w', encoding='utf-8').write(t)\nEOF", [("a", "STATE", True)]),
        (f"python - <<'EOF'\np = '{S}a/STATE.md'\nprint(open(p, encoding='ascii').read())\nEOF", [("a", "STATE", False)]),
        (f"cat > /tmp/fix.py <<'EOF'\np = r'{S}a/STATE.md'\nopen(p, 'w').write('x')\nEOF\npython /tmp/fix.py",
         [("a", "STATE", True)]),
        (f"python - <<'EOF'\nimport pathlib\np = pathlib.Path('{S}a/STATE.md')\np.write_text(p.read_text())\nEOF",
         [("a", "STATE", True)]),
        (f"python - <<'EOF'\nfrom pathlib import Path\np = Path(r'D:/x/{S}a/FINDINGS.md')\n"
         f"with p.open('a', encoding='utf-8') as f:\n    f.write('- x')\nEOF", [("a", "FINDINGS", True)]),
        (f"python - <<'EOF'\nfor p, old, new in [('{S}a/STATE.md', 'x', 'y')]:\n"
         f"    s = open(p).read(); open(p, 'w').write(s.replace(old, new))\nEOF", [("a", "STATE", True)]),
        (f"python - <<'EOF'\np = '{S}INDEX.md'\nq = '{S}a/STATE.md'\nprint(open(q).read())\n"
         f"open(p, 'w').write('x')\nEOF", [("a", "STATE", False)]),
        (f"python - <<'EOF'\np = '{S}INDEX.md'\nprint(open('{S}a/STATE.md').read())\n"
         f"open(p, 'w').write('x')\nEOF", [("a", "STATE", False)]),
        (f"cat > /tmp/x.sh <<'EOF'\necho y >> {S}a/FINDINGS.md\nEOF\nbash /tmp/x.sh", [("a", "FINDINGS", True)]),
        # quoting the shell itself would read: a PowerShell here-string, an escaped quote
        ("$b = @'\nsee .claude/scratch/b/STATE.md, don't\n'@\nSet-Content -Path '.claude\\scratch\\a\\STATE.md' -Value $b",
         [("b", "STATE", False), ("a", "STATE", True)]),
        (f"printf '%s\\n' 'it'\\''s done' >> {S}a/FINDINGS.md", [("a", "FINDINGS", True)]),
        (f"touch {S}a/FINDINGS.md", [("a", "FINDINGS", True)]),
        # a name holding the note or the bucket
        (f'F={S}a/FINDINGS.md; printf "%s" "- x" >> "$F"; tail -1 "$F"',
         [("a", "FINDINGS", False), ("a", "FINDINGS", True), ("a", "FINDINGS", False)]),
        (f'B=/d/p/{S}a; cat >> "$B/DECISIONS.md" <<\'EOF\'\n- D1 x\nEOF', [("a", "DECISIONS", True)]),
        (f"$f = 'D:\\p\\.claude\\scratch\\a\\STATE.md'; Get-Content $f | Select-Object -First 3",
         [("a", "STATE", False), ("a", "STATE", False)]),
        (f'echo "F={S}a/STATE.md"; cat x > "$F"', [("a", "STATE", False)]),
    ]
    bad = [(c, ki.shell_notes(c), want) for c, want in shapes if ki.shell_notes(c) != want]
    for c, got, want in bad:
        print(f"shell_notes({c!r}) = {got}, want {want}")
    ok(not bad, f"shell_notes: {len(shapes) - len(bad)}/{len(shapes)} command shapes judged right "
                "(redirect target, tee, sed -i, cp target, Set-Content, open('w'), data heredoc bodies)")

    # 18. The dogfood case end to end: a session that wrote its own task, then READ a closed one.
    root9 = project("p9", slugs=("mine", "closed"))
    sid9 = "99999999-0000-4000-8000-000000000009"
    t9 = transcript(sid9, [
        u(sid9, "2026-10-10T01:00:00Z", "work on mine"),
        a(sid9, "2026-10-10T01:01:00Z", call("Write", file_path=note(root9, "mine", "STATE.md"), content=state("mine", "m"))),
        a(sid9, "2026-10-10T01:02:00Z", call("Bash", command=f'claude --version 2>/dev/null; head -30 {S}closed/STATE.md | cut -c1-300')),
    ])
    kc.touch(t9, sid9, root9)
    ok(entry(root9, "mine", sid9) and entry(root9, "closed", sid9) is None
       and ki.session_bucket(t9, root9) == ki.bucket_dir(root9, "mine"),
       "a read with `2>/dev/null` of another task's STATE.md files nothing there, and /clear stays on this task")
    # 18b. A copy of a task outside the project (a sandbox, another project) is not that task:
    # 2026-10-10 a `sed -i` on `$T/.claude/scratch/<closed>/STATE.md` filed a session there.
    elsewhere = os.path.join(tmp, "elsewhere", ".claude", "scratch", "closed", "STATE.md")
    sid9b = "99999999-0000-4000-8000-00000000009b"
    t9b = transcript(sid9b, [
        u(sid9b, "2026-10-10T03:00:00Z", "sandbox test"),
        a(sid9b, "2026-10-10T03:01:00Z", call("Bash", command=f'T=$(mktemp -d); cp -r .claude/scratch "$T/.claude/"; '
                                                              f'sed -i s/a/b/ "$T/{S}closed/STATE.md"')),
        a(sid9b, "2026-10-10T03:02:00Z", call("Write", file_path=elsewhere, content=state("closed", "c"))),
        a(sid9b, "2026-10-10T03:03:00Z", call("Bash", command=f'echo x >> "$CLAUDE_PROJECT_DIR/{S}mine/FINDINGS.md"')),
    ])
    kc.touch(t9b, sid9b, root9)
    home = os.path.expanduser("~")
    ok(entry(root9, "closed", sid9b) is None and (entry(root9, "mine", sid9b) or {}).get("sid") == sid9b
       and ki.session_bucket(t9b, root9) is None
       and ki.note_here("~/", home) and ki.note_here(root9.replace("\\", "/") + "/", root9)
       and not ki.note_here("/tmp/x/", root9)
       and ki.shell_notes(f"$r='{root9}'; Add-Content \"$r\\.claude\\scratch\\mine\\FINDINGS.md\" x", root9)
       == [("mine", "FINDINGS", True)],
       "a sandbox ($T) or another folder's copy of a task files nothing; $CLAUDE_PROJECT_DIR, ~ and a name set to the root do")

    # 19. A background task's notice is never what the user asked.
    sid10 = "aaaaaaaa-0000-4000-8000-00000000000a"
    t10 = transcript(sid10, [
        u(sid10, "2026-10-10T02:00:00Z", "<task-notification>\n<task-id>x1</task-id>\n<status>completed</status>\n"
                                         "<summary>Agent \"r\" finished</summary>\n<result>report</result>\n</task-notification>"),
        u(sid10, "2026-10-10T02:01:00Z", "the real request"),
        a(sid10, "2026-10-10T02:02:00Z", call("Write", file_path=note(root9, "mine", "STATE.md"), content=state("mine", "m"))),
    ])
    kc.touch(t10, sid10, root9)
    ok((entry(root9, "mine", sid10) or {}).get("asked") == "the real request",
       "asked skips a <task-notification>: the harness wrote it, not the user")
    ok(kc._asked([(1, "/clear"), (2, "/continue kya hum in numbers ko aur improve")], None)
       == "/continue kya hum in numbers ko aur improve"
       and kc._asked([(1, "/continue alpha"), (2, "haan, aage badho")], None) == "haan, aage badho",
       "asked: a slash command given a sentence is the request; `/continue alpha` and `/clear` are not")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

fails = sum(1 for good, _ in cases if not good)
for good, label in cases:
    print(f"{'ok ' if good else 'BAD'} {label}")
for s in skipped:
    print(f"SKIP {s}")
print(f"\n{len(cases) - fails}/{len(cases)} passed")
sys.exit(1 if fails else 0)
