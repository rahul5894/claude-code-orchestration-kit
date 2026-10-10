"""SessionEnd: the ending session's record in every bucket it worked on (bucket handoff-timeline).

Claude Code fires SessionEnd on /clear, on exit, on logout and on an interactive /resume to
another session (reasons clear, prompt_input_exit, logout, resume, other). This calls
kit_chain.finish(): the session's entry in <bucket>/digests/<sid>.json, its STATE snapshot, the
verbatim digest <sid>.md - at ANY context %; before, a digest came only after kit-context's 45%
Stop block, and 12 of 31 sessions that wrote a handoff had none - and SESSIONS.md re-rendered.
A session that touched no bucket goes in the session log, .claude/scratch/_sessions/, when it was a
conversation (bucket kit-records-integration, D009); a headless run writes nothing there.

Budget: Claude Code gives SessionEnd hooks 1.5 s by default; a hook's own `timeout` raises it
(code.claude.com/docs/en/hooks), and install.ps1 registers every kit hook with `timeout = 5`, so
this one has 5 s and stops starting digests after 4. A killed or closed window may fire no
SessionEnd at all: kit-session-start's kit_chain.maintain() finishes such a session later.
Headless sessions are recorded only when they touched a bucket. Claude Code discards
this hook's output; it prints nothing. Exit 0 always; any crash = silence (fail open, dev tool).
Self-check: python kit-session-end_test.py
"""
import os
import sys

# The hook's own folder, explicitly: under PYTHONSAFEPATH=1 (or python -P / -I) the script dir
# is not on sys.path, the import fails and the hook exits 1 - which fails open (refuter-02).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit_off import kit_off  # noqa: E402

if __name__ == "__main__" and kit_off():
    sys.exit(0)  # off here, the default: out before the imports below (kit-default-off-optimize D003)

import json  # noqa: E402
import time  # noqa: E402

from kit_index import drop_read_states, session_root, window  # noqa: E402

BUDGET_S = 4


def main():
    t0 = time.time()
    try:
        # Explicit UTF-8, as in the other hooks: sys.stdin uses the locale codec (cp1252 on
        # Windows) while the payload leaves non-ASCII raw.
        data = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except Exception:
        return
    if not isinstance(data, dict):
        return
    root = session_root(data)  # a session of no task goes in the session log (kit_chain)
    sid = str(data.get("session_id") or "")
    transcript = str(data.get("transcript_path") or "")
    if sid:
        drop_read_states(sid)  # the Stop hook's kept reads (they hold its text); a resume rebuilds them
    if not (root and sid and transcript):
        return
    import kit_chain
    kit_chain.finish(transcript, sid, root, pid=window(), deadline=t0 + BUDGET_S)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
