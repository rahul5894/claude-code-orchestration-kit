"""Self-contained check for md-guard.py. Run from anywhere: python md-guard_test.py
Builds its own fixtures (one 400-line .md, one 10-line .md) in a temp dir."""
import json
import os
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "md-guard.py")

tmp = tempfile.mkdtemp(prefix="md-guard-")
BIG = os.path.join(tmp, "big.md").replace("\\", "/")
SMALL = os.path.join(tmp, "small.md").replace("\\", "/")
BIG_WIN = BIG.replace("/", "\\")
# A big file under a non-ASCII path. Before 2026-09-19 the hook decoded stdin with the
# locale codec, so this path mangled, line_count() saw 0 lines and the Read was ALLOWED.
ACCENT_DIR = os.path.join(tmp, "Größe")
os.makedirs(ACCENT_DIR, exist_ok=True)
BIG_ACCENT = os.path.join(ACCENT_DIR, "big.md").replace("\\", "/")
with open(BIG, "w") as f:
    f.write("".join(f"line {i} " + "x" * 200 + "\n" for i in range(400)))
with open(SMALL, "w") as f:
    f.write("".join(f"line {i}\n" for i in range(10)))
with open(BIG_ACCENT, "w", encoding="utf-8") as f:
    f.write("".join(f"line {i} " + "x" * 200 + "\n" for i in range(400)))

CASES = [
    # (want, tool, input, agent_type)
    ("ALLOW", "Bash", {"command": f"cat > {tmp}/new.md <<EOF\nhi\nEOF"}, None),
    ("ALLOW", "Bash", {"command": f"cat >> {BIG} <<EOF\nrow\nEOF"}, None),
    ("ALLOW", "Bash", {"command": f'sed -i "s/a/b/" {BIG}'}, None),
    ("DENY",  "Bash", {"command": f'bash -c "cat {BIG}"'}, None),
    ("ALLOW", "Bash", {"command": f"grep -c line {BIG}"}, None),
    ("ALLOW", "Bash", {"command": 'qmd update && qmd search "x" -c planning --full-path -n 5'}, None),
    ("DENY",  "Bash", {"command": f"grep -n line {BIG}"}, None),
    ("ALLOW", "Bash", {"command": f"grep -n line {BIG} | cut -c1-300"}, None),
    # `grep -l` prints names only, so allowing it LOOKS free. It is not: the four cases
    # below pin the reverted 2026-09-19 relaxation. The first two are the bypasses it
    # opened, the third is the search-string match, the fourth is the convenience it was
    # meant to buy - denied, because no pattern separated it from the first three.
    ("DENY",  "Bash", {"command": f"grep -rl gate --include=*.md {tmp} | xargs cat"}, None),
    ("DENY",  "Bash", {"command": f"rg --files-with-matches gate -g *.md {tmp} | xargs cat"}, None),
    ("DENY",  "Bash", {"command": f'grep -rn "use -all mode" {BIG}'}, None),
    ("DENY",  "Bash", {"command": f'grep -rl "gate" --include=*.md {tmp}'}, None),
    ("ALLOW", "Bash", {"command": f"sed -n 1,5p {SMALL}"}, None),
    ("DENY",  "Bash", {"command": f"cat {BIG_WIN}"}, None),
    ("ALLOW", "Bash", {"command": f"git diff {BIG}"}, None),
    ("DENY",  "Bash", {"command": "cat some/unknown.md"}, None),
    ("ALLOW", "Bash", {"command": f"wc -l {BIG}"}, None),
    ("ALLOW", "Bash", {"command": "git add CLAUDE.md && git commit -m x"}, None),
    ("ALLOW", "Bash", {"command": f"rm -f {BIG}; git status --short | head -5"}, None),
    ("DENY",  "Bash", {"command": f"git status && cat {BIG} | head -5"}, None),
    ("DENY",  "PowerShell", {"command": f"Get-Content {BIG_WIN}"}, None),
    ("ALLOW", "PowerShell", {"command": f"Get-Content {BIG_WIN} -TotalCount 40 | % {{ $_.Substring(0, [Math]::Min(300, $_.Length)) }}"}, None),
    ("DENY",  "Read", {"file_path": BIG_ACCENT}, None),
    ("DENY",  "Read", {"file_path": BIG}, None),
    ("DENY",  "Read", {"file_path": BIG, "offset": 200}, None),
    ("ALLOW", "Read", {"file_path": BIG, "offset": 20, "limit": 100}, None),
    ("ALLOW", "Read", {"file_path": SMALL}, None),
    ("ALLOW", "Read", {"file_path": HOOK}, None),
    ("ALLOW", "Edit", {"file_path": BIG}, None),
    # A read-only agent's shell writes are denied on the agent_type in the payload. The same
    # command from a builder, or with no agent_type at all, stays allowed: this is a rule
    # about who is running, not about the command.
    ("DENY",  "Bash", {"command": f"echo hi > {tmp}/out.txt"}, "refuter"),
    ("ALLOW", "Bash", {"command": f"echo hi > {tmp}/out.txt"}, "builder"),
    ("ALLOW", "Bash", {"command": f"echo hi > {tmp}/out.txt"}, None),
    ("ALLOW", "Bash", {"command": "git status --short 2>&1"}, "refuter"),
    ("ALLOW", "Bash", {"command": "grep -n x file.py >/dev/null; echo $?"}, "refuter"),
    ("DENY",  "Bash", {"command": "sed -i s/a/b/ x.py"}, "debugger"),
    ("DENY",  "Bash", {"command": "git checkout -- x.py"}, "refuter"),
    ("ALLOW", "Bash", {"command": "git diff 4c52057...HEAD --stat"}, "refuter"),
    ("DENY",  "Bash", {"command": "python - <<'EOF'\nopen('x','w').write('1')\nEOF"}, "debugger"),
    ("ALLOW", "Bash", {"command": "python -c \"print(open('x').read())\""}, "refuter"),
    ("DENY",  "PowerShell", {"command": "Set-Content x.txt 'hi'"}, "refuter"),
    ("ALLOW", "Bash", {"command": "pytest tests/test_x.py -x -q"}, "debugger"),
    ("DENY",  "Bash", {"command": f"rm -f {tmp}/build.log"}, "refuter"),
    # Review 02 (report 02 items 1, 2, 3, 5, 16): every bypass it measured and every false
    # positive it measured, one line each. The redirect lines are judged on the command with
    # quoted spans blanked (DECISIONS 8), which is why the arrows and `awk '$1 > 5'` below
    # are allowed while `2>out.txt` is not.
    ("DENY",  "Bash", {"command": "echo hi >> out.txt"}, "refuter"),
    ("DENY",  "Bash", {"command": "python x.py 2>out.txt"}, "refuter"),
    ("DENY",  "Bash", {"command": "pytest -q 1>log.txt"}, "refuter"),
    ("DENY",  "Bash", {"command": "echo hi &>out.txt"}, "refuter"),
    ("DENY",  "Bash", {"command": "echo hi &>>out.txt"}, "refuter"),
    ("DENY",  "Bash", {"command": "cat <<EOF > out.txt"}, "refuter"),
    ("ALLOW", "Bash", {"command": "cmd 1>&2"}, "refuter"),
    ("ALLOW", "Bash", {"command": "echo x >/dev/null"}, "refuter"),
    ("ALLOW", "Bash", {"command": "echo x > /dev/null"}, "refuter"),
    ("ALLOW", "Bash", {"command": "cmd 2> /dev/null"}, "refuter"),
    ("ALLOW", "Bash", {"command": "cmd 2>/dev/null"}, "refuter"),
    ("ALLOW", "Bash", {"command": 'grep -n "->" file.py'}, "refuter"),
    ("ALLOW", "Bash", {"command": 'grep -rn "=>" src/'}, "refuter"),
    ("ALLOW", "Bash", {"command": "awk '$1 > 5' data.txt"}, "refuter"),
    ("ALLOW", "Bash", {"command": "git log --format='%h <%ae>'"}, "refuter"),
    ("ALLOW", "PowerShell", {"command": "Get-Content x > $null"}, "refuter"),
    ("ALLOW", "PowerShell", {"command": "cmd > nul"}, "refuter"),
    ("ALLOW", "PowerShell", {"command": 'Select-String "a -> b" x.txt'}, "refuter"),
    ("DENY",  "Bash", {"command": "git switch -c tmp"}, "refuter"),
    ("DENY",  "Bash", {"command": "git branch -D x"}, "refuter"),
    ("DENY",  "Bash", {"command": "git stash"}, "refuter"),
    ("DENY",  "Bash", {"command": "git worktree add ../x"}, "refuter"),
    ("DENY",  "Bash", {"command": "git tag v1"}, "refuter"),
    ("DENY",  "Bash", {"command": "git submodule update"}, "refuter"),
    ("ALLOW", "Bash", {"command": "git stash list"}, "refuter"),
    ("ALLOW", "Bash", {"command": "git stash show"}, "refuter"),
    ("ALLOW", "Bash", {"command": "git worktree list"}, "refuter"),
    ("ALLOW", "Bash", {"command": "git branch"}, "refuter"),
    ("ALLOW", "Bash", {"command": "git branch -a"}, "refuter"),
    ("ALLOW", "Bash", {"command": "git log --oneline -3"}, "refuter"),
    ("DENY",  "Bash", {"command": 'find . -name "*.pyc" -delete'}, "refuter"),
    ("DENY",  "Bash", {"command": "echo x | xargs rm -f"}, "refuter"),
    ("DENY",  "Bash", {"command": "perl -i -pe s/a/b/ x.py"}, "refuter"),
    ("DENY",  "Bash", {"command": "python -c \"import os;os.remove('x')\""}, "refuter"),
    ("DENY",  "Bash", {"command": "python -c \"open('x', mode='w')\""}, "refuter"),
    ("DENY",  "Bash", {"command": "pwsh -File install.ps1"}, "refuter"),
    ("DENY",  "PowerShell", {"command": "pwsh -File install.ps1"}, "refuter"),
    ("DENY",  "Bash", {"command": "python verify_live.py"}, "refuter"),
    ("DENY",  "PowerShell", {"command": "python verify_live.py"}, "refuter"),
    ("ALLOW", "Bash", {"command": 'find . -name "*.py" | head'}, "refuter"),
    ("ALLOW", "Bash", {"command": "python -m pytest tests/test_x.py -q"}, "refuter"),
]


def run(tool, inp, agent_type=None):
    # Bytes, not text=True: the payload must reach the hook as raw UTF-8, the way
    # JSON.stringify sends it. text=True would encode it with the locale codec and the
    # non-ASCII case below could never run on Windows.
    payload = {"tool_name": tool, "tool_input": inp}
    if agent_type:
        payload["agent_type"] = agent_type
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    p = subprocess.run([sys.executable, HOOK], input=raw, capture_output=True)
    return "DENY" if b'"deny"' in p.stdout else "ALLOW"


fails = 0
for want, tool, inp, agent_type in CASES:
    got = run(tool, inp, agent_type)
    if got != want:
        fails += 1
    label = inp.get("command") or inp.get("file_path")
    print(f"{'ok ' if got == want else 'BAD'} want={want:5} got={got:5} {tool:10} {label[:60]!r}")
print(f"\n{len(CASES) - fails}/{len(CASES)} passed")
sys.exit(1 if fails else 0)
