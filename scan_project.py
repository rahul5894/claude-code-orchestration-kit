#!/usr/bin/env python3
"""What is dangerous in THIS repo - detected, never guessed. Fills four CLAUDE.md sections.

    python scan_project.py [<repo>]                 # print the four sections
    python scan_project.py --apply [<repo>]         # write them into <repo>/CLAUDE.md
    python ~/.claude/kit/scan_project.py --apply .  # what /kit-init runs

/kit-init used to leave Security surfaces, Layout, Conventions and Danger list as the
template's visible placeholders for the user to fill by hand, and they stayed empty. A model
filling them instead is worse: a guessed security surface is trusted by a reviewer. So this
script detects them from what the tree actually contains - one regex per category, counted
per file, the evidence on every line - and writes them itself. Two runs on the same tree
produce the same text (the date excepted), because nothing here asks a model anything.

`--apply` rewrites placeholder LINES inside each section - the template's `<path>` bullets and
the block under a previous `<!-- auto-detected` marker - and nothing else, so the template's
prose is never duplicated here and a human's own lines survive. A section with no placeholder
line left is reported `kept`. Exit 0 on success, 2 when --apply has no CLAUDE.md to write.
"""
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except (AttributeError, OSError):
    pass

TODAY = datetime.date.today().isoformat()
MAX_FILE = 1024 * 1024          # a file over 1 MB is data, not code someone reviews
MAX_BYTES = 200 * 1024          # and only its first 200 KB is worth a regex
SKIP_DIRS = {'.git', 'node_modules', '.venv', 'venv', 'dist', 'build', '.next', '.dart_tool',
             '__pycache__', '.qartez', 'vendor', 'coverage'}
# Content, not code: scanning prose for `secret` or `login` lists every doc in the repo.
CONTENT_EXT = {'.md', '.txt', '.json', '.lock', '.svg', '.csv'}
# ...except the handful of .json files that ARE the surface: settings, MCP and credentials.
JSON_SEC = re.compile(r'^(settings.*\.json|\.mcp.*\.json|firebase.*\.json'
                      r'|.*service-?account.*\.json|credentials.*\.json|vercel\.json'
                      r'|appsettings.*\.json|secrets.*\.json)$', re.I)
GENERATED = re.compile(r'\.g\.dart$|\.freezed\.dart$|\.pb\.go$|\.pb\.dart$|_pb2\.py$'
                       r'|\.generated\.|(^|/)__generated__/|\.min\.js$')
LOCKFILES = ('package-lock.json', 'yarn.lock', 'pnpm-lock.yaml', 'bun.lockb', 'poetry.lock',
             'uv.lock', 'Pipfile.lock', 'Cargo.lock', 'composer.lock', 'pubspec.lock',
             'go.sum', 'Gemfile.lock')
# Every generic word is gone: `session` in a comment, `role="button"` and `invoice` in prose
# listed half the repo. What is left names a library, a call, or an SQL verb.
CATEGORIES = [
    ('auth', r'\b(jwt|jsonwebtoken|passport|bcrypt|argon2|oauth2?|openid|next-auth|clerk|'
             r'firebase_auth|supabase\.auth|auth\.(uid|user|currentUser)|authenticate|'
             r'authorization|bearer|csrf|xsrf)\b|\b(login|logout)\s*\(|getServerSession|'
             r'express-session|SessionMiddleware|session\.(get|set|destroy|regenerate)|'
             r'cookies\(\)|set_cookie|setCookie|res\.cookie'),
    ('entitlement', r'\b(role(s)?(?!=)|permission(s)?|is_admin|isAdmin|is_staff|isSuperuser|'
                    r'policy|policies|rls|row level security|entitlement(s)?|quota|'
                    r'rate_?limit|feature_?flag)\b'),
    ('db', r'\b(select\s+.+\s+from|insert\s+into|update\s+\w+\s+set|delete\s+from|prisma|'
           r'sequelize|knex|typeorm|drizzle|sqlalchemy|django\.db|models\.Model|gorm|sqlx|'
           r'pgx|mongoose|supabase\.from|firestore|createClient\()'),
    ('upload', r'\b(multipart|formdata|upload(s|ed)?|multer|busboy|UploadFile|file_field|'
               r'image_picker|MediaType|sharp\(|ffmpeg|imagemagick|storage\.from|putObject|'
               r'presigned)\b'),
    # The env-name tokens carry no leading boundary on purpose: EXA_API_KEY is an API key.
    ('secrets', r'\b(process\.env|os\.environ|getenv|dotenv|credentials?|keychain|'
                r'SecureStorage)\b|(SECRET|API_KEY|PRIVATE_KEY|ACCESS_TOKEN)\b'),
    ('routes', r'\b(app\.(get|post|put|delete|patch)\(|router\.(get|post|put|delete|patch)\('
               r'|@app\.route|@router\.|APIRouter|http\.Handle(Func)?|HandleFunc|'
               r'export\s+(async\s+)?function\s+(GET|POST|PUT|DELETE|PATCH)|"use server"|'
               r"'use server'|createServerAction|@Controller|@Get\(|@Post\()"),
    ('payments', r'\b(stripe|razorpay|paypal|braintree|checkout\.session|webhook(s)?|refund|'
                 r'payment_?intent)\b'),
]
CATEGORIES = [(n, re.compile(p, re.I)) for n, p in CATEGORIES]
# A settings/credentials json is read for these two only - a route regex on JSON is noise.
JSON_CATEGORIES = [(n, rx) for n, rx in CATEGORIES if n in ('secrets', 'entitlement')]
# Three hits in one of these carry a file on their own; the rest need a second category.
STRONG = ('auth', 'entitlement', 'secrets', 'payments')
# Where the file sits is evidence too: one hit in app/api/ beats three `secret`s in a README.
PATH_SIG = re.compile(r'(^|/)(auth|session|login|oauth|sso|permission|permissions|role|roles|'
                      r'policy|policies|rls|guard|guards|middleware|secret|secrets|credential|'
                      r'credentials|billing|payment|payments|stripe|checkout|upload|uploads|'
                      r'storage|api|routes?|handlers?|controllers?|views|urls|route\.(ts|js)|'
                      r'server|actions|admin|migrations?)(/|\.|_|-)')
SEC_DIRS = {'migrations': 'schema and RLS policies live here',
            'migrate': 'schema changes live here',
            'policies': 'access-control policies live here',
            'supabase': 'database, RLS policies and edge functions',
            'auth': 'authentication and session handling',
            'middleware': 'runs on every request - auth and redirects are decided here',
            'guards': 'route and permission guards'}
# A real secrets file, never a .env.example / .env.sample / .envrc checked in on purpose.
ENVFILE = re.compile(r'^\.env(\.(local|development|production|staging|test)){0,2}$')
MIG_DIRS = ('migrations', 'migrate', 'db/migrate', 'alembic/versions', 'supabase/migrations',
            'prisma/migrations', 'drizzle', 'flyway', 'liquibase')
MIG_EXT = {'.sql', '.py', '.js', '.ts', '.go', '.rb'}
DEPLOY_FILES = [(re.compile(r'(^|/)Dockerfile[^/]*$'), 'builds the image that ships'),
                (re.compile(r'(^|/)docker-compose[^/]*\.ya?ml$'), 'brings up real services'),
                (re.compile(r'(^|/)deploy(\.[^/]+)?$'),
                 'deploys; changes here ship to production'),
                (re.compile(r'^(fly\.toml|vercel\.json|netlify\.toml)$'),
                 'hosting config; a change here redeploys the site')]
INFRA_DIRS = {'terraform': 'infrastructure as code; an edit here changes live infrastructure',
              'k8s': 'infrastructure as code; an edit here changes live infrastructure',
              'helm': 'infrastructure as code; an edit here changes live infrastructure',
              'deploy': 'deploys; changes here ship to production',
              'deployment': 'deploys; changes here ship to production'}
WORKFLOW = re.compile(r'^\.github/workflows/[^/]+\.ya?ml$')
SEED = re.compile(r'(^|/)seed[^/]*\.(py|ts|js|sql)$')
HEADINGS = ('Security surfaces in THIS repo', 'Layout', 'Conventions', 'Danger list')
MARKER = '<!-- auto-detected'
# The block is closed, not open-ended: without this line a re-run swallowed the template
# prose that happened to sit under the last detected bullet.
END = '<!-- /auto-detected -->'
# What --apply is allowed to overwrite: a template placeholder, a previous run's block, and
# the "nothing detected" bullets it wrote - those refresh once the repo grows what they missed.
PLACEHOLDER = re.compile(r'<path>|<dir>/|<language/version|<\.\.\.>|<!-- auto-detected'
                         r'|^\s*- nothing detected by scan_project\.py'
                         r'|^\s*- none detected by scan_project\.py'
                         r'|^\s*- <[^>]+>\s*$')   # a bullet that is only a template <hint>



def git(root, *args):
    """git stdout, or None when this is not a git repo / git is not installed."""
    if not (root / '.git').exists():
        return None
    try:
        r = subprocess.run(['git', '-C', str(root)] + list(args), capture_output=True,
                           text=True, encoding='utf-8', errors='replace', timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def census(root):
    """Every file the scan may look at: relative, posix, sorted. Tracked files when git."""
    out = git(root, 'ls-files', '-z')
    names = [n.replace('\\', '/') for n in out.split('\0') if n] if out else []
    if not names:          # a repo whose index is still empty is a tree like any other
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            base = pathlib.Path(dirpath)
            names += [(base / f).relative_to(root).as_posix() for f in filenames]
    return sorted(n for n in names if not (set(n.split('/')[:-1]) & SKIP_DIRS))


def read_head(path):
    """The first 200 KB as text, or None for a file that is too big or is not text."""
    try:
        if path.stat().st_size > MAX_FILE:
            return None
        with open(path, 'rb') as fh:
            blob = fh.read(MAX_BYTES)
    except OSError:
        return None
    if b'\0' in blob[:4096]:
        return None
    return blob.decode('utf-8', errors='replace')


def scannable(rel):
    name = rel.rsplit('/', 1)[-1]
    if JSON_SEC.search(name):
        return True
    # LICENSE text says "permission" and a .gitignore says "secret": prose, not code.
    return not (name in LOCKFILES or GENERATED.search(rel)
                or os.path.splitext(name)[1].lower() in CONTENT_EXT
                or name.upper().startswith(('LICENSE', 'COPYING', 'NOTICE', 'CHANGELOG'))
                or name.startswith('.gitignore') or name == '.gitattributes')


def category_hits(root, files):
    """{path: {category: matching lines}} for every code file with at least one hit."""
    hits = {}
    for rel in files:
        if not scannable(rel):
            continue
        text = read_head(root / rel)
        if text is None:
            continue
        lines, per = text.splitlines(), {}
        for cat, rx in (JSON_CATEGORIES if JSON_SEC.search(rel.rsplit('/', 1)[-1])
                        else CATEGORIES):
            if not rx.search(text):        # one pass over the blob before seven over lines
                continue
            n = sum(1 for ln in lines if rx.search(ln))
            if n:
                per[cat] = n
        if per:
            hits[rel] = per
    return hits


def dirs_of(files):
    """{directory: the file extensions under it, at any depth}."""
    seen = {}
    for f in files:
        parts = f.split('/')[:-1]
        ext = os.path.splitext(f)[1].lower()
        for i in range(len(parts)):
            seen.setdefault('/'.join(parts[:i + 1]), set()).add(ext)
    return seen


def is_surface(rel, per):
    """Where it sits plus one hit, or three hits in a strong category, or two categories."""
    if PATH_SIG.search(rel) or JSON_SEC.search(rel.rsplit('/', 1)[-1]):
        return True
    strong = max((n for c, n in per.items() if c in STRONG), default=0)
    return strong >= 3 or (len(per) >= 2 and sum(per.values()) >= 4)


def sec_section(files, hits, dirs):
    surfaces = {p: c for p, c in hits.items() if is_surface(p, c)}
    ranked = sorted(surfaces.items(), key=lambda kv: (-len(kv[1]), -sum(kv[1].values()), kv[0]))
    out = []
    for path, per in ranked[:25]:
        why = ', '.join(f'{c} {n}' for c, n in sorted(per.items(), key=lambda kv: (-kv[1], kv[0])))
        out.append(f'- `{path}` — {why}')
    extra = []
    for d in sorted(dirs):
        base = d.rsplit('/', 1)[-1]
        why = ('CI: runs with the repository secrets' if base == 'workflows'
               and d.endswith('.github/workflows') else SEC_DIRS.get(base))
        if why:
            extra.append(f'- `{d}/` — {why}')
    out += extra[:8]
    if not out:
        out = ['- none detected by scan_project.py — name them by hand if this repo has any']
    return [], [f'<!-- auto-detected {TODAY} by scan_project.py — a floor, not a ceiling; the '
                'global list still applies. Numbers are matching lines. -->'] + out


def layout_section(root, files):
    tops = {}
    for f in files:
        if '/' in f:
            tops.setdefault(f.split('/', 1)[0], []).append(f)
    rows = []
    for name, group in sorted(tops.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:12]:
        ext = {}
        for f in group:
            e = os.path.splitext(f)[1].lstrip('.').lower()
            if e:
                ext[e] = ext.get(e, 0) + 1
        top = sorted(ext.items(), key=lambda kv: (-kv[1], kv[0]))[:2]
        langs = ', '.join(f'{e} {n}' for e, n in top) or 'no extensions'
        rows.append(f'{name + "/":<18}{len(group)} files, main languages: {langs}')
    if not rows:
        rows = ['(no subdirectories — every tracked file is at the repo root)']
    total = git(root, 'rev-list', '--count', 'HEAD')
    log = git(root, 'log', '-200', '--name-only', '--pretty=format:')
    bullets = []
    # One commit is enough to say what that commit touched; a floor of five said nothing at
    # all on a repo three days old, which is exactly when /kit-init runs.
    if log is not None and total is not None and int(total.strip() or 0) >= 1:
        n_commits, counts = min(200, int(total.strip())), {}
        for ln in log.splitlines():
            p = ln.strip().replace('\\', '/')
            if p and p.rsplit('/', 1)[-1] not in LOCKFILES and p != 'CLAUDE.md':
                counts[p] = counts.get(p, 0) + 1
        for p, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:4]:
            bullets.append(f'- `{p}` — changed in {c} of the last {n_commits} commits')
    if not bullets:
        bullets = ['- nothing detected by scan_project.py — name the files most changes touch']
    return rows, [f'<!-- auto-detected {TODAY} by scan_project.py -->'] + bullets


def yaml_sdk(text):
    """`sdk:` under `environment:` only - a `sdk:` under dependencies is a package."""
    inside = False
    for ln in text.splitlines():
        if not ln[:1].isspace():
            inside = ln.strip().startswith('environment:')
            continue
        m = re.match(r'\s+sdk:\s*["\']?([^"\'\n]+)', ln)
        if inside and m:
            return m.group(1).strip()
    return None


def conventions_section(root, files):
    at_root = {f for f in files if '/' not in f}
    facts = []

    def text_of(name):
        return read_head(root / name) or '' if name in at_root else ''

    pkg = text_of('package.json')
    if pkg:
        try:                # a manifest mid-edit is absent, not a crash
            node = (json.loads(pkg).get('engines') or {}).get('node')
        except (ValueError, AttributeError, TypeError, KeyError):
            node = None
        if node:
            facts.append(f'Node {node} (package.json engines)')
    pyp = text_of('pyproject.toml')
    m = re.search(r'requires-python\s*=\s*["\']([^"\']+)', pyp)
    if m:
        facts.append(f'Python {m.group(1)} (pyproject requires-python)')
    m = re.search(r'^go\s+([\d.]+)', text_of('go.mod'), re.M)
    if m:
        facts.append(f'Go {m.group(1)} (go.mod)')
    sdk = yaml_sdk(text_of('pubspec.yaml'))
    if sdk:
        facts.append(f'Dart sdk {sdk} (pubspec.yaml)')
    m = re.search(r'edition\s*=\s*["\']([^"\']+)', text_of('Cargo.toml'))
    if m:
        facts.append(f'Rust edition {m.group(1)} (Cargo.toml)')
    for lock, pm in (('pnpm-lock.yaml', 'pnpm'), ('yarn.lock', 'yarn'),
                     ('package-lock.json', 'npm'), ('bun.lockb', 'bun'),
                     ('poetry.lock', 'poetry'), ('uv.lock', 'uv'), ('Pipfile.lock', 'pipenv')):
        if lock in at_root:
            facts.append(f'package manager {pm} ({lock})')
            break
    tools = []
    for label, hit in (
            ('formatter prettier', next((f for f in sorted(at_root) if f.startswith('.prettierrc')), None)),
            ('formatter/linter biome', 'biome.json' if 'biome.json' in at_root else None),
            ('linter ruff', 'ruff.toml' if 'ruff.toml' in at_root
             else ('pyproject.toml' if '[tool.ruff]' in pyp else None)),
            ('formatter black', 'pyproject.toml' if '[tool.black]' in pyp else None),
            ('linter eslint', next((f for f in sorted(at_root)
                                    if f.startswith('.eslintrc') or f.startswith('eslint.config.')), None)),
            ('analyzer dart', 'analysis_options.yaml' if 'analysis_options.yaml' in at_root else None),
            ('linter golangci-lint', next((f for f in ('.golangci.yml', '.golangci.yaml')
                                           if f in at_root), None)),
            ('formatter rustfmt', 'rustfmt.toml' if 'rustfmt.toml' in at_root else None),
            ('editorconfig', '.editorconfig' if '.editorconfig' in at_root else None)):
        if hit:
            tools.append(f'{label} ({hit})')
    facts += tools
    bullet = ('- ' + ', '.join(facts) if facts
              else '- nothing detected by scan_project.py; the code itself is the convention')
    return [], [f'<!-- auto-detected {TODAY} by scan_project.py -->', bullet]


def danger_section(files, hits, dirs, tracked):
    at_root = {f for f in files if '/' not in f}
    out = []
    for d in sorted(dirs):
        # A `migrations` directory under docs/ holds prose and an empty one holds nothing:
        # the rule is the suffix AND a file a migration runner would actually execute.
        if ('docs' not in d.split('/') and (dirs[d] & MIG_EXT)
                and any(d == s or d.endswith('/' + s) for s in MIG_DIRS)):
            out.append(f'- `{d}/` — migrations: run in order, never edit an applied one')
    out = out[:3]
    gen = [(r'\.g\.dart$', '*.g.dart', 'build_runner'),
           (r'\.freezed\.dart$', '*.freezed.dart', 'build_runner'),
           (r'\.pb\.(go|dart)$', '*.pb.*', 'protoc'), (r'_pb2\.py$', '*_pb2.py', 'protoc'),
           (r'\.generated\.', '*.generated.*', 'a generator')]
    found = []
    for rx, glob, by in gen:
        n = sum(1 for f in files if re.search(rx, f))
        if n:
            found.append(f'- `{glob}` — {n} generated files ({by}); never hand-edit, regenerate')
    out += found[:4]
    infra = []
    for f in sorted(files):
        if WORKFLOW.search(f):     # a workflow is CI, not a deploy script named one
            continue
        for rx, why in DEPLOY_FILES:
            if rx.search(f):
                infra.append(f'- `{f}` — {why}')
                break
    for d in sorted(dirs):
        why = INFRA_DIRS.get(d.rsplit('/', 1)[-1])
        if why:
            infra.append(f'- `{d}/` — {why}')
    infra += [f'- `{f}` — CI: runs on push with the repository secrets'
              for f in sorted(files) if WORKFLOW.search(f)]
    out += infra[:8]
    envs = [f for f in files if ENVFILE.search(f.rsplit('/', 1)[-1])]
    for f in sorted(envs)[:3]:
        out.append(f'- `{f}` — TRACKED IN GIT: a secret here is public' if tracked
                   else f'- `{f}` — secrets live here; never commit it')
    for f in sorted(at_root):
        if f in LOCKFILES:
            out.append(f'- `{f}` — hand edits break installs; only the package manager writes it')
    seeds = [f for f in files
             if SEED.search(f)
             or (re.search(r'(^|/)(seeds|fixtures)/', f) and 'db' in hits.get(f, {}))]
    for f in sorted(seeds)[:3]:
        out.append(f'- `{f}` — writes to a database: never run it against anything live')
    if not out:
        out = ['- nothing detected by scan_project.py — add what you learn']
    return [], [f'<!-- auto-detected {TODAY} by scan_project.py — evidence-based only -->'] + out


def sections(root):
    """The four sections, heading -> (fenced lines, bullet lines). No template prose here:
    the template owns that, and --apply only ever replaces the placeholder lines."""
    files = census(root)
    tracked = git(root, 'ls-files', '-z') is not None
    hits = category_hits(root, files)
    dirs = dirs_of(files)
    out = {HEADINGS[0]: sec_section(files, hits, dirs),
           HEADINGS[1]: layout_section(root, files),
           HEADINGS[2]: conventions_section(root, files),
           HEADINGS[3]: danger_section(files, hits, dirs, tracked)}
    return {h: (fenced, bullets + [END]) for h, (fenced, bullets) in out.items()}


def render(heading, fenced, bullets):
    """What stdout shows without --apply: the heading, then exactly what --apply would write."""
    out = [f'## {heading}', '']
    if fenced:
        out += ['```'] + fenced + ['```', '']
    return '\n'.join(out + bullets) + '\n\n'


def _nl(line):
    return line.rstrip('\r\n')


def bounds(lines, heading):
    """(start, end) of a `## heading` section. A `## ` line inside a fence does not end it."""
    start, fence = None, False
    for i, raw in enumerate(lines):
        s = _nl(raw)
        if s.startswith('```'):
            fence = not fence
            continue
        if fence:
            continue
        if s.rstrip() == '## ' + heading:
            start = i
        elif start is not None and s.startswith('## '):
            return start, i
    return (start, len(lines)) if start is not None else (None, None)


def runs(lines, start, end):
    """[(first, last + 1, inside_a_fence)] - the runs --apply may replace. A marker line
    swallows the lines under it, so a re-run refreshes its block instead of doubling it."""
    fence, flags = False, {}
    for i in range(start, end):
        if _nl(lines[i]).startswith('```'):
            fence = not fence
            flags[i] = None            # the fence delimiter itself is never replaced
        else:
            flags[i] = fence
    found, i = [], start
    while i < end:
        if flags[i] is None or not PLACEHOLDER.search(_nl(lines[i])):
            i += 1
            continue
        j = i + 1
        if MARKER in lines[i]:          # a previous run's block: up to its own end marker
            j = next((x + 1 for x in range(i + 1, end) if END in lines[x]), j)
        while j < end and flags[j] is not None and PLACEHOLDER.search(_nl(lines[j])):
            j += 1
        found.append((i, j, flags[i]))
        i = j
    return found


def apply(text, secs):
    """Rewrite the placeholder lines of each section. Returns (text, {heading: verb})."""
    lines = text.splitlines(keepends=True)
    eol = '\r\n' if lines and lines[0].endswith('\r\n') else '\n'
    open_end = bool(lines) and not lines[-1].endswith(('\n', '\r'))
    report = {}
    for h in HEADINGS:
        start, end = bounds(lines, h)
        if start is None:
            report[h] = 'absent'
            continue
        found = runs(lines, start, end)
        if not found:                  # a section a human filled in by hand
            report[h] = 'kept'
            continue
        fenced, bullets = secs[h]
        jobs = []
        in_fence = next((r for r in found if r[2]), None)
        in_prose = next((r for r in found if not r[2]), None)
        if fenced and in_fence:
            jobs.append((in_fence[0], in_fence[1], fenced))
        if bullets:
            if in_prose:
                jobs.append((in_prose[0], in_prose[1], bullets))
            else:                      # no bullet placeholder: land under the section's prose
                at = max(i for i in range(start, end) if _nl(lines[i]).strip()) + 1
                jobs.append((at, at, bullets))
        for a, b, new in sorted(jobs, reverse=True):
            lines[a:b] = [ln + eol for ln in new]
        report[h] = 'filled'
    out = ''.join(lines)
    if open_end and out.endswith(eol):
        out = out[:-len(eol)]
    return out, report


def main(argv):
    root = pathlib.Path(next((a for a in argv if not a.startswith('-')), '.')).resolve()
    secs = sections(root)
    if '--apply' not in argv:
        sys.stdout.write(''.join(render(h, *secs[h]) for h in HEADINGS))
        return 0
    cm = root / 'CLAUDE.md'
    if not cm.exists():
        print(f'scan_project: no CLAUDE.md in {root} — run /kit-init first')
        return 2
    try:
        raw = cm.read_bytes().decode('utf-8')
    except UnicodeDecodeError:
        print('scan_project: CLAUDE.md is not UTF-8; nothing written')
        return 2
    new, report = apply(raw, secs)
    cm.write_bytes(new.encode('utf-8'))
    for h in HEADINGS:
        verb = report[h]
        n = len(secs[h][0]) + len(secs[h][1])
        print(f'{h}: {verb}' + (f' ({n} lines)' if verb == 'filled' else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
