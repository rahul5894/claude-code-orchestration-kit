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
    # (want, tool, input)
    ("ALLOW", "Bash", {"command": f"cat > {tmp}/new.md <<EOF\nhi\nEOF"}),
    ("ALLOW", "Bash", {"command": f"cat >> {BIG} <<EOF\nrow\nEOF"}),
    ("ALLOW", "Bash", {"command": f'sed -i "s/a/b/" {BIG}'}),
    ("DENY",  "Bash", {"command": f'bash -c "cat {BIG}"'}),
    ("ALLOW", "Bash", {"command": f"grep -c line {BIG}"}),
    ("ALLOW", "Bash", {"command": 'qmd update && qmd search "x" -c planning --full-path -n 5'}),
    ("DENY",  "Bash", {"command": f"grep -n line {BIG}"}),
    ("ALLOW", "Bash", {"command": f"grep -n line {BIG} | cut -c1-300"}),
    # `grep -l` prints names only, so allowing it LOOKS free. It is not: the four cases
    # below pin the reverted 2026-09-19 relaxation. The first two are the bypasses it
    # opened, the third is the search-string match, the fourth is the convenience it was
    # meant to buy - denied, because no pattern separated it from the first three.
    ("DENY",  "Bash", {"command": f"grep -rl gate --include=*.md {tmp} | xargs cat"}),
    ("DENY",  "Bash", {"command": f"rg --files-with-matches gate -g *.md {tmp} | xargs cat"}),
    ("DENY",  "Bash", {"command": f'grep -rn "use -all mode" {BIG}'}),
    ("DENY",  "Bash", {"command": f'grep -rl "gate" --include=*.md {tmp}'}),
    ("ALLOW", "Bash", {"command": f"sed -n 1,5p {SMALL}"}),
    ("DENY",  "Bash", {"command": f"cat {BIG_WIN}"}),
    ("ALLOW", "Bash", {"command": f"git diff {BIG}"}),
    ("DENY",  "Bash", {"command": "cat some/unknown.md"}),
    ("ALLOW", "Bash", {"command": f"wc -l {BIG}"}),
    ("ALLOW", "Bash", {"command": "git add CLAUDE.md && git commit -m x"}),
    ("ALLOW", "Bash", {"command": f"rm -f {BIG}; git status --short | head -5"}),
    ("DENY",  "Bash", {"command": f"git status && cat {BIG} | head -5"}),
    ("DENY",  "PowerShell", {"command": f"Get-Content {BIG_WIN}"}),
    ("ALLOW", "PowerShell", {"command": f"Get-Content {BIG_WIN} -TotalCount 40 | % {{ $_.Substring(0, [Math]::Min(300, $_.Length)) }}"}),
    ("DENY",  "Read", {"file_path": BIG_ACCENT}),
    ("DENY",  "Read", {"file_path": BIG}),
    ("DENY",  "Read", {"file_path": BIG, "offset": 200}),
    ("ALLOW", "Read", {"file_path": BIG, "offset": 20, "limit": 100}),
    ("ALLOW", "Read", {"file_path": SMALL}),
    ("ALLOW", "Read", {"file_path": HOOK}),
    ("ALLOW", "Edit", {"file_path": BIG}),
]


def run(tool, inp):
    # Bytes, not text=True: the payload must reach the hook as raw UTF-8, the way
    # JSON.stringify sends it. text=True would encode it with the locale codec and the
    # non-ASCII case below could never run on Windows.
    raw = json.dumps({"tool_name": tool, "tool_input": inp}, ensure_ascii=False).encode("utf-8")
    p = subprocess.run([sys.executable, HOOK], input=raw, capture_output=True)
    return "DENY" if b'"deny"' in p.stdout else "ALLOW"


fails = 0
for want, tool, inp in CASES:
    got = run(tool, inp)
    if got != want:
        fails += 1
    label = inp.get("command") or inp.get("file_path")
    print(f"{'ok ' if got == want else 'BAD'} want={want:5} got={got:5} {tool:10} {label[:60]!r}")
print(f"\n{len(CASES) - fails}/{len(CASES)} passed")
sys.exit(1 if fails else 0)
