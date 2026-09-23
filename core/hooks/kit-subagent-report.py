"""SubagentStop hook: file every finished subagent's final message, so none is lost.

Writes one <root>/.claude/scratch/_inbox/<UTC>-<agent_type>-<id8>.md per subagent from the
payload's `last_assistant_message`, where <root> is the first of CLAUDE_PROJECT_DIR and the
payload's `cwd` that has a .claude/scratch/ dir; the transcript is never parsed. The hook is global, so
a project with no .claude/scratch/ is left completely alone, and so is one whose git would
show the file. Prints nothing in any path: stdout from a hook can reach the model. Any
crash = write nothing (fail open, dev tool).
Self-check: python kit-subagent-report_test.py
"""
import datetime
import json
import os
import re
import subprocess
import sys

# The hook's own folder, explicitly: under PYTHONSAFEPATH=1 (or python -P / -I) the script dir
# is not on sys.path, the import fails and the hook exits 1 - which fails open (refuter-02).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit_off import kit_off  # noqa: E402

UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def git_would_see(scratch):
    """True when this scratch dir is inside a git repo that does NOT ignore it.

    Measured 2026-09-19: of five projects on this machine with a `.claude/scratch/`, two do
    not ignore it. There, a file per finished subagent shows up in `git status` - which
    discards a read-only reviewer's verdict under the kit's own rule, and invites
    `git add .` to commit agent output. One `git check-ignore`: 0 = ignored, 1 = not
    ignored, anything else (no git, not a repo, timeout) = nothing to dirty, keep writing.
    """
    try:
        p = subprocess.run(["git", "-C", scratch, "check-ignore", "-q", scratch],
                           capture_output=True, timeout=5)
    except Exception:
        return False
    return p.returncode == 1


def clean(value):
    """Filename-safe field: `..`, separators and spaces all become `-`, empty -> unknown."""
    return UNSAFE.sub("-", str(value or "")) or "unknown"


def main():
    if kit_off():
        return
    try:
        # Explicit UTF-8: sys.stdin uses the locale codec (cp1252 on Windows) and the payload
        # comes from JSON.stringify, which leaves non-ASCII raw. Decoding it wrong mangles
        # every arrow and accent in the report.
        data = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except Exception:
        return
    # Payload cwd follows the shell's `cd`: after `cd .claude/scratch` (2026-09-23) two reports
    # were never filed. CLAUDE_PROJECT_DIR is the launch root and does not move; payload cwd is
    # the fallback for a session launched in a parent dir, then cd'd into the repo (D011).
    # Every project on the machine fires this. Only a repo that already keeps task buckets
    # gets written to; anywhere else the hook is a no-op.
    scratch = next((s for s in (os.path.join(r, ".claude", "scratch")
                                for r in (os.environ.get("CLAUDE_PROJECT_DIR"), data.get("cwd")) if r)
                    if os.path.isdir(s)), None)
    if not scratch or kit_off(os.path.dirname(os.path.dirname(scratch))):
        return
    if git_would_see(scratch):
        return
    inbox = os.path.join(scratch, "_inbox")
    os.makedirs(inbox, exist_ok=True)

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    agent_type = clean(data.get("agent_type"))
    agent_id = clean(data.get("agent_id"))
    raw = data.get("last_assistant_message")
    # Anything but a str is a payload shape change (content blocks, say). str() would turn a
    # list into a non-empty repr and present it as the verbatim report, so it counts as
    # missing and the repr goes in the file where it can be seen.
    body = raw if isinstance(raw, str) else ""
    if not body.strip():
        # v2.1.271+: an agent holding SubagentHandback delivers its report through that tool
        # and leaves only closing text here. No kit agent grants it, so an empty body means
        # something changed - it has to be loud in the file, never a silent blank.
        body = ("MISSING REPORT — no final message; transcript: "
                + str(data.get("agent_transcript_path") or "unknown"))
        if raw is not None and not isinstance(raw, str):
            body += f"\n\nlast_assistant_message was: {raw!r}"
    header = f"agent_type: {agent_type}\nagent_id: {agent_id}\nutc: {stamp}\n\n"
    # Two subagents of one type can finish inside the same second, and agent_id is `unknown`
    # when absent - same name, second report silently wins. `x` mode claims the first free
    # suffix instead, and is atomic against the other hook process doing the same.
    base = os.path.join(inbox, f"{stamp}-{agent_type}-{agent_id[:8]}")
    n = 1
    while True:
        try:
            with open(base + (".md" if n == 1 else f"-{n}.md"), "x", encoding="utf-8") as f:
                f.write(header + body)
            return
        except FileExistsError:
            n += 1


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        pass
