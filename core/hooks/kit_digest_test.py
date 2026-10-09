"""Self-contained check for kit_digest.py. Run from anywhere: python kit_digest_test.py
Builds its own transcript in a temp dir and deletes it on the way out."""
import json
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kit_digest as kd  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

tmp = tempfile.mkdtemp(prefix="kit-digest-test-")
cases = []


def ok(cond, label):
    cases.append((bool(cond), label))


def user(text, **kw):
    return dict({"type": "user", "isSidechain": False, "timestamp": "2026-10-07T08:15:00Z",
                 "message": {"role": "user", "content": text}}, **kw)


def asst(*blocks):
    return {"type": "assistant", "isSidechain": False, "timestamp": "2026-10-07T08:16:00Z",
            "message": {"role": "assistant", "content": list(blocks)}}


def text(t):
    return {"type": "text", "text": t}


def tool(tid, name, inp):
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}


def result(tid, out, err=False):
    return {"type": "user", "isSidechain": False,
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid,
                                                     "content": out, "is_error": err}]}}


LONG = "Make the archive queue robust: it must keep running with no stops, ever, and report in Hinglish tables."
lines = [
    user(LONG),
    user("<system-reminder>internal note</system-reminder><ide_opened_file>x.py</ide_opened_file>please also check B2"),
    user("<command-name>/continue</command-name><command-message>continue</command-message><command-args>b2-storage</command-args>"),
    user("skill text the harness injected", isMeta=True),
    {"type": "user", "isSidechain": True, "message": {"content": "a subagent's own prompt"}},
    asst(text("Reading the two files."), tool("t1", "Read", {"file_path": "D:/p/a.md"}),
         tool("t2", "Bash", {"command": "python check.py --all"})),
    # parallel calls answer out of order: the Bash output must sit under the Bash call
    result("t2", "line\n" * 300 + "RESULT: 41/41 passed"),
    result("t1", "the whole file a.md, which is on disk"),
    asst(tool("t3", "Agent", {"subagent_type": "researcher", "description": "find the cap"})),
    result("t3", "Report: the cap is 4096 tokens (docs, verified)."),
    asst(tool("t4", "Bash", {"command": "rm -rf /"})),
    result("t4", "The user doesn't want to proceed with this tool use.", err=True),
    asst(tool("t5", "Edit", {"file_path": "D:/p/app.py"})),
    result("t5", "Error: String to replace not found in file.", err=True),
    {"type": "attachment", "attachment": {"type": "queued_command", "prompt": [{"type": "text", "text": "and push after"}]}},
    asst(text("Done: 41/41 passed, key sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUV kept out, api_key=supersecret123")),
    user(LONG),  # the same long message pasted again adds nothing
    "{torn line",
    user("last question: what next?"),
    asst(text("Next: run the gate.")),
    # review 2026-10-07: git's "[rejected]" is no refusal; a refusal's words are the user's,
    # whole; a short answer that repeats an earlier one still answers its own turn
    user("now push it"),
    asst(tool("t6", "Bash", {"command": "git push"})),
    result("t6", "Exit code 1\n ! [rejected]        main -> main (fetch first)", err=True),
    asst(tool("t7", "Bash", {"command": "git push -f"})),
    result("t7", "The user doesn't want to proceed with this tool use. The tool use was rejected (eg. if it "
                 "was a file edit, the new_string was NOT written to the file). To tell you how to proceed, "
                 "the user said: " + "Never force-push; push to release-2026-10, tag v3.4.1 and quote the "
                 "CHANGELOG line exactly. " * 3, err=True),
    asst(text("Done.")),
    user("and again for the tag"),
    asst(text("Done.")),
    asst(tool("t8", "Bash", {"command": "env | grep KEY"})),
    result("t8", "EXA_API_KEY=3f1c0a9b8c7d6e5f6666\nDB_PASSWORD=Sup3rS3cretPw\n{\"password\": \"hunter2hunter2\"}\n"
                 "Authorization: Bearer abcdefghijklmnopqrstuvwx\n" + "x" * 590 + " sk-ant-api03-" + "Q" * 620),
]
path = os.path.join(tmp, "t.jsonl")
with open(path, "w", encoding="utf-8") as f:
    for ln in lines:
        f.write((ln if isinstance(ln, str) else json.dumps(ln)) + "\n")

try:
    turns = kd.extract(path)
    full = kd.render(turns, {"session": "s1", "transcript": path}, 0)
    ok(LONG in full and full.count(LONG) == 1, "a user message is kept verbatim, a repeat of it once only")
    ok("please also check B2" in full and "internal note" not in full and "x.py" not in full,
       "system-reminder and IDE-opened-file noise is cut from the user's words")
    ok("/continue b2-storage" in full, "a slash command reads as `/name args`")
    ok("skill text the harness injected" not in full and "a subagent's own prompt" not in full,
       "isMeta rows and sidechain rows are left out")
    i_bash = full.find("Bash: python check.py --all")
    ok(i_bash >= 0 and "RESULT: 41/41 passed" in full[i_bash:i_bash + 900]
       and "the whole file a.md" not in full,
       "a shell's output tail sits under its own call; a Read's output is left out")
    ok("Report: the cap is 4096 tokens" in full, "a subagent's report is kept")
    files = next((ln for ln in full.splitlines() if ln.startswith("Files Edit/Write was called on")), "")
    ok("(1," in files and "`D:/p/app.py`" in files and "a.md" not in files,
       "the header lists every file Edit/Write was called on, a Read is not one")
    ok("**User refused:**" in full and "**Error:**" in full and "String to replace not found" in full,
       "a refusal and an error are kept, labelled")
    ok("and push after" in full, "a prompt queued while a turn ran is kept")
    ok("sk-ant-api03" not in full and "supersecret123" not in full and "[redacted]" in full,
       "secrets are redacted")
    ok("Next: run the gate." in full and "**Assistant:** Next: run the gate." in full,
       "the turn's final answer is kept as the answer")
    ok("[rejected]" in full and "**User refused:** Bash: git push\n" not in full
       and full.count("**User refused:**") == 2,
       "git's [rejected] is an error, not a user refusal")
    ok(("Never force-push; push to release-2026-10, tag v3.4.1 and quote the CHANGELOG line exactly. " * 3).strip() in full,
       "a refusal's words are kept whole as the user's")
    ok(full.count("**Assistant:** Done.") == 2, "a short answer repeated in a later turn is kept for that turn")
    ok(not any(s in full for s in ("3f1c0a9b8c7d6e5f6666", "Sup3rS3cretPw", "hunter2hunter2",
                                   "abcdefghijklmnopqrstuvwx", "QQQQQQQQQQ")),
       "KEY=, PASSWORD=, JSON passwords, Bearer tokens and a key at the cut edge are all redacted")
    # refuter 7-9: counts survive, more secret shapes go, a key at a 200-char command cut too
    ok(kd.redact('max_tokens=200000 "cache_read_input_tokens": 123456 pwd: D:/Projects/x token: 4096')
       == 'max_tokens=200000 "cache_read_input_tokens": 123456 pwd: D:/Projects/x token: 4096',
       "token counts and paths are not secrets: kept as written")
    ok(all(s not in kd.redact(t) for s, t in (
        ("Hunter2Secret", "postgres://admin:Hunter2Secret@db.local:5432/x"),
        ("b3BlbnNzaC1rZXk", "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXk\n-----END OPENSSH PRIVATE KEY-----"),
        ("YWRtaW46aHVudGVyMg", "Authorization: Basic YWRtaW46aHVudGVyMg=="),
        ("abc12", "PASSWORD=abc12"),
        ("12345678", "PASSWORD=12345678"),  # verifier N1: digits only is still a password
        ("99887766", "api_key=99887766"))),
       "DB URL passwords, private keys, Basic auth and short passwords are redacted")
    ok("ghp_ABC" not in kd.tool_line("Bash", {"command": "x" * 190 + " ghp_ABCDEFGHIJKLMNOPQRSTUVWX1234"}),
       "a key straddling the 200-char command cut leaves no prefix behind")
    lean = kd.render([dict(t, outs={}) for t in turns], {}, 0)
    ok("RESULT: 41/41 passed" not in lean and LONG in lean and len(lean) < len(full),
       "without the output excerpts the words all remain")

    # The cap: old turns lose detail, user words and the newest TAIL turns never do.
    many = os.path.join(tmp, "many.jsonl")
    with open(many, "w", encoding="utf-8") as f:
        for i in range(20):
            f.write(json.dumps(user(f"instruction number {i}: keep exact")) + "\n")
            f.write(json.dumps(asst(text(f"narration {i} " + "n" * 400), tool(f"b{i}", "Bash", {"command": f"cmd{i}"}))) + "\n")
            f.write(json.dumps(result(f"b{i}", "o" * 2000)) + "\n")
            f.write(json.dumps(asst(text(f"answer {i} " + "a" * 3000))) + "\n")
    t2 = kd.extract(many)
    capped = kd.render(t2, {}, 3000)
    ok(all(f"instruction number {i}: keep exact" in capped for i in range(20)),
       "under a tight cap every user message survives")
    ok(f"answer 19 {'a' * 3000}" in capped and "narration 0" not in capped,
       "the newest turns stay whole while the oldest lose narration")
    ok("exceeded" in capped.splitlines()[3], "a cap the never-cut parts exceed is said in the header")
    ok(kd.cap_tokens(45, 1_000_000) == 100_000 and kd.cap_tokens(65, 1_000_000) == 180_000
       and kd.cap_tokens(75, 1_000_000) == 250_000 and kd.cap_tokens(85, 1_000_000) == 300_000,
       "the user's table: 45% 10%, 60-70% 18%, 70-80% 25%, 80%+ 30% of the window")

    # write(): the folder ignores itself; nothing is pruned here (kit_chain prunes, 7 days after
    # the bucket closes); a bucket that is gone is never created again.
    bucket = os.path.join(tmp, "proj", ".claude", "scratch", "alpha")
    os.makedirs(bucket)
    out_dir = os.path.join(bucket, "digests")
    n = kd.write(path, os.path.join(out_dir, "s1.md"), {"session": "s1"}, 0)
    gi = open(os.path.join(out_dir, ".gitignore"), encoding="utf-8").read()
    ok(n > 0 and os.path.isfile(os.path.join(out_dir, "s1.md")) and gi.strip().endswith("*"),
       "write() makes the digest and a `*` .gitignore beside it")
    for k in range(7):
        kd.write(path, os.path.join(out_dir, f"s{k + 2}.md"), {"session": f"s{k + 2}"}, 0)
    left = [f for f in os.listdir(out_dir) if f.endswith(".md")]
    ok(len(left) == 8 and not hasattr(kd, "KEEP") and not hasattr(kd, "prune"),
       "8 writes keep 8 digests: no count cap deletes session 1 of a long task")
    ok(not [f for f in os.listdir(out_dir) if f.endswith(".tmp")],
       "no tmp file is left behind")
    gone = os.path.join(tmp, "proj", ".claude", "scratch", "moved-away", "digests")
    ok(kd.write(path, os.path.join(gone, "s1.md"), {}, 0) == -1 and not os.path.exists(os.path.dirname(gone)),
       "a bucket that was moved or renamed is not created again by a late write")
    part = [dict(t) for t in turns[:2]]
    kd.write(path, os.path.join(out_dir, "cut.md"), {"session": "cut"}, 0, turns=part)
    cut = open(os.path.join(out_dir, "cut.md"), encoding="utf-8").read()
    ok("please also check B2" in cut and "last question: what next?" not in cut,
       "write(turns=...) writes only the turns it is given")
    ok(kd.local_time("2026-10-07T08:15:00Z") == time.strftime(
        "%H:%M", time.localtime(1791360900)) and kd.local_time("garbage-not-a-time") == "-a-ti",
       "turn times are shown in local time; an unparsable stamp falls back to its raw slice")
    ok(kd.extract(os.path.join(tmp, "nope.jsonl")) == [] and kd.write(
        os.path.join(tmp, "nope.jsonl"), os.path.join(out_dir, "z.md"), {}, 0) == -1,
       "a missing transcript -> nothing extracted, nothing written")

    # 2026-10-10 (bucket handoff-timeline): an error names its call; an MCP tool shows its command;
    # a task notification is the harness's, not the user's; an async launch receipt is noise.
    notes = os.path.join(tmp, "notes.jsonl")
    with open(notes, "w", encoding="utf-8") as f:
        for ln in [
            user("check the laptop python"),
            asst(tool("e1", "Bash", {"command": "python3 - <<'PY'\nprint(1)\nPY"})),
            result("e1", "Exit code 49\nPython was not found; run without arguments to install from the Microsoft Store", err=True),
            asst(tool("e2", "mcp__ssh-mpc-server__execute-command", {"cmdString": "df -h / | tail -1"})),
            result("e2", "/dev/sda1 100G 88G 12G 89% /"),
            asst(tool("e3", "Agent", {"subagent_type": "researcher", "description": "dig", "run_in_background": True})),
            result("e3", "Async agent launched successfully. agentId: abc (internal ID - do not mention to user.)"),
            user("<task-notification>\n<task-id>abc</task-id>\n<status>completed</status>\n<summary>Agent \"dig\" "
                 "finished</summary>\n<result>FOUND: the cap is 12 GB free</result>\n</task-notification>"),
            asst(text("Both done.")),
            # most notices arrive queued, while a turn runs (8 of 8 in one real session)
            {"type": "attachment", "attachment": {"type": "queued_command", "prompt":
                "<task-notification>\n<task-id>b9</task-id>\n<summary>Background command \"gate\" completed "
                "(exit code 0)</summary>\n</task-notification>"}},
        ]:
            f.write(json.dumps(ln) + "\n")
    nt = kd.render(kd.extract(notes), {"session": "n"}, 0)
    ok("**Error:** Bash: python3 - <<'PY' print(1) PY -> Exit code 49 Python was not found" in nt,
       "an error line names the call that failed (python3 - never left to a reader's guess)")
    ok("- mcp__ssh-mpc-server__execute-command df -h / | tail -1" in nt,
       "an MCP tool's command (cmdString) is shown, not just its name")
    ok("**Background task done (line 8; the harness, not the user):**\nAgent \"dig\" finished\nFOUND: the cap is 12 GB free"
       in nt and "<task-notification>" not in nt and "1 user messages" in nt
       and "**Background task done (line 10; the harness, not the user):**\nBackground command \"gate\" completed" in nt,
       "a task notification, typed or queued, is the harness's: summary and result kept, never the user's words")
    ok("Async agent launched" not in nt and "do not mention" not in nt,
       "an async agent's launch receipt is left out (its report comes as the notification)")
    ok(kd.harness_text("  <task-notification>x") and kd.harness_text("[Request interrupted by user]")
       and not kd.harness_text("please check <task-notification> handling"),
       "harness_text: a notice or an interrupt marker at the start, never a user line that mentions one")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

fails = sum(1 for good, _ in cases if not good)
for good, label in cases:
    print(f"{'ok ' if good else 'BAD'} {label}")
print(f"\n{len(cases) - fails}/{len(cases)} passed")
sys.exit(1 if fails else 0)
