"""Native /compact of a real session, on a fork: the original transcript is never touched.

Runs `claude -p --resume <sid> --fork-session "/compact"` in the project dir with every hook
off, saves the compaction summary to bench/results/handoff-ab/<name>/compact.md, then deletes
the fork's transcript so the user's /resume list is left as it was.
MSYS_NO_PATHCONV=1: Git Bash turned "/compact" into "C:/Program Files/Git/compact" (F10).

Usage: python compact_fork.py <name> <project dir> <session id>
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "results", "handoff-ab")
EXE = os.environ.get("CLAUDE_CODE_EXECPATH") or "claude"


def main(name, project, sid):
    env = dict(os.environ, MSYS_NO_PATHCONV="1", CLAUDE_CODE_PROMPT_CACHE_TTL="5m")
    r = subprocess.run([EXE, "-p", "--resume", sid, "--fork-session", "--settings",
                        '{"disableAllHooks":true}', "--output-format", "json", "/compact"],
                       cwd=project, env=env, capture_output=True, timeout=1500)
    out = json.loads(r.stdout.decode("utf-8") or "{}")
    fork = out.get("session_id")
    slug = project.replace(":", "-").replace("\\", "-").replace("/", "-")
    path = os.path.join(os.path.expanduser("~/.claude/projects"), slug, f"{fork}.jsonl")
    if not os.path.exists(path):  # the project folder name is a lowercase-drive variant
        cands = [os.path.join(d, f"{fork}.jsonl") for d in
                 [os.path.join(os.path.expanduser("~/.claude/projects"), x)
                  for x in os.listdir(os.path.expanduser("~/.claude/projects"))]]
        path = next((c for c in cands if os.path.exists(c)), path)
    summary, meta = "", {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if o.get("type") == "system" and o.get("subtype") == "compact_boundary":
                meta = o.get("compactMetadata") or {}
            if o.get("isCompactSummary"):
                c = (o.get("message") or {}).get("content")
                summary = c if isinstance(c, str) else "\n".join(
                    b.get("text", "") for b in c or [] if isinstance(b, dict))
    os.remove(path)
    side = os.path.splitext(path)[0]
    if os.path.isdir(side):
        import shutil
        shutil.rmtree(side, ignore_errors=True)
    os.makedirs(os.path.join(OUT, name), exist_ok=True)
    with open(os.path.join(OUT, name, "compact.md"), "w", encoding="utf-8") as f:
        f.write(summary)
    print(f"{name}: exit {r.returncode}, pre {meta.get('preTokens')} -> post {meta.get('postTokens')}, "
          f"summary ~{len(summary) // 4} tokens, fork {fork} deleted")


if __name__ == "__main__":
    main(*sys.argv[1:4])
