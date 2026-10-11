"""SubagentStop hook: file every finished subagent's final message, so none is lost.

The report goes where the task's rules want it: when the agent's first prompt names a brief of
this project, `.claude/scratch/<slug>/briefs/<NN>-*.md`, the message becomes that bucket's
`reports/<NN>-<agent_type>.md` - unless a report for <NN> is already there (a builder writes
its own). Measured 2026-10-11: 44 of 156 briefs had no report, the hand-written copy forgotten
(bucket kit-optimize-pass D001). Any other agent's message goes to
<root>/.claude/scratch/_inbox/<UTC>-<agent_type>-<id8>.md, and an _inbox file older than
INBOX_DAYS is pruned: nothing ever read it back. <root> is the first of CLAUDE_PROJECT_DIR and
the payload's `cwd` that has a .claude/scratch/ dir. The message is the payload's
`last_assistant_message`; only the agent transcript's first prompt is read. The hook is global,
so a project with no .claude/scratch/ is left completely alone, and so is one whose git would
show the file. Prints nothing in any path: stdout from a hook can reach the model. Any crash =
write nothing (fail open, dev tool).
Self-check: python kit-subagent-report_test.py
"""
import os
import sys

# The hook's own folder, explicitly: under PYTHONSAFEPATH=1 (or python -P / -I) the script dir
# is not on sys.path, the import fails and the hook exits 1 - which fails open (refuter-02).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit_off import kit_off  # noqa: E402

if __name__ == "__main__" and kit_off():
    sys.exit(0)  # off here, the default: out before the imports below (kit-default-off-optimize D003)

import datetime  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402

UNSAFE = re.compile(r"[^A-Za-z0-9._-]")
# A brief path in the agent's prompt, absolute or relative, either slash.
BRIEF = re.compile(r"\.claude[\\/]+scratch[\\/]+([A-Za-z0-9][A-Za-z0-9._-]*)[\\/]+briefs[\\/]+"
                   r"((\d{2,3})-[A-Za-z0-9._-]+\.md)")
INBOX_DAYS = 30
PROMPT_LINES = 40  # the first prompt is among the transcript's first lines


def first_prompt(transcript):
    """The text of the agent transcript's first user message, or ""."""
    try:
        with open(transcript, encoding="utf-8", errors="replace") as f:
            for _, line in zip(range(PROMPT_LINES), f):
                if '"user"' not in line:
                    continue
                obj = json.loads(line)
                if not isinstance(obj, dict) or obj.get("type") != "user":
                    continue
                c = (obj.get("message") or {}).get("content")
                if isinstance(c, list):
                    c = " ".join(b.get("text", "") for b in c if isinstance(b, dict))
                if isinstance(c, str) and c.strip():
                    return c
    except (OSError, TypeError, ValueError):
        pass
    return ""


def report_path(scratch, prompt, agent_type):
    """<bucket>/reports/<NN>-<agent_type>.md for the first brief of THIS project the prompt names,
    or None: no brief, a brief that is not there, or a report for <NN> already written."""
    for m in BRIEF.finditer(prompt):
        slug, name, nn = m.group(1), m.group(2), m.group(3)
        bucket = os.path.join(scratch, slug)
        if not os.path.isfile(os.path.join(bucket, "briefs", name)) or os.path.islink(bucket):
            continue
        reports = os.path.join(bucket, "reports")
        if os.path.isdir(reports) and any(n.startswith(nn + "-") for n in os.listdir(reports)):
            return None
        return os.path.join(reports, f"{nn}-{agent_type}.md")
    return None


def prune(inbox):
    """Drop _inbox files older than INBOX_DAYS: copies of agent messages nothing reads back."""
    import time
    cut = time.time() - INBOX_DAYS * 86400
    for n in os.listdir(inbox):
        p = os.path.join(inbox, n)
        try:
            if n.endswith(".md") and os.path.isfile(p) and os.path.getmtime(p) < cut:
                os.remove(p)
        except OSError:
            pass


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
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    agent_type = clean(data.get("agent_type"))
    agent_id = clean(data.get("agent_id"))
    target = report_path(scratch, first_prompt(str(data.get("agent_transcript_path") or "")), agent_type)
    inbox = os.path.join(scratch, "_inbox")
    if not target:
        os.makedirs(inbox, exist_ok=True)
        prune(inbox)
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
    if target:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        try:
            with open(target, "x", encoding="utf-8") as f:  # `x`: a report written meanwhile wins
                f.write("<!-- filed by the kit from the agent's final message (SubagentStop) -->\n"
                        + header + body)
            return
        except FileExistsError:
            os.makedirs(inbox, exist_ok=True)
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
