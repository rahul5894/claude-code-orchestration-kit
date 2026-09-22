"""Self-contained check for scan_project.py. Run from anywhere: python scan_project_test.py
Builds its own fixtures (node, python, docs-only, a 1500-file tree) in a temp dir. No network.
The temp dir goes away even when a case raises: the installer runs this on every install.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
SCAN = os.path.join(HERE, "scan_project.py")
TEMPLATE = os.path.join(HERE, "extras", "project", "CLAUDE.md")
sys.path.insert(0, HERE)
import scan_project                                                    # noqa: E402

HEADINGS = scan_project.HEADINGS
GIT = shutil.which("git") is not None
tmp = tempfile.mkdtemp(prefix="scan-project-")
results = []


def check(label, cond, detail=""):
    results.append((label, bool(cond)))
    print(f"{'ok ' if cond else 'BAD'} {label}" + ("" if cond else f"\n      -> {detail}"))


def check_git(label, cond, detail=""):
    """A case that needs a real git repo. No git on PATH is a skip, not a failure."""
    if not GIT:
        results.append((label, True))
        print(f"skip {label} (git is not on PATH)")
        return
    check(label, cond, detail)


def write(root, rel, text):
    p = os.path.join(root, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)


def fixture(name, files, git=False):
    root = os.path.join(tmp, name)
    for rel, text in files.items():
        write(root, rel, text)
    if git and GIT:
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        for args in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "x"]):
            subprocess.run(["git", "-C", root] + args, capture_output=True, env=env)
    return root


def scan(root, *extra):
    r = subprocess.run([sys.executable, SCAN] + list(extra) + [root],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def block(text, heading):
    m = re.search(rf"^## {re.escape(heading)}\s*$", text, re.M)
    if not m:
        return ""
    nxt = re.search(r"^## ", text[m.end():], re.M)
    return text[m.start():m.end() + nxt.start() if nxt else len(text)]


try:
    # 1. A node repo: the two code files with real hits, the migrations dir, pnpm, the
    #    workflow, the lockfile, a .env someone committed and the .env.example beside it.
    node = fixture("node", {
        "package.json": '{"name":"n","engines":{"node":"20"}}',
        "pnpm-lock.yaml": "lockfileVersion: 9\n",
        ".env": "STRIPE_SECRET_KEY=sk_live_x\n",
        ".env.example": "STRIPE_SECRET_KEY=\n",
        "src/auth/session.ts": ("import jwt from 'jsonwebtoken'\n"
                                "export function login(req) { const c = req.cookies.session\n"
                                "  return jwt.verify(c, process.env.SECRET) }\n"),
        "src/api/upload.ts": ("import multer from 'multer'\n"
                              "export async function POST(req) { const f = req.formData()\n"
                              "  return upload(f, process.env.API_KEY) }\n"),
        "prisma/schema.prisma": "datasource db { provider = \"postgresql\" }\n",
        "prisma/migrations/0001/migration.sql": "create table users (id int);\n",
        ".github/workflows/deploy.yml": "on: push\njobs: {deploy: {runs-on: ubuntu-latest}}\n",
        "README.md": "a secret API_KEY mentioned in prose only\n",
    }, git=True)
    code, out = scan(node)
    sec, dang, conv = (block(out, "Security surfaces in THIS repo"), block(out, "Danger list"),
                       block(out, "Conventions"))
    check("node: exits 0 and prints all four headings",
          code == 0 and all(f"## {h}" in out for h in HEADINGS), out[:300])
    check("node: security lists session.ts and upload.ts, and prisma/migrations/",
          "`src/auth/session.ts`" in sec and "`src/api/upload.ts`" in sec
          and "`prisma/migrations/`" in sec, sec)
    check("node: security does not list the README (prose is not a surface)",
          "README.md" not in sec, sec)
    check("node: conventions name pnpm and node 20",
          "pnpm (pnpm-lock.yaml)" in conv and "Node 20" in conv, conv)
    check_git("node: danger names the workflow, the lockfile, the migrations and .env TRACKED",
              ".github/workflows/deploy.yml" in dang and "pnpm-lock.yaml" in dang
              and "prisma/migrations/" in dang and "`.env` — TRACKED IN GIT" in dang, dang)
    check("node: the workflow is CI, not a deploy script (one line, not two)",
          dang.count(".github/workflows/deploy.yml") == 1
          and "CI: runs on push" in dang, dang)
    check("node: .env.example is never called a secrets file",
          ".env.example" not in dang, dang)
    check_git("node: layout names a file changed in the only commit (no 5-commit floor)",
              re.search(r"- `[^`]+` — changed in 1 of the last 1 commits",
                        block(out, "Layout")), block(out, "Layout"))

    # 2. A python fastapi repo: routes + secrets + db in one file, ruff as the linter, an
    #    alembic migrations dir, a seed script, and a docs/ dir that only talks about them.
    py = fixture("py", {
        "pyproject.toml": '[project]\nrequires-python = ">=3.11"\n\n[tool.ruff]\nline-length = 100\n',
        "app/main.py": ("import os\nfrom sqlalchemy import create_engine\n"
                        "engine = create_engine(os.environ['DB_URL'])\n"
                        "@app.get('/users')\ndef users(): return engine\n"
                        "@app.post('/users')\n"
                        "def add(u): return engine.execute('insert into users values (1)')\n"),
        "alembic/versions/0001_init.py": "def upgrade(): op.create_table('users')\n",
        "scripts/seed.py": "rows = [1, 2, 3]\n",
        "docs/migrations/plan.sql": "-- how we would migrate, one day\n",
    }, git=True)
    code, out = scan(py)
    sec2, conv2, dang2 = (block(out, "Security surfaces in THIS repo"), block(out, "Conventions"),
                          block(out, "Danger list"))
    row = next((l for l in sec2.splitlines() if "app/main.py" in l), "")
    check("python: main.py listed with routes, secrets and db",
          all(c in row for c in ("routes", "secrets", "db")), row or sec2)
    check("python: conventions name ruff and the requires-python",
          "ruff" in conv2 and "3.11" in conv2, conv2)
    check("python: alembic/versions is a migrations danger line",
          "`alembic/versions/` — migrations" in dang2, dang2)
    check("python: docs/migrations/ is prose, not a migrations danger line",
          "docs/migrations" not in dang2, dang2)
    check("python: scripts/seed.py is flagged as writing to a database",
          "`scripts/seed.py` — writes to a database" in dang2, dang2)

    # 3. A docs-only tree: every section says so instead of inventing something.
    docs = fixture("docs", {"README.md": "# notes\n", "docs/plan.md": "# plan\n"})
    code, out = scan(docs)
    check("docs-only: all four sections carry a none/nothing-detected bullet",
          code == 0 and len(re.findall(r"^- no(ne|thing) detected by scan_project\.py", out, re.M)) == 4,
          out)

    # 4. The four files the word-matching used to get wrong, in one tree.
    mix = fixture("mix", {
        "src/components/Button.tsx": ("// the session is read higher up; this is presentation\n"
                                      "export const Button = () => <div role=\"button\" />\n"),
        "app/api/users/route.ts": "export async function GET() { return [] }\n",
        "core/hooks/kit-session-start.py": ("# prints one line when the session starts and the\n"
                                            "# project has no gate row. It decides nothing.\n"
                                            "print('ok')\n"),
        ".mcp.json": '{"mcpServers":{"x":{"env":{"API_KEY":"${X}"}}}}\n',
    })
    sec3 = block(scan(mix)[1], "Security surfaces in THIS repo")
    check("a `role=\"button\"` and the word session in a comment are not a surface",
          "Button.tsx" not in sec3, sec3)
    check("app/api/users/route.ts is a surface on its path plus one route hit",
          "`app/api/users/route.ts`" in sec3, sec3)
    check("a hook that only mentions `session` in prose is not a surface",
          "kit-session-start.py" not in sec3, sec3)
    check("`.mcp.json` is read for secrets even though .json is content",
          "`.mcp.json`" in sec3, sec3)

    # 5. --apply on a real copy of the shipped template: fills the placeholder LINES, keeps
    #    every other line byte-identical, and a second run refreshes without duplicating.
    before = open(TEMPLATE, encoding="utf-8").read()
    shutil.copyfile(TEMPLATE, os.path.join(node, "CLAUDE.md"))
    code, rep = scan(node, "--apply")
    after = open(os.path.join(node, "CLAUDE.md"), encoding="utf-8").read()

    def stripped(text):
        for h in HEADINGS:
            b = block(text, h)
            text = text.replace(b, f"@@{h}@@\n") if b else text
        return text.replace("\r\n", "\n")

    check("--apply: reports all four filled, exit 0",
          code == 0 and rep.count(": filled") == 4, rep)
    check("--apply: every line outside the four blocks is byte-identical",
          stripped(before) == stripped(after),
          [l for l in stripped(after).splitlines() if l not in stripped(before).splitlines()][:4])
    check("--apply: no template placeholder survives in the four blocks",
          not re.search(r"<path>|<dir>/|<language/version|<\.\.\.>",
                        "".join(block(after, h) for h in HEADINGS)), after[:200])
    check("--apply: the template's own prose inside a block survives, exactly once",
          after.count("reviewer does not have to guess") == 1
          and after.count("New code matches the file it lands in") == 1
          and after.count("Name the three or four files most changes touch") == 1,
          "".join(block(after, h) for h in HEADINGS)[:300])
    check("--apply: no `- <hint>` template bullet survives inside the four sections",
          not re.search(r'^\s*- <[^>]+>\s*$', "".join(block(after, h) for h in HEADINGS), re.M),
          "".join(block(after, "Danger list"))[:300])
    code2, rep2 = scan(node, "--apply")
    check("--apply twice: the second run rewrites its own block, byte for byte",
          code2 == 0 and open(os.path.join(node, "CLAUDE.md"), encoding="utf-8").read() == after,
          rep2)
    write(node, "CLAUDE.md", before.replace(
        "- `<path>` — <what goes wrong if this is changed carelessly>",
        "- `src/db.ts` — a human wrote this line\n"
        "- `<path>` — <what goes wrong if this is changed carelessly>"))
    code3, rep3 = scan(node, "--apply")
    edited = open(os.path.join(node, "CLAUDE.md"), encoding="utf-8").read()
    check("a human's own bullet survives beside the detected ones",
          "a human wrote this line" in edited and "auto-detected" in block(edited, "Danger list"),
          block(edited, "Danger list"))
    hand = fixture("hand", {"CLAUDE.md": "".join(
        f"## {h}\n\n- `src/x.ts` — a human filled this in\n\n" for h in HEADINGS)})
    check("a section with no placeholder line left is kept, not rewritten",
          scan(hand, "--apply")[1].count(": kept") == 4, scan(hand, "--apply")[1])
    check("--apply with no CLAUDE.md exits 2", scan(docs, "--apply")[0] == 2, str(scan(docs, "--apply")))
    bad = os.path.join(tmp, "latin1")
    os.makedirs(bad, exist_ok=True)
    with open(os.path.join(bad, "CLAUDE.md"), "wb") as fh:
        fh.write(b"## Layout\n\n- caf\xe9 in latin-1\n")
    code4, rep4 = scan(bad, "--apply")
    check("a CLAUDE.md that is not UTF-8 exits 2 and is left alone",
          code4 == 2 and "not UTF-8" in rep4
          and open(os.path.join(bad, "CLAUDE.md"), "rb").read().endswith(b"latin-1\n"), rep4)

    # 6. apply() itself: line endings, a fenced `## `, and a human line above a placeholder.
    secs = {h: ([], [f"<!-- auto-detected x -->", f"- {h} detected"]) for h in HEADINGS}
    secs["Layout"] = (["core/     8 files"], ["<!-- auto-detected x -->", "- `a.py` — changed"])
    body = ("# t\n\n## Layout\n\n```\n<dir>/     <one line>\n## not a heading\n```\n\n"
            "prose that stays\n\n## Danger list\n\n- `keep.ts` — human\n- `<path>` — <gone>\n")
    lf, _ = scan_project.apply(body, secs)
    check("apply(): an LF file stays LF", "\r" not in lf, repr(lf[:40]))
    crlf, _ = scan_project.apply(body.replace("\n", "\r\n"), secs)
    check("apply(): a CRLF file stays CRLF",
          crlf.count("\r\n") == crlf.count("\n") and "\r\n" in crlf, repr(crlf[:40]))
    check("apply(): a `## ` line inside a fence does not end the section",
          "## not a heading" in lf and "core/     8 files" in lf
          and "prose that stays" in lf and "- `a.py` — changed" in lf, lf)
    check("apply(): a human bullet above a placeholder bullet survives",
          "- `keep.ts` — human" in lf and "- Danger list detected" in lf and "<path>" not in lf, lf)
    check("apply(): a heading the file does not have is reported absent",
          scan_project.apply(body, secs)[1]["Conventions"] == "absent",
          scan_project.apply(body, secs)[1])

    # 7. A git repo whose index is still empty: the tree is scanned anyway.
    fresh = fixture("fresh", {"src/auth/login.ts": "import jwt from 'jsonwebtoken'\n"})
    if GIT:
        subprocess.run(["git", "-C", fresh, "init", "-q"], capture_output=True)
    check_git("a git repo with nothing added yet still detects its files",
              "`src/auth/login.ts`" in block(scan(fresh)[1], "Security surfaces in THIS repo"),
              scan(fresh)[1][:300])

    # 8. Determinism: the same tree twice gives the same bytes.
    check("two runs on the same tree produce identical stdout", scan(node)[1] == scan(node)[1])

    # 9. A manifest mid-edit and a pubspec whose `sdk:` is a dependency, not the SDK.
    broken = fixture("broken", {"package.json": '{"name":"n", "engines": ',
                                "pubspec.yaml": "dependencies:\n  foo:\n    sdk: flutter\n"})
    code, out = scan(broken)
    check("a half-written package.json and a dependency `sdk:` are absent, not a crash",
          code == 0 and "Traceback" not in out and "Dart sdk" not in out, out[:300])

    # 10. 1,500 files (opt-in: `--perf`), 11. a NUL byte and a 2 MB file skipped.
    # The installer runs this file on every install, twice under verify_live; building 1,500
    # files cost it 6 s of wall-clock (measured 2026-09-22: install.ps1 1.2 s -> 7.8 s), so the
    # perf case runs only when asked and counts as passed otherwise, keeping N/N stable.
    big = os.path.join(tmp, "big")
    n_files = 1500 if "--perf" in sys.argv else 20
    for i in range(n_files):
        write(big, f"src/mod{i // 50}/f{i}.ts", f"export const x{i} = {i}\nconst role = 'admin'\n")
    with open(os.path.join(big, "blob.bin"), "wb") as fh:
        fh.write(b"jwt\0secret" * 10)
    with open(os.path.join(big, "huge.ts"), "w", encoding="utf-8") as fh:
        fh.write("// process.env.SECRET\n" + "x" * 2_100_000)
    # Warm the tree first. Measured 2026-09-22 on Windows: the FIRST touch of 1,500 files that
    # were created milliseconds ago costs 5.3 s, while a plain Python read of the same 51 KB
    # afterwards costs 0.06 s and the scan 0.18 s. That 5.3 s is the filesystem, not the
    # scanner, and timing it here would pin this check to how busy the machine's AV is.
    for dirpath, _, names in os.walk(big):
        for n in names:
            open(os.path.join(dirpath, n), "rb").read()
    t0 = time.time()
    code, out = scan(big)
    elapsed = time.time() - t0
    if n_files == 1500:
        check(f"1,500-file non-git tree scans in under 15 s via os.walk ({elapsed:.2f} s)",
              code == 0 and elapsed < 15.0 and "## Layout" in out, out[:200])
    else:
        check("1,500-file scan: skipped (run with --perf); 20-file tree scanned instead",
              code == 0 and "## Layout" in out, out[:200])
    check("the NUL-byte file and the 2 MB file are skipped without error",
          "blob.bin" not in out and "huge.ts" not in out and "Traceback" not in out, out[:400])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

passed = sum(1 for _, okx in results if okx)
print(f"\n{passed}/{len(results)} passed")
sys.exit(0 if passed == len(results) else 1)
