"""Replay every shell command in the user's transcripts that names a bucket note through the OLD
shell-write test (any `>`, tee, Set-Content... anywhere in the command = every note in it was
written) and the NEW per-path one (kit_index.shell_notes), and show where they disagree.

    python bench/handoff/note_writes_scan.py [--samples 12]

Bucket handoff-timeline, 2026-10-10: the old test filed a session under a closed task because
`2>/dev/null` sat beside a read of that task's STATE.md.
"""
import glob
import json
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "core", "hooks"))
import kit_index as ki  # noqa: E402

OLD_WRITE = re.compile(r">|\btee\b|Set-Content|Out-File|Add-Content|write_text|\.write\(|"
                       r"open\([^)]*['\"][wa]", re.IGNORECASE)
OLD_NOTE = re.compile(r"(?:^|[/\\\s\"'=])\.claude[/\\]scratch[/\\]([^/\\\s\"'*?<>|]+)[/\\]"
                      r"(STATE|FINDINGS|DECISIONS)\.md", re.IGNORECASE)
# `cd <...>/.claude/scratch/<slug> && ... >> FINDINGS.md`: a bare note name after a cd into a bucket
CD_BUCKET = re.compile(r"\bcd\s+[\"']?[^\s\"';&|]*\.claude[/\\]scratch[/\\]([^/\\\s\"'*?<>|;&]+)[/\\]?[\"']?\s*(?:&&|;)")
BARE_WRITE = re.compile(r"(?:>>?|\btee\s+(?:-a\s+)?)\s*[\"']?(?:\./)?(STATE|FINDINGS|DECISIONS)\.md\b")


def commands():
    for path in glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl")):
        try:
            f = open(path, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with f:
            for line in f:
                if '"tool_use"' not in line or "scratch" not in line:
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(o, dict) or o.get("isSidechain") or o.get("type") != "assistant":
                    continue
                for b in (o.get("message") or {}).get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in ("Bash", "PowerShell"):
                        cmd = (b.get("input") or {}).get("command")
                        if isinstance(cmd, str) and "scratch" in cmd:
                            yield os.path.basename(os.path.dirname(path)), cmd


def main(argv):
    samples = int(argv[argv.index("--samples") + 1]) if "--samples" in argv else 12
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    verdicts, ex, cd = Counter(), {}, Counter()
    n_cmd = 0
    for proj, cmd in commands():
        n_cmd += 1
        old_w = bool(OLD_WRITE.search(cmd))
        old = [(m.group(1), m.group(2).upper(), old_w) for m in OLD_NOTE.finditer(cmd)]
        new = ki.shell_notes(cmd)
        if old or new:
            o, n = Counter(old), Counter(new)
            for key in set(o) | set(n):
                k = ("W" if key[2] else "R")
                # count each note mention once per side
                for _ in range(o[key]):
                    verdicts["old " + k] += 1
                for _ in range(n[key]):
                    verdicts["new " + k] += 1
            old_set = {(s, t): w for s, t, w in old}
            new_set = {(s, t): w for s, t, w in new}
            for st in set(old_set) | set(new_set):
                pair = (("W" if old_set.get(st) else "R") if st in old_set else "-") + "->" + \
                       (("W" if new_set.get(st) else "R") if st in new_set else "-")
                verdicts[pair] += 1
                ex.setdefault(pair, []).append((proj, st, cmd))
        m = CD_BUCKET.search(cmd)
        if m and BARE_WRITE.search(cmd[m.end():]):
            cd["cd into a bucket, then write a bare note name"] += 1
            ex.setdefault("cd", []).append((proj, (m.group(1), BARE_WRITE.search(cmd[m.end():]).group(1)), cmd))
    print(f"{n_cmd} shell commands mention scratch")
    for k in sorted(verdicts):
        print(f"  {k:8} {verdicts[k]}")
    for k, v in cd.items():
        print(f"  {k}: {v}")
    for pair in ("W->R", "R->W", "-->R", "-->W", "W->-", "R->-", "cd"):
        rows = ex.get(pair, [])
        if not rows:
            continue
        print(f"\n=== {pair}: {len(rows)} (showing {min(samples, len(rows))})")
        for proj, st, cmd in rows[:samples]:
            print(f"--- {proj} {st}\n{cmd[:700]}")


if __name__ == "__main__":
    main(sys.argv[1:])
