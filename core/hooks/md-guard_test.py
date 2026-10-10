"""Self-contained check for md-guard.py. Run from anywhere: python md-guard_test.py
Builds its own fixtures (one 400-line .md, one 10-line .md) in a temp dir."""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "md-guard.py")

tmp = tempfile.mkdtemp(prefix="md-guard-")
atexit.register(shutil.rmtree, tmp, True)
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
# A big doc with headings (its outline goes with a shell denial), and a big bucket file.
DOC = os.path.join(tmp, "guide.md").replace("\\", "/")
with open(DOC, "w", encoding="utf-8") as f:
    f.write("".join((f"## Part {i // 50}\n" if i % 50 == 0 else f"text {i}\n") for i in range(700)))
# A big doc under a folder with a space, the $env: variable the PowerShell case reads, and the
# temp dir as Git Bash spells it (/c/Users/... on Windows).
SPACED = os.path.join(tmp, "sub dir", "big.md").replace("\\", "/")
os.makedirs(os.path.dirname(SPACED), exist_ok=True)
with open(SPACED, "w") as f:
    f.write("".join(f"line {i}\n" for i in range(400)))
os.environ["KIT_MDG_DIR"] = tmp
GITBASH_TMP = ("/" + tmp[0].lower() + tmp[2:].replace("\\", "/")) if os.name == "nt" and tmp[1] == ":" else tmp
MUST = []
for rel in (".claude/scratch/b1/STATE.md",):
    p_ = os.path.join(tmp, rel).replace("\\", "/")
    os.makedirs(os.path.dirname(p_), exist_ok=True)
    with open(p_, "w", encoding="utf-8") as f:
        f.write("".join(f"row {i}\n" for i in range(500)))
    MUST.append(p_)

CASES = [
    # (want, tool, input, agent_type)
    ("ALLOW", "Bash", {"command": f"cat > {tmp}/new.md <<EOF\nhi\nEOF"}, None),
    ("ALLOW", "Bash", {"command": f"cat >> {BIG} <<EOF\nrow\nEOF"}, None),
    # a heredoc body is data: `type` + a .md name in it is not a read (denied 2026-09-23)
    ("ALLOW", "Bash", {"command": f"cat >> {SMALL} <<'EOF'\n- type continue then read STATE.md\nEOF"}, None),
    ("ALLOW", "Bash", {"command": f"cat >> {SMALL} <<-\"EOF\"\n- type continue then read STATE.md\n\tEOF"}, None),
    ("DENY",  "Bash", {"command": f"cat >> {SMALL} <<'EOF'\nrow\nEOF\ncat {BIG}"}, None),
    # unterminated: nothing is stripped, the verdict is what it was before stripping existed
    ("DENY",  "Bash", {"command": f"cat >> {SMALL} <<'EOF'\n- then cat {BIG}"}, None),
    # ...and a body naming a .md that does not exist reads nothing big (2026-10-07: unresolved
    # paths pass - 64% of shell denials since 09-29 were such paths or small files)
    ("ALLOW", "Bash", {"command": f"cat >> {SMALL} <<'EOF'\n- type continue then read STATE.md"}, None),
    # D009: a body is data only under a file-write line with a QUOTED delimiter. An unquoted
    # one expands $(...) and backticks, an interpreter runs its body, and a `<<` inside quotes,
    # a comment or arithmetic opens no heredoc at all - each of those is judged line by line.
    ("DENY",  "Bash", {"command": f"cat <<EOF\n$(cat {BIG})\nEOF"}, None),
    ("DENY",  "Bash", {"command": f"cat <<EOF\n`cat {BIG}`\nEOF"}, None),
    ("DENY",  "Bash", {"command": f"bash <<'EOF'\ncat {BIG}\nEOF"}, None),
    ("DENY",  "Bash", {"command": f"python - <<'EOF'\ncat {BIG}\nEOF"}, None),
    ("DENY",  "Bash", {"command": f'echo "<<EOF"\ncat {BIG}\nEOF'}, None),
    ("DENY",  "Bash", {"command": f"# see <<EOF\ncat {BIG}\nEOF"}, None),
    ("DENY",  "Bash", {"command": f"echo $((1<<2))\ncat {BIG}\n2"}, None),
    ("DENY",  "Bash", {"command": f"cat > {tmp}/x.txt \"<<'EOF'\"\ncat {BIG}\nEOF"}, None),
    ("ALLOW", "Bash", {"command": f"cat > {tmp}/x.md <<\"EOF\"\n- type continue then read STATE.md\nEOF"}, None),
    ("ALLOW", "Bash", {"command": f"tee -a {tmp}/x.md <<'EOF'\n- type continue then read STATE.md\nEOF"}, None),
    ("DENY",  "Bash", {"command": f"tee {tmp}/x.md <<'EOF' | bash\ncat {BIG}\nEOF"}, None),
    ("DENY",  "Bash", {"command": f"bash <<'EOF'; cat > {tmp}/f\ncat {BIG}\nEOF"}, None),
    # a quote opened on an earlier line: the heredoc-looking line is inside a string, and the
    # read after the string closes is real (found by /code-review 2026-09-23)
    ("DENY",  "Bash", {"command": f"echo \"\ncat > {tmp}/f <<'EOF'\n\"; cat {BIG}\nEOF"}, None),
    ("ALLOW", "Bash", {"command": f"cd {tmp} && cat >> {SMALL} <<'EOF'\n- type continue then read STATE.md\nEOF"}, None),
    # only a whitelisted write line strips its body: a separator glued to the target, a
    # second heredoc, or a process substitution hands the body to an interpreter (refuter-01)
    ("DENY",  "Bash", {"command": f"cat > {tmp}/f;bash <<'EOF'\ncat {BIG}\nEOF"}, None),
    ("DENY",  "Bash", {"command": f"cat > {tmp}/f|bash <<'EOF'\ncat {BIG}\nEOF"}, None),
    ("DENY",  "Bash", {"command": f"tee {tmp}/x&&bash <<'EOF'\ncat {BIG}\nEOF"}, None),
    ("DENY",  "Bash", {"command": f"bash <<'A'; cat > {tmp}/f <<'B'\ncat {BIG}\nA\nrow\nB"}, None),
    ("DENY",  "Bash", {"command": f"bash <<'A' | cat > {tmp}/f <<'B'\ncat {BIG}\nA\nrow\nB"}, None),
    ("DENY",  "Bash", {"command": f"cat > >(bash) <<'EOF'\ncat {BIG}\nEOF"}, None),
    ("DENY",  "Bash", {"command": f"tee >(bash) <<'EOF'\ncat {BIG}\nEOF"}, None),
    ("ALLOW", "Bash", {"command": f"cat <<'EOF' > {tmp}/x.md\n- type continue then read STATE.md\nEOF"}, None),
    # an earlier line can leave bash inside an outer heredoc, a string or a continuation, so a
    # write line after it strips nothing (refuter-03, each probed: bash ran the "body")
    ("DENY",  "Bash", {"command": f"cat <<X\ncat > {tmp}/f <<'EOF'\nX\ncat {BIG}\nEOF"}, None),
    ("DENY",  "Bash", {"command": f"cat <<X\ncat > /dev/null <<'EOF'\nX\ncat {BIG}\nEOF"}, "refuter"),
    ("DENY",  "Bash", {"command": f"echo \"x\\\"\ncat > {tmp}/f <<'EOF'\n\"; cat {BIG}\nEOF"}, None),
    ("DENY",  "Bash", {"command": f"bash -s \\\ntee {tmp}/f <<'EOF'\ncat {BIG}\nEOF"}, None),
    # a near-terminator (`  EOF`, `EOF `) does not end the body for bash: the next "heredoc
    # head" is body text, and its "body" runs (refuter-04, probed live)
    ("DENY",  "Bash", {"command": f"cat > /dev/null <<'EOF'\n  EOF\ncat > /dev/null <<'true'\nEOF\ncat {BIG}\ntrue"}, None),
    ("DENY",  "Bash", {"command": f"cat > /dev/null <<'EOF'\nEOF \ncat > /dev/null <<'true'\nEOF\ncat {BIG}\ntrue"}, "refuter"),
    # an UNquoted delimiter expands $(...) in the body, so a write line's body is still judged
    ("DENY",  "Bash", {"command": f"cat > {tmp}/f <<EOF\n$(cat {BIG})\nEOF"}, None),
    # back-to-back quoted write heredocs: both bodies are data
    ("ALLOW", "Bash", {"command": f"cat > {tmp}/a <<'EOF'\nread STATE.md\nEOF\ncat > {tmp}/b <<'EOF'\nread STATE.md\nEOF"}, None),
    ("DENY",  "Bash", {"command": "bash <<EOF\nrm x\nEOF"}, "refuter"),
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
    ("ALLOW", "Bash", {"command": "cat some/unknown.md"}, None),
    # 2026-10-07 false denials, each seen live: a search string naming a .md, a file the same
    # command creates, `$VAR` and loop paths to small files (the kit's own session, F11)
    ("ALLOW", "Bash", {"command": f'grep -rl "STATE.md" {tmp} | head -3'}, None),
    ("ALLOW", "Bash", {"command": f"python - <<'EOF'\nopen('{tmp}/made.md','w').write('x')\nEOF\nhead {tmp}/made-later.md"}, None),
    ("ALLOW", "Bash", {"command": f'M={tmp}; for f in small; do echo "== $f"; cat "$M/$f.md"; done'}, None),
    ("ALLOW", "Bash", {"command": 'cat "$KIT_TEST_UNSET_VAR/big.md"'}, None),
    # ...while a variable or loop that lands on the big file still denies
    ("DENY",  "Bash", {"command": f'M={tmp}; cat "$M/big.md"'}, None),
    ("DENY",  "Bash", {"command": f'M={tmp} && cat "${{M}}/big.md" | head -50'}, None),
    ("DENY",  "Bash", {"command": f'for f in small big; do cat "{tmp}/$f.md"; done'}, None),
    # a doc the agent must have whole reads raw in a shell too when small; big, it still goes
    # through Read (which passes it whole, below)
    ("DENY",  "Bash", {"command": f"cat {MUST[0]}"}, None),
    # review 2026-10-07: every spelling a shell expands is expanded before the verdict - a
    # quoted path with a space, $(pwd) / `pwd` / $PWD, $env:X, {a,b}, a bare "$f" from a loop
    # or an assignment, and find on a Git Bash /c/ path - all of which read the big doc whole
    ("DENY",  "Bash", {"command": f'cat "{SPACED}"'}, None),
    ("DENY",  "Bash", {"command": f'cd {tmp} && cat "$(pwd)/big.md"'}, None),
    ("DENY",  "Bash", {"command": f"cd {tmp} && cat `pwd`/big.md"}, None),
    ("DENY",  "PowerShell", {"command": "Get-Content $env:KIT_MDG_DIR/big.md"}, None),
    ("DENY",  "Bash", {"command": f"cat {tmp}/{{big,small}}.md"}, None),
    ("DENY",  "Bash", {"command": f'for f in {tmp}/b*.md; do cat "$f"; done'}, None),
    ("DENY",  "Bash", {"command": f'F={BIG}; cat "$F"'}, None),
    ("DENY",  "Bash", {"command": f"find {GITBASH_TMP} -name big.md -exec cat {{}} \\;"}, None),
    ("ALLOW", "Bash", {"command": f'for f in {tmp}/sm*.md; do cat "$f"; done'}, None),
    ("ALLOW", "Bash", {"command": f"cat {tmp}/{{small,nothere}}.md"}, None),
    # a search string naming a .md under a named folder is no read of that file (only `find`
    # joins a bare name onto a folder): `grep -rn "big.md" <dir>` was denied (review)
    ("ALLOW", "Bash", {"command": f'grep -rn "big.md" {tmp} | head -5'}, None),
    # refuter 2026-10-07: glued quoting, a subshell cd, bash -c, Join-Path and `git -C dir` read
    # the big doc whole; a grep pattern naming a file in the cwd is text; a URL is no path
    ("DENY",  "Bash", {"command": f'cd {tmp} && cat "$(pwd)"/big.md'}, None),
    ("DENY",  "Bash", {"command": f'cat {tmp}/"big".md'}, None),
    ("DENY",  "Bash", {"command": f"(cd {tmp} && cat big.md)"}, None),
    ("DENY",  "Bash", {"command": f'bash -c "cd {tmp} && cat big.md"'}, None),
    ("DENY",  "Bash", {"command": f"git -C {tmp} show HEAD:big.md | head -1000"}, None),
    ("DENY",  "PowerShell", {"command": f"Get-Content (Join-Path {tmp} big.md)"}, None),
    ("ALLOW", "Bash", {"command": f'cd {tmp} && grep -rn "big.md" .'}, None),
    ("ALLOW", "Bash", {"command": "curl -s https://example.net/big.md | head -50"}, None),
    # verifier N2/N3: grep's -a/-b take no value and -f reads patterns from a file, so the file
    # after them is still a read; a subshell's cd ends with the subshell
    ("DENY",  "Bash", {"command": f"grep -a . {BIG}"}, None),
    ("DENY",  "Bash", {"command": f"grep -v -f /dev/null {BIG}"}, None),
    ("DENY",  "Bash", {"command": f"cd {tmp} && (cd .claude && ls); cat big.md"}, None),
    ("ALLOW", "Bash", {"command": f"wc -l {BIG}"}, None),
    ("ALLOW", "Bash", {"command": "git add CLAUDE.md && git commit -m x"}, None),
    # 2026-09-29: 218 of 320 real shell denials were false. Precision without narrowing the
    # reader test: a first stage that only LISTS .md files feeding stdin filters (Bash), a small
    # file after `cd`, a glob of small files, a `;` inside quotes that used to cut a sed script
    # off its own `| cut -c` cap.
    ("ALLOW", "Bash", {"command": f"ls {BIG} | head -3"}, None),
    ("ALLOW", "Bash", {"command": f"git diff --stat -- {BIG} | tail -1"}, None),
    ("ALLOW", "Bash", {"command": f"cd {tmp} && cat small.md"}, None),
    ("ALLOW", "Bash", {"command": f"cat {tmp}/sm*.md"}, None),
    ("ALLOW", "Bash", {"command": f"sed -n '1p;2p' {BIG} | cut -c1-90"}, None),
    # ...while every shape a command-position rewrite let through (refuter, 2026-09-29) denies
    ("DENY",  "Bash", {"command": f"cd {tmp} && cat big.md"}, None),
    ("DENY",  "Bash", {"command": f"cat {tmp}/b*.md"}, None),
    ("DENY",  "Bash", {"command": f"< {BIG} cat"}, None),
    ("DENY",  "Bash", {"command": f"find {tmp} -name big.md -exec cat {{}} \\;"}, None),
    ("DENY",  "Bash", {"command": f"eval cat {BIG}"}, None),
    ("DENY",  "Bash", {"command": f'bash -lc "cat {BIG}"'}, None),
    ("DENY",  "Bash", {"command": f"ls {BIG} | xargs -I {{}} cat {{}}"}, None),
    ("DENY",  "PowerShell", {"command": f"ls {BIG} | cat"}, None),
    ("DENY",  "PowerShell", {"command": f"gci {BIG} | Get-Content"}, None),
    ("DENY",  "Bash", {"command": f"grep -rn x --include='*.md' {tmp}"}, None),
    ("DENY",  "Bash", {"command": f"rg -n x -g '*.md' {tmp}"}, None),
    ("DENY",  "Bash", {"command": f"cat $(grep -rl x --include=*.md {tmp})"}, None),
    ("DENY",  "Bash", {"command": f"python - <<'EOT'\nimport os; os.system('cat {BIG}')\nEOT"}, None),
    ("DENY",  "Bash", {"command": f"git show HEAD:{BIG}"}, None),
    ("ALLOW", "Bash", {"command": f"rm -f {BIG}; git status --short | head -5"}, None),
    ("DENY",  "Bash", {"command": f"git status && cat {BIG} | head -5"}, None),
    ("DENY",  "PowerShell", {"command": f"Get-Content {BIG_WIN}"}, None),
    ("ALLOW", "PowerShell", {"command": f"Get-Content {BIG_WIN} -TotalCount 40 | % {{ $_.Substring(0, [Math]::Min(300, $_.Length)) }}"}, None),
    # Read is Claude Code's own (D005, 2026-10-07): whole up to 25K tokens, then pages with a
    # PARTIAL-view note, refuses >256 KB. The hook says nothing about any Read, big or small.
    ("ALLOW", "Read", {"file_path": BIG_ACCENT}, None),
    ("ALLOW", "Read", {"file_path": BIG}, None),
    ("ALLOW", "Read", {"file_path": DOC}, None),
    ("ALLOW", "Read", {"file_path": BIG, "limit": 0}, None),
    ("ALLOW", "Read", {"file_path": MUST[0]}, None),
    ("ALLOW", "Read", {"file_path": SMALL}, None),
    ("ALLOW", "Edit", {"file_path": BIG}, None),
    # A read-only agent's shell writes are denied on the agent_type in the payload. The same
    # command from a builder, or with no agent_type at all, stays allowed: this is a rule
    # about who is running, not about the command.
    ("DENY",  "Bash", {"command": f"echo hi > {tmp}/out.txt"}, "refuter"),
    # the per-project off switch writes files; a read-only agent must not flip it (refuter-02)
    ("DENY",  "Bash", {"command": "python ~/.claude/kit/kit_switch.py off ."}, "refuter"),
    ("ALLOW", "Bash", {"command": f"echo hi > {tmp}/out.txt"}, "builder"),
    ("ALLOW", "Bash", {"command": f"echo hi > {tmp}/out.txt"}, None),
    ("ALLOW", "Bash", {"command": "git status --short 2>&1"}, "refuter"),
    ("ALLOW", "Bash", {"command": "grep -n x file.py >/dev/null; echo $?"}, "refuter"),
    ("DENY",  "Bash", {"command": "sed -i s/a/b/ x.py"}, "debugger"),
    ("DENY",  "Bash", {"command": "git checkout -- x.py"}, "refuter"),
    ("ALLOW", "Bash", {"command": "git diff 4c52057...HEAD --stat"}, "refuter"),
    ("DENY",  "Bash", {"command": "python - <<'EOF'\nopen('x','w').write('1')\nEOF"}, "debugger"),
    ("DENY",  "Bash", {"command": "python -c \"import os; os.close(os.open('k', os.O_CREAT))\""}, "refuter"),
    ("ALLOW", "Bash", {"command": "python -c \"import os; print(os.open('k', os.O_RDONLY))\""}, "refuter"),
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
    # write guard unchanged on 2026-09-29: two bypasses a loosening briefly opened stay shut
    ("DENY",  "PowerShell", {"command": '& "./install.ps1"'}, "refuter"),
    ("DENY",  "Bash", {"command": "git apply --check --apply x.patch"}, "refuter"),
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
    if b'"deny"' in p.stdout:
        return "DENY"
    return "WINDOW" if b'"updatedInput"' in p.stdout else "ALLOW"


fails = 0
for want, tool, inp, agent_type in CASES:
    got = run(tool, inp, agent_type)
    if got != want:
        fails += 1
    label = inp.get("command") or inp.get("file_path")
    print(f"{'ok ' if got == want else 'BAD'} want={want:5} got={got:5} {tool:10} {label[:60]!r}")

# A denial must say how to get ALL of the file, not only how to find a spot in it: a model
# told "grep, then Read a window" can stop at one window and work from part of the document.
def reason(tool, inp, field="permissionDecisionReason"):
    raw = json.dumps({"tool_name": tool, "tool_input": inp}, ensure_ascii=False).encode("utf-8")
    p = subprocess.run([sys.executable, HOOK], input=raw, capture_output=True)
    try:
        out = json.loads(p.stdout)["hookSpecificOutput"]
        return json.dumps(out[field]) if field == "updatedInput" else out[field]
    except (ValueError, KeyError, TypeError):
        return ""


MESSAGES = [
    ("shell deny says cut truncates, read content with Read",
     reason("Bash", {"command": f"cat {BIG}"}), ["truncates long lines", "Read every window in order"]),
    ("shell deny carries the line count and the outline",
     reason("Bash", {"command": f"cat {DOC}"}), ["guide.md (700 lines)", "Outline (", "L351 ## Part 7"]),
]
# The hook runs on every shell call with a 5 s budget: a URL (a UNC spelling took 17 s) and a
# brace explosion (six 20-way braces took 0.78 s) must each stay far inside it.
import time  # noqa: E402
for cmd in ("curl -s https://example.net/README.md | head -50",
            "cat " + "{a,b,c,d,e,f,g,h,i,j,k,l,m,n,o,p,q,r,s,t}" * 6 + ".md"):
    t0 = time.perf_counter()
    run("Bash", {"command": cmd})
    MESSAGES.append((f"under 2 s: {cmd[:30]}", "ok" if time.perf_counter() - t0 < 2 else "slow", ["ok"]))
for label, text, needles in MESSAGES:
    good = all(n in text for n in needles)
    if not good:
        fails += 1
    print(f"{'ok ' if good else 'BAD'} message: {label}")

total = len(CASES) + len(MESSAGES)
print(f"\n{total - fails}/{total} passed")
sys.exit(1 if fails else 0)
