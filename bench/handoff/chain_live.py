"""Live test: one task carried across several /clears while a second task runs in a parallel
window, one window killed (bucket handoff-timeline). Drives the real Claude Code binary headless
(stream-json) with ONLY the hooks under test: `--setting-sources project --settings <file>`, so
the globally installed kit does not run beside them.

Arms:  new = this checkout's core/hooks;  old = core/hooks at a git ref (default 47538bf, the
kit before the timeline). Same script, same prompts, same checks.

Window A, task alpha: S1 writes STATE.md (marker ALPHA-S1) + a FINDINGS line, /clear;
S2 rewrites STATE.md (ALPHA-S2), /clear; S3 reads it and answers; window closed (stdin EOF).
Window B, task beta, at the same time: S1 writes (BETA-S1), /clear; S2 rewrites (BETA-S2) and is
KILLED - no SessionEnd. After 65 s a third window starts and says hi (its SessionStart repairs).
Every session stays far under 45%, so the old kit's Stop hook never asks for anything.

Checked per arm: alpha SESSIONS.md lists S1, S2, S3 in order; every session has its verbatim
digest and STATE snapshot; S1's snapshot still says ALPHA-S1 after S2 rewrote STATE.md; beta's
records hold no alpha text; the killed session ends up with an end and a digest.

    python bench/handoff/chain_live.py [--arm new|old|both] [--ref 47538bf] [--model haiku] [--keep]
Costs a few cents with Haiku per arm. Writes only into temp dirs (and Claude Code's own
transcripts of these temp projects under ~/.claude/projects).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import queue

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
CLAUDE = os.environ.get("CLAUDE_CODE_EXECPATH") or shutil.which("claude") or "claude"
DROP = ("CLAUDE_PROJECT_DIR", "CLAUDE_PID", "CLAUDE_CODE_SESSION_ID", "CLAUDECODE",
        "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SSE_PORT")
HOOK_FILES = ("kit-session-start.py", "kit-context.py", "kit-session-end.py", "kit_off.py",
              "kit_index.py", "kit_digest.py", "kit_chain.py")


def hooks_dir(arm, ref):
    if arm == "new":
        return os.path.join(REPO, "core", "hooks")
    d = tempfile.mkdtemp(prefix="kit-oldhooks-")
    for f in HOOK_FILES:
        r = subprocess.run(["git", "show", f"{ref}:core/hooks/{f}"], cwd=REPO, capture_output=True)
        if r.returncode == 0:
            with open(os.path.join(d, f), "wb") as fh:
                fh.write(r.stdout)
    return d


def settings(hdir):
    py = sys.executable.replace("\\", "/")
    def h(f):
        return [{"type": "command", "command": f"{py} {hdir.replace(chr(92), '/')}/{f}", "timeout": 5}]
    hooks = {"SessionStart": [{"matcher": "startup|resume|clear|compact|fork", "hooks": h("kit-session-start.py")}],
             "Stop": [{"hooks": h("kit-context.py")}]}
    if os.path.isfile(os.path.join(hdir, "kit-session-end.py")):
        hooks["SessionEnd"] = [{"hooks": h("kit-session-end.py")}]
    path = os.path.join(tempfile.mkdtemp(prefix="kit-chainset-"), "settings.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"hooks": hooks}, f)
    return path


def project():
    root = tempfile.mkdtemp(prefix="kit-chain-")
    with open(os.path.join(root, "CLAUDE.md"), "w", encoding="utf-8") as f:
        f.write("# test project\n| **FAST GATE — agents run this** | `python -c pass` | 0.1 s |\n")
    scratch = os.path.join(root, ".claude", "scratch")
    os.makedirs(scratch)
    with open(os.path.join(scratch, "INDEX.md"), "w", encoding="utf-8") as f:
        f.write("# Task index\n| slug | status | updated | next action |\n|---|---|---|---|\n"
                "| alpha | OPEN | 2026-10-09 | see STATE.md |\n| beta | OPEN | 2026-10-09 | see STATE.md |\n")
    for slug in ("alpha", "beta"):
        os.makedirs(os.path.join(scratch, slug))
        for name in ("FINDINGS", "DECISIONS"):
            with open(os.path.join(scratch, slug, f"{name}.md"), "w", encoding="utf-8") as f:
                f.write(f"# {name} — {slug}\n<!-- Append-only. -->\n<!-- Each: ... -->\n")
    subprocess.run(["git", "init", "-q"], cwd=root)
    return root


class Window:
    def __init__(self, name, root, model, setfile):
        env = {k: v for k, v in os.environ.items() if k not in DROP}
        self.name = name
        self.p = subprocess.Popen(
            [CLAUDE, "-p", "--model", model, "--input-format", "stream-json", "--output-format",
             "stream-json", "--verbose", "--permission-mode", "bypassPermissions",
             "--setting-sources", "project", "--settings", setfile],
            cwd=root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.q = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        self.sids = []

    def _read(self):
        for raw in self.p.stdout:
            try:
                self.q.put(json.loads(raw.decode("utf-8", "replace")))
            except ValueError:
                pass

    def say(self, text, timeout=300):
        msg = {"type": "user", "message": {"role": "user", "content": text}}
        self.p.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
        self.p.stdin.flush()
        while True:
            o = self.q.get(timeout=timeout)
            sid = o.get("session_id")
            if sid and (not self.sids or self.sids[-1] != sid):
                self.sids.append(sid)
            if o.get("type") == "result":
                return str(o.get("result") or "")

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=90)
        except Exception:
            self.p.kill()

    def kill(self):
        self.p.kill()
        self.p.wait()


def write_state(slug, marker, nxt):
    return (f"Use the Write tool to create the file .claude/scratch/{slug}/STATE.md with exactly this "
            f"content, then reply only DONE:\n# STATE - {slug}\nUpdated: 2026-10-09   Status: OPEN\n"
            f"## Objective\ntest task {slug} {marker}\n## Next action\n{nxt}\n")


def append_finding(slug, text):
    return (f"Use the Bash tool to append exactly this line to .claude/scratch/{slug}/FINDINGS.md: "
            f"`- 2026-10-09 [fact] {text}` (use >> so nothing else changes), then reply only DONE.")


def records(root, slug):
    d = os.path.join(root, ".claude", "scratch", slug, "digests")
    files = sorted(os.listdir(d)) if os.path.isdir(d) else []
    view = os.path.join(root, ".claude", "scratch", slug, "SESSIONS.md")
    text = open(view, encoding="utf-8").read() if os.path.isfile(view) else ""
    entries = {}
    for f in files:
        if f.endswith(".json"):
            try:
                entries[f[:-5]] = json.load(open(os.path.join(d, f), encoding="utf-8"))
            except ValueError:
                pass
    return d, files, text, entries


def read(path):
    try:
        return open(path, encoding="utf-8").read()
    except OSError:
        return ""


def run_arm(arm, ref, model, keep):
    hdir = hooks_dir(arm, ref)
    setfile = settings(hdir)
    root = project()
    print(f"\n=== arm {arm}: hooks {hdir}\n    project {root}")
    a, b = Window("A", root, model, setfile), Window("B", root, model, setfile)
    t0 = time.time()
    try:
        a.say(write_state("alpha", "ALPHA-S1", "step 2 of alpha"))
        b.say(write_state("beta", "BETA-S1", "step 2 of beta"))
        a.say(append_finding("alpha", "alpha one"))
        a.say("/clear")
        b.say("/clear")
        a.say("Read .claude/scratch/alpha/STATE.md. " + write_state("alpha", "ALPHA-S2", "step 3 of alpha"))
        b.say("Read .claude/scratch/beta/STATE.md. " + write_state("beta", "BETA-S2", "step 3 of beta"))
        a.say("/clear")
        ans = a.say("Read .claude/scratch/alpha/STATE.md and reply with its Next action line only.")
        time.sleep(2)
        b.kill()   # no SessionEnd for beta's S2
        a.close()  # SessionEnd for alpha's S3
        print(f"    A sessions {a.sids}\n    B sessions {b.sids}\n    S3 answered: {ans.strip()[:80]!r}")
        print("    waiting 65 s so the killed session's entry is past the repair's 60 s guard ...")
        time.sleep(65)
        c = Window("C", root, model, setfile)
        try:
            c.say("hi - reply only OK")
        finally:
            c.close()
    finally:
        for w in (a, b):
            try:
                w.p.kill()
            except Exception:
                pass
    elapsed = time.time() - t0

    rows = []
    d, files, view, entries = records(root, "alpha")
    a_sids = [s for s in a.sids if s]
    rows.append(("alpha SESSIONS.md lists S1, S2, S3 in order",
                 bool(view) and all(f"## S{i + 1} · {s}" in view for i, s in enumerate(a_sids[:3]))
                 and len(a_sids) >= 3))
    rows.append(("alpha: a verbatim digest for every session",
                 all(f"{s}.md" in files for s in a_sids[:3])))
    rows.append(("alpha: a STATE snapshot for S1 and S2",
                 all(f"{s}.state.md" in files for s in a_sids[:2])))
    rows.append(("alpha S1's snapshot still says ALPHA-S1 after S2 rewrote STATE.md",
                 "ALPHA-S1" in read(os.path.join(d, f"{a_sids[0]}.state.md")) if a_sids else False))
    rows.append(("alpha: STATE.md now says ALPHA-S2", "ALPHA-S2" in read(os.path.join(root, ".claude", "scratch", "alpha", "STATE.md"))))
    rows.append(("alpha S1's FINDINGS line is attributed to S1",
                 "FINDINGS L4-4" in view.split("## S2")[0] if view else False))
    rows.append(("alpha S3 (window closed) has an end", bool(a_sids[2:3]) and bool((entries.get(a_sids[2]) or {}).get("end"))))
    bd, bfiles, bview, bentries = records(root, "beta")
    b_sids = [s for s in b.sids if s]
    btext = bview + "".join(read(os.path.join(bd, f)) for f in bfiles if f.endswith(".md"))
    rows.append(("beta: S1 and S2 both listed", bool(bview) and all(s in bview for s in b_sids[:2]) and len(b_sids) >= 2))
    rows.append(("beta's records hold no alpha text", bool(btext) and "ALPHA-S" not in btext and "alpha one" not in btext))
    rows.append(("beta S2 (window KILLED) repaired at the next start: end + digest",
                 bool(b_sids[1:2]) and bool((bentries.get(b_sids[1]) or {}).get("end")) and f"{b_sids[1]}.md" in bfiles))
    right = sum(1 for _, good in rows if good)
    for label, good in rows:
        print(f"    {'PASS' if good else 'FAIL'}  {label}")
    print(f"    arm {arm}: {right}/{len(rows)} in {elapsed:.0f} s")
    if not keep:
        shutil.rmtree(root, ignore_errors=True)
    return right, len(rows)


def main():
    arg = sys.argv
    arm = arg[arg.index("--arm") + 1] if "--arm" in arg else "both"
    ref = arg[arg.index("--ref") + 1] if "--ref" in arg else "47538bf"
    model = arg[arg.index("--model") + 1] if "--model" in arg else "haiku"
    out = {}
    for one in (("old", "new") if arm == "both" else (arm,)):
        out[one] = run_arm(one, ref, model, "--keep" in arg)
    print("\nsummary: " + ", ".join(f"{k} {r}/{n}" for k, (r, n) in out.items()))


if __name__ == "__main__":
    main()
