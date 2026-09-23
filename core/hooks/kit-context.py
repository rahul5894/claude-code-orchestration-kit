"""Stop hook: at 45% context, the finished turn hands off and the user is told to /clear.

The user never watches the context meter, and past about half of it the model's grip on a
long task degrades. No hook payload carries context usage (probed on Claude Code 2.1.280), so
it is read from the transcript: input + cache_creation + cache_read tokens of the LAST
main-chain assistant line (a "<synthetic>" line or one whose counts sum to 0 is skipped), over
the window named by the last `model` attachment ("[1m]" in the id or a claude-fable id =
1,000,000, else 200,000; more than 200K used = 1,000,000 whatever the attachment says).

A stop while a background task other than a shell runs is not a finished task and says
nothing. A headless session (CLAUDE_CODE_SESSION_ATTENDED == "0") says nothing either: no
user reads the notice and a block would only spend a turn. The first stop in
each 10-point band from 45% (45, 55, 65...) returns `decision: block` with REASON, which goes
to the model: write the handoff into the open bucket's STATE.md, then tell the user. Every
later qualifying stop only shows NOTICE to the user. The band reached is kept per session in
the temp dir and removed once usage falls under 45% (after a compaction), so the next
crossing blocks again. Transcripts reach tens of MB: only lines containing `"usage"` or
`"modelId"` are parsed.

Exit 0 always. Any crash = silence (fail open, dev tool). Never writes outside the temp dir.
Self-check: python kit-context_test.py
"""
import json
import os
import re
import sys
import tempfile

# The hook's own folder, explicitly: under PYTHONSAFEPATH=1 (or python -P / -I) the script dir
# is not on sys.path, the import fails and the hook exits 1 - which fails open (refuter-02).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit_off import kit_off  # noqa: E402

THRESHOLD = 45
BAND = 10
WINDOW = 200_000
WINDOW_1M = 1_000_000
UNSAFE = re.compile(r"[^A-Za-z0-9._-]")
REASON = ("orchestration-kit: context is at {pct}% ({used}K of {window}K). Hand off now, before "
          "any new work: rewrite the OPEN bucket's STATE.md as the handoff, by the task skill's "
          "STATE rules (<= ~60 lines; Next action exact; under User said, every approval, "
          "preference and open question that lives only in this chat); if no bucket is "
          "open, open one the /task way and write it there - or, if nothing needs to carry over, skip "
          "the bucket and just tell the user to /clear. Then tell the user in one line: "
          "handoff saved - run /clear, then type /continue.")
# Not "saved": REASON lets the model skip the handoff when nothing carries over (code-review).
NOTICE = ("Context {pct}% full - handoff written? Next: /clear, then type /continue.")


def usage(transcript_path):
    """(used tokens, window) from the transcript; unreadable or missing = (0, WINDOW)."""
    used, window = 0, WINDOW
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"usage"' not in line and '"modelId"' not in line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(obj, dict):
                    continue
                if obj.get("type") == "assistant" and obj.get("isSidechain") is False:
                    msg = obj.get("message") or {}
                    u = msg.get("usage")
                    if isinstance(u, dict) and msg.get("model") != "<synthetic>":
                        n = sum(int(u.get(k) or 0) for k in (
                            "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
                        used = n or used
                elif obj.get("type") == "attachment":
                    att = obj.get("attachment") or {}
                    if att.get("type") == "model":
                        model = str((att.get("identity") or {}).get("modelId") or "")
                        # Fable 5.1 is 1M with no marker in its id (sessions measured to 919K).
                        window = (WINDOW_1M if "[1m]" in model or model.startswith("claude-fable")
                                  else WINDOW)
    except OSError:
        return 0, WINDOW
    # Before ~2.1.268 no `model` attachment was written; a session already past 200K can only
    # be a 1M one (measured: such transcripts peaked at 909K).
    return used, (WINDOW_1M if used > WINDOW else window)


def main():
    if kit_off():
        return
    try:
        # Explicit UTF-8, same as the other hooks: sys.stdin uses the locale codec (cp1252 on
        # Windows) while the payload leaves non-ASCII raw.
        data = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except Exception:
        return
    if os.environ.get("CLAUDE_CODE_SESSION_ATTENDED") == "0":
        return
    # A running shell (a dev server, a watcher) does not mean the task is unfinished; anything
    # else, including an entry of unknown shape, does.
    if any(not isinstance(t, dict) or t.get("type") != "shell"
           for t in data.get("background_tasks") or []):
        return
    used, window = usage(data.get("transcript_path") or "")
    pct = used * 100 // window
    marker = os.path.join(tempfile.gettempdir(),
                          "kit-context-" + UNSAFE.sub("_", str(data.get("session_id") or "unknown")))
    if pct < THRESHOLD:
        try:
            os.remove(marker)
        except OSError:
            pass
        return
    band = (pct - THRESHOLD) // BAND
    try:
        with open(marker, encoding="utf-8") as f:
            stored = int(f.read().strip())
    except (OSError, ValueError):
        stored = -1
    # stop_hook_active = this stop follows our own block; blocking again would loop.
    if not data.get("stop_hook_active") and band > stored:
        with open(marker, "w", encoding="utf-8") as f:
            f.write(str(band))
        out = {"decision": "block",
               "reason": REASON.format(pct=pct, used=used // 1000, window=window // 1000)}
    else:
        out = {"systemMessage": NOTICE.format(pct=pct)}
    sys.stdout.write(json.dumps(out))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        pass
