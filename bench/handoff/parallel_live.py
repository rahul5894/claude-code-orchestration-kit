"""Live test: parallel windows that each hand off, /clear and /continue (bucket
parallel-window-resume). Drives the real Claude Code binary headless (stream-json), with
whatever kit is installed in ~/.claude - run it before and after an install to compare.

Window A writes bucket alpha's STATE.md, then window B writes beta's (beta = the newest
handoff). Each STATE.md's next action is "reply with the word <SLUG>-OK". Then A runs /clear +
/continue, then B does, both still open; then a third window starts and runs /continue. Right:
A says ALPHA-OK, B says BETA-OK, C takes neither unasked. The old kit sent everyone to beta.

    python bench/handoff/parallel_live.py [--model haiku] [--keep]
Costs a few cents with Haiku. Writes only into a temp project dir.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import queue

CLAUDE = os.environ.get("CLAUDE_CODE_EXECPATH") or shutil.which("claude") or "claude"
# The caller's own session ids must not leak into the windows under test.
DROP = ("CLAUDE_PROJECT_DIR", "CLAUDE_PID", "CLAUDE_CODE_SESSION_ID", "CLAUDECODE",
        "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SSE_PORT")


def project():
    root = tempfile.mkdtemp(prefix="kit-pw-")
    with open(os.path.join(root, "CLAUDE.md"), "w", encoding="utf-8") as f:
        f.write("# test project\n| **FAST GATE — agents run this** | `python -c pass` | 0.1 s |\n")
    os.makedirs(os.path.join(root, ".claude", "scratch"))
    with open(os.path.join(root, ".claude", "scratch", "INDEX.md"), "w", encoding="utf-8") as f:
        f.write("# Task index\n| slug | status | updated | next action |\n|---|---|---|---|\n"
                # The word sits only in STATE.md: a window that quotes the INDEX resumed nothing.
                "| alpha | OPEN | 2026-10-09 | see STATE.md |\n| beta | OPEN | 2026-10-09 | see STATE.md |\n")
    for slug in ("alpha", "beta"):
        os.makedirs(os.path.join(root, ".claude", "scratch", slug))
    subprocess.run(["git", "init", "-q"], cwd=root)
    subprocess.run(["git", "add", "-A"], cwd=root)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"], cwd=root)
    return root


class Window:
    def __init__(self, name, root, model):
        env = {k: v for k, v in os.environ.items() if k not in DROP}
        self.name = name
        self.p = subprocess.Popen(
            [CLAUDE, "-p", "--model", model, "--input-format", "stream-json", "--output-format",
             "stream-json", "--verbose", "--permission-mode", "bypassPermissions"],
            cwd=root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.q = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        self.notes = []

    def _read(self):
        for raw in self.p.stdout:
            try:
                self.q.put(json.loads(raw.decode("utf-8", "replace")))
            except ValueError:
                pass

    def say(self, text, timeout=300):
        """Send one user message; return the turn's final result text."""
        msg = {"type": "user", "message": {"role": "user", "content": text}}
        self.p.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
        self.p.stdin.flush()
        while True:
            o = self.q.get(timeout=timeout)
            if o.get("type") == "system" and o.get("subtype") == "hook_response":
                out = str(o.get("output") or o.get("stdout") or "")
                if "Open task(s)" in out or "this window" in out:
                    self.notes.append(out[:600])
            if o.get("type") == "result":
                return str(o.get("result") or "")

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=60)
        except Exception:
            self.p.kill()


def write_state(slug):
    return (f"Use the Write tool to create the file .claude/scratch/{slug}/STATE.md with exactly this "
            f"content, then reply only DONE:\n# STATE - {slug}\nUpdated: 2026-10-09   Status: OPEN\n"
            f"## Objective\ntest task {slug}\n## Next action\nReply with exactly the word "
            f"{slug.upper()}-OK and nothing else.\n")


def verdict(text):
    hits = [w for w in ("ALPHA-OK", "BETA-OK") if w in text]
    return hits[0] if len(hits) == 1 else ("BOTH" if hits else "neither")


def main():
    model = sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv else "haiku"
    root = project()
    a, b = Window("A", root, model), Window("B", root, model)
    rows = []
    try:
        a.say(write_state("alpha"))
        b.say(write_state("beta"))
        a.say("/clear")
        ra = a.say("/continue")
        b.say("/clear")
        rb = b.say("/continue")
        c = Window("C", root, model)
        try:
            rc = c.say("/continue")
        finally:
            c.close()
        rows = [("A (worked on alpha)", "ALPHA-OK", verdict(ra), ra),
                ("B (worked on beta)", "BETA-OK", verdict(rb), rb),
                ("C (new window, both busy)", "neither", verdict(rc), rc)]
    finally:
        a.close()
        b.close()
    right = 0
    for who, want, got, text in rows:
        right += got == want
        print(f"{who:28} want {want:9} got {got:9} | {' '.join(text.split())[:160]}")
    print(f"\nright: {right}/{len(rows)}  project: {root}")
    if "--keep" not in sys.argv:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
