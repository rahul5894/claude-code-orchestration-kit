#!/usr/bin/env python3
"""Live-state check: is the INSTALLED kit the kit in this repo, and does it hold together?

`validate_kit.py` is the fast gate and reads this repository only. This script reads
`~/.claude` as well, so it catches the class of defect the gate structurally cannot:
a stale install, a settings key the merge dropped, a roster row that drifted from the
agent file, an instruction no agent can carry out with the tools it holds.

Run it after any change to an agent file or to the installer. It writes nothing of its own,
but it does run `install.ps1` **twice**: once up front so the sections below judge the kit
rather than a stale copy of it, and once at the end, because only a second run can show the
installer reporting "unchanged". Budget for that: on a machine that already had a
`settings.json`, the first run may leave one `.bak-kit-*` file.

    python verify_live.py        # exits 0 on ALL CLEAR, 1 otherwise
"""
import datetime
import glob
import json
import os
import pathlib
import re
import subprocess
import sys

KIT = pathlib.Path(__file__).resolve().parent
HOME = pathlib.Path(os.path.expanduser('~/.claude'))
os.chdir(KIT)
bad = []

# A Windows console is cp1252, so printing a tool's UTF-8 output raises UnicodeEncodeError and
# kills the script mid-report. It happened here while reporting a real failure: the check
# caught the defect and then crashed trying to say so, which reads exactly like a pass.
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except (AttributeError, OSError):
    pass


def ok(cond, label, detail=''):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + ('' if cond else f'   -> {detail}'))
    if not cond:
        bad.append(label)


def fm(p):
    """Frontmatter as a flat dict, plus the whole file. Good enough: the kit's frontmatter
    is one level deep and has no multi-line values."""
    s = pathlib.Path(p).read_text(encoding='utf-8')
    d = {}
    for ln in s.split('\n---', 1)[0].splitlines():
        if ':' in ln and not ln.startswith('#'):
            k, v = ln.split(':', 1)
            d[k.strip()] = v.strip()
    return d, s


def norm(s):
    return s.replace('\r\n', '\n')


def install():
    """Run the installer. Reads output as UTF-8 because Windows decodes subprocess pipes as
    cp1252 by default: one box-drawing character kills the reader thread and hands back an
    EMPTY stdout, which reads as "the tool said nothing" rather than as an error.

    A machine with only Windows PowerShell 5.1 has no `pwsh`, and the
    resulting FileNotFoundError used to end the whole script with a traceback and no section
    list - on exactly the fresh machine this file exists to check."""
    try:
        return subprocess.run(['pwsh', '-File', 'install.ps1'], capture_output=True, text=True, encoding='utf-8', errors='replace')
    except OSError as e:
        ok(False, 'pwsh (PowerShell 7+) is on PATH to run install.ps1', str(e))
        return subprocess.CompletedProcess([], 1, '', str(e))


print("=== A. every instruction is executable with the tools the agent holds ===")
# An order to run a CLI, or to read git, is dead text in an agent with no shell. Both have
# shipped before. A nearby disclaimer ("you have no shell, so you cannot run qmd") is fine.
NEEDS = [(r'\bqmd\b', 'Bash'), (r'`git (?:diff|status)', 'Bash'),
         (r'run the (?:project\'s )?(?:fast )?gate', 'Bash')]
DISCLAIMS = ('cannot', 'no shell', 'you have no', 'never run', 'do not run')
for p in sorted(glob.glob('core/agents/*.md')):
    d, s = fm(p)
    tools = [t.strip() for t in d.get('tools', '').split(',')]
    txt = (s.split('\n---', 1)[1] if '\n---' in s else s) + ' ' + d.get('initialPrompt', '')
    probs = [m.group(0) for pat, tool in NEEDS if tool not in tools
             for m in re.finditer(pat, txt, re.I)
             if not any(w in txt[max(0, m.start() - 120):m.start() + 80].lower() for w in DISCLAIMS)]
    ok(not probs, f"{os.path.basename(p)}: no order it cannot carry out", str(probs[:2]))

print("\n=== B. no tool granted that the guard always denies ===")
# qartez-guard denies Grep and Glob on every path and file type, index or no index
# (verified directly against .md, .json, .ps1 and an unindexed directory). Granting them
# costs a wasted turn per call and teaches the agent its search failed.
for p in sorted(glob.glob('core/agents/*.md')):
    d, _ = fm(p)
    tools = [t.strip() for t in d.get('tools', '').split(',')]
    ok('Grep' not in tools and 'Glob' not in tools, f"{os.path.basename(p)}: no dead Grep/Glob")

pairs = [(p, HOME / 'agents' / os.path.basename(p)) for p in glob.glob('core/agents/*.md')]
pairs += [(p, HOME / 'commands' / os.path.basename(p)) for p in glob.glob('core/commands/*.md')]
pairs += [(p, HOME / 'output-styles' / os.path.basename(p))
          for p in glob.glob('core/output-styles/*.md')]
pairs += [(p, HOME / 'skills' / pathlib.Path(p).parent.name / 'SKILL.md')
          for p in glob.glob('core/skills/*/SKILL.md')]


def drifted():
    return [dst.name for src, dst in pairs
            if not dst.exists()
            or norm(pathlib.Path(src).read_text(encoding='utf-8')) != norm(
                dst.read_text(encoding='utf-8'))]


# Snapshot BEFORE installing. Taken afterwards, this check could only ever prove the copy
# succeeded - it would repair a three-version-old install and then report "no stale install",
# which is the one thing it exists to tell you about.
was_stale = drifted()

# Install now, so every section below judges the kit rather than an out-of-date copy of it.
# Section F then runs the installer again: only a SECOND run can prove idempotency, because
# the first legitimately reports "replaced" whenever the repo moved since the last install.
first_install = install()
ok(first_install.returncode == 0, 'install.ps1 exits 0', first_install.stderr.strip()[:200])

print("\n=== C. installed == repo ===")
if was_stale:
    print(f"  NOTE  {len(was_stale)} file(s) were stale before this run and have been "
          f"reinstalled: {', '.join(was_stale[:4])}"
          + (f" (+{len(was_stale) - 4} more)" if len(was_stale) > 4 else ''))
ok(not drifted(), f"all {len(pairs)} installed files byte-identical to repo after install",
   str(drifted()[:3]))
# The compare above sees SKILL.md only. `Copy-Item -Recurse` into a folder that already
# exists can nest a subfolder inside itself (references/references) and never removes a file
# the repo dropped, so the whole tree is compared by relative path.


def _skill_tree(base, names):
    return {f'{n}/{f.relative_to(base / n).as_posix()}'
            for n in names for f in (base / n).rglob('*') if f.is_file()}


_skill_names = [p.name for p in pathlib.Path('core/skills').glob('*') if p.is_dir()]
_repo_tree = _skill_tree(pathlib.Path('core/skills'), _skill_names)
_inst_tree = _skill_tree(HOME / 'skills', [n for n in _skill_names if (HOME / 'skills' / n).is_dir()])
ok(_repo_tree == _inst_tree, 'installed skill trees match the repo (no nested or stale files)',
   str(sorted(_repo_tree ^ _inst_tree)[:5]))

print("\n=== C2. Claude Code itself accepts every installed component ===")
# The authoritative loader, not our parser. Two agents once shipped with an unquoted ": " in
# initialPrompt: valid to a line-splitter, a nested mapping to YAML, and per this command
# "at runtime this agent does not load at all". Two of six agents would simply not exist in
# the next session, with every other check green.
try:
    _v = subprocess.run(['claude', 'plugin', 'validate', str(HOME)],
                        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=300)
    # `or ''` on both streams: a shim that writes nothing leaves these None, and the crash
    # that follows is the same defect this file was just fixed for - an unhandled failure
    # mode reported as a traceback instead of a named FAIL.
    _out = (_v.stdout or '') + (_v.stderr or '')
    _errs = [l.strip() for l in _out.splitlines() if '❯' in l and 'symlink' not in l]
    ok('Validation passed' in _out and not _errs,
       'claude plugin validate accepts the installed agents, skills and commands',
       str(_errs[:2]) if _errs else _out.strip()[-200:] or 'no output from the validator')
except (OSError, subprocess.TimeoutExpired) as e:
    ok(False, 'claude plugin validate could run', f'{type(e).__name__}: {e}')

print("\n=== C3. the installer survives the states a real machine arrives in ===")
# Each of these was a crash or a silent loss before it was tested. They run against a throwaway
# HOME, never yours.
import shutil        # noqa: E402  - local to this section
import tempfile      # noqa: E402


def install_into(setup):
    """Install into a scratch HOME prepared by `setup(dir)`; return (rc, stderr, dir)."""
    tmp = tempfile.mkdtemp(prefix='kit-probe-')
    d = pathlib.Path(tmp) / '.claude'
    d.mkdir(parents=True)
    setup(d)
    env = dict(os.environ, CLAUDE_CONFIG_DIR=str(d), USERPROFILE=tmp, HOME=tmp)
    r = subprocess.run(['pwsh', '-File', 'install.ps1'], capture_output=True, text=True,
                       encoding='utf-8', errors='replace', env=env)
    return r, d, tmp


def _policy_applied(d):
    """Step 3b's own probe: without a state that HAS an enabledPlugins map, the plugin policy
    loop never executes in any of these runs and could be dead code."""
    _p = json.loads((d / 'settings.json').read_text(encoding='utf-8')).get('enabledPlugins') or {}
    return ((_p.get('simple-english@simple-english') is False
             and _p.get('ponytail@ponytail') is True), str(_p)[:200])


for _label, _setup, _extra, _verify in [
        ('a machine with nothing installed yet', lambda d: None, None, None),
        # Get-Content -Raw yields $null here, not '': every later .Replace() threw.
        ('an empty CLAUDE.md', lambda d: (d / 'CLAUDE.md').write_bytes(b''), None, None),
        ('an empty settings.json', lambda d: (d / 'settings.json').write_bytes(b''), None, None),
        # A file we cannot parse must be backed up and reported, never quietly discarded.
        ('a corrupt settings.json',
         lambda d: (d / 'settings.json').write_text('{ not json', encoding='utf-8'),
         'not json', None),
        ('a settings.json that enables a disabled plugin',
         lambda d: (d / 'settings.json').write_text(
             '{"enabledPlugins": {"simple-english@simple-english": true, "ponytail@ponytail": true}}',
             encoding='utf-8'),
         None, _policy_applied)]:
    _r, _d, _tmp = install_into(_setup)
    _msg = (_r.stderr or '').strip().replace('\n', ' ')[:150]
    if _extra:
        _kept = any(_extra in p.read_text(encoding='utf-8', errors='replace')
                    for p in _d.glob('settings.json*'))
        ok(_kept, f'installer preserves {_label} somewhere it can be recovered from', _msg)
    else:
        ok(_r.returncode == 0, f'installer survives {_label}', f'rc={_r.returncode} {_msg}')
    if _verify:
        try:
            _cond, _detail = _verify(_d)
        except (OSError, ValueError, AttributeError) as e:
            _cond, _detail = False, f'{type(e).__name__}: {e}'
        ok(_cond, 'installer disables a policy-disabled plugin and leaves an allowed one on',
           _detail)
    shutil.rmtree(_tmp, ignore_errors=True)

print("\n=== C4. qartez, which every agent's search depends on ===")
# An upgraded qartez whose server was never restarted serves the pre-upgrade behaviour to
# every agent while the version string says otherwise - silent, and invisible to every other
# check here. The doctor's own `restart_required_after_upgrade` is a hardcoded `true` in
# 0.27.0 (`qartez-mcp/src/doctor.rs:25`, never reassigned), so it is not consulted: staleness
# is computed below from the running process start times against the binary's mtime.
try:
    _q = subprocess.run(['qartez', 'doctor', '--format', 'json'], capture_output=True,
                        text=True, encoding='utf-8', errors='replace', timeout=180)
    _doc = json.loads(_q.stdout or '{}')
except (OSError, subprocess.TimeoutExpired, ValueError) as e:
    _doc = None
    ok(False, 'qartez doctor could run', f'{type(e).__name__}: {e}')
if _doc:
    print(f"  NOTE  qartez {_doc.get('version')} · index "
          f"{(_doc.get('index') or {}).get('symbols')} symbols, "
          f"coverage {(_doc.get('index') or {}).get('coverage')}")
    _exe = _doc.get('executable')
    try:
        _mtime = datetime.datetime.fromtimestamp(os.path.getmtime(_exe),
                                                 datetime.timezone.utc)
    except (OSError, TypeError) as e:
        _mtime = None
        ok(False, 'qartez executable on disk', f'{type(e).__name__}: {e}')
    if _mtime:
        # ponytail: mtime is the ceiling here - an installer that PRESERVES timestamps can
        # leave the binary older than a server started before the upgrade, and that staleness
        # is invisible to this comparison. Version-stamping the running server would fix it.
        # `LIKE 'qartez%'`, not `='qartez.exe'`: the server also runs as qartez-mcp.exe.
        _ps = subprocess.run(['powershell', '-NoProfile', '-Command',
                              'Get-CimInstance Win32_Process -Filter "Name LIKE \'qartez%\'" | '
                              "ForEach-Object { $_.CreationDate.ToUniversalTime().ToString('o') }"],
                             capture_output=True, text=True, encoding='utf-8',
                             errors='replace', timeout=30)
        if _ps.returncode != 0 or (_ps.stderr or '').strip():
            # A failed PowerShell call returns no lines, which reads exactly like "nothing is
            # running" - so it must be a FAILED CHECK, not a NOTE and not a silent pass.
            ok(False, 'qartez process list readable via Get-CimInstance',
               (_ps.stderr or '')[:200])
        else:
            _starts = []
            for _ln in (_ps.stdout or '').splitlines():
                _ln = _ln.strip()
                if not _ln:
                    continue
                try:
                    _starts.append(datetime.datetime.fromisoformat(
                        _ln[:-1] + '+00:00' if _ln.endswith('Z') else _ln))
                except ValueError:
                    continue
            if not _starts:
                print("  NOTE  no qartez.exe running right now (nothing to be stale)")
            else:
                _stale = [t for t in _starts if t < _mtime]
                ok(not _stale,
                   'every running qartez.exe started after the binary on disk was written',
                   'RESTART Claude Code: a qartez server older than the installed binary is '
                   'serving agents')
    # A project-local skill silently overrides the global one the kit relies on.
    ok(not (_doc.get('host_integration') or {}).get('local_skill_shadow'),
       'no project-local qartez skill shadowing the global one')

print("\n=== C5. no project silently switches the kit off ===")
# A project-local `outputStyle` BEATS the user-level one, so one line in one repo's
# .claude/settings.local.json disables the whole orchestrator there - roster, delegation
# threshold, model pinning - with nothing anywhere reporting it. Proven 2026-09-19: in the
# one repo that still had it, the session transcript showed "Concise style loaded: YES,
# orchestrator style loaded: NO". audit_project.py catches it per repo; this catches it
# across every repo at once, which is the only way you would notice.
KILLERS = ('CLAUDE_CODE_EFFORT_LEVEL', 'CLAUDE_CODE_SUBAGENT_MODEL_FORCE',
           'CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS', 'CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH')
try:
    _dis_ids = set(json.loads(pathlib.Path('core/plugins.json').read_text(encoding='utf-8'))['disable'])
except (OSError, ValueError, KeyError, TypeError):
    _dis_ids = set()
_offenders = []
_scanned = 0
for _proj in sorted(pathlib.Path(r'D:\Projects').glob('*')) if pathlib.Path(r'D:\Projects').is_dir() else []:
    for _rel in ('.claude/settings.json', '.claude/settings.local.json'):
        _f = _proj / _rel
        if not _f.is_file():
            continue
        _scanned += 1
        try:
            _d = json.loads(_f.read_text(encoding='utf-8'))
        except ValueError:
            _offenders.append(f'{_proj.name}/{_rel}: unparseable')
            continue
        if 'outputStyle' in _d:
            _offenders.append(f'{_proj.name}/{_rel}: outputStyle={_d["outputStyle"]!r} (kit OFF there)')
        for _k in KILLERS:
            if _k in (_d.get('env') or {}):
                _offenders.append(f'{_proj.name}/{_rel}: env.{_k}={_d["env"][_k]!r}')
        # A project file may re-enable a plugin the kit disables globally; the installer only
        # ever writes the user-level settings.json, so nothing else would report it.
        _ep = _d.get('enabledPlugins')
        if isinstance(_ep, dict):
            _offenders += [f'{_proj.name}/{_rel}: enabledPlugins[{_p}]=true (policy disables it)'
                           for _p, _v in _ep.items() if _v is True and _p in _dis_ids]
ok(not _offenders, f'none of the {_scanned} project settings files overrides the kit',
   '; '.join(_offenders[:4]))

print("\n=== C6. plugins ===")
# Claude Code has no per-plugin hook switch (hooks.md offers only `disableAllHooks`), so a
# plugin whose SessionStart, UserPromptSubmit or Stop hook fires in every session is either
# reviewed and allowed, or disabled whole. Nothing else would report one: a new plugin that
# injects 700 tokens of reply rules into every session just makes the orchestrator quietly
# worse. core/plugins.json holds the verdicts, install.ps1 applies `disable`, and this names
# anything in neither map.
SESSION_EVENTS = ('SessionStart', 'UserPromptSubmit', 'Stop')
# Every event Claude Code dispatches. A hooks file whose top level IS the event map (no
# `hooks` wrapper) is recognised by these keys - otherwise it reads as "declares no hooks".
HOOK_EVENTS = SESSION_EVENTS + ('PreToolUse', 'PostToolUse', 'SubagentStart', 'SubagentStop',
                                'SessionEnd', 'PreCompact', 'Notification')


def _enabled_plugins(p):
    """`enabledPlugins` from a settings file; {} when it is missing or unreadable."""
    try:
        return json.loads(p.read_text(encoding='utf-8')).get('enabledPlugins') or {}
    except (OSError, ValueError, AttributeError):
        return {}


def _event_map(root, decl):
    """(events, escaped_path) for a manifest's `hooks` value, in every shape it can take:
    an inline event map, one path, a list of paths, or nothing (then hooks/hooks.json)."""
    if isinstance(decl, dict):
        return decl, None           # inline in the manifest: the event map itself
    files = ([decl] if isinstance(decl, str)
             else [x for x in decl if isinstance(x, str)] if isinstance(decl, list)
             else ['hooks/hooks.json'] if (root / 'hooks' / 'hooks.json').is_file()
             else [])
    events = {}
    for f in files:
        # ${CLAUDE_PLUGIN_ROOT} is how a plugin spells its own root. Left unexpanded the path
        # never resolves, and a plugin that hooks every session reads as hooking nothing.
        resolved = (root / f.replace('${CLAUDE_PLUGIN_ROOT}', str(root))).resolve()
        if resolved != root.resolve() and root.resolve() not in resolved.parents:
            return None, f          # a declared path outside the plugin root is not read
        if not resolved.is_file():
            continue
        _j = json.loads(resolved.read_text(encoding='utf-8'))
        events.update(_j.get('hooks') if isinstance(_j, dict) and isinstance(_j.get('hooks'), dict)
                      else {k: v for k, v in _j.items() if k in HOOK_EVENTS}
                      if isinstance(_j, dict) else {})
    return events, None


try:
    _pol = json.loads(pathlib.Path('core/plugins.json').read_text(encoding='utf-8'))
    _dis, _allowed = _pol['disable'], _pol['allow']
except (OSError, ValueError, KeyError) as e:
    # The policy file IS this section: without it there is nothing to judge against, and a
    # traceback here would skip D, E and F as well.
    _dis = _allowed = None
    ok(False, 'core/plugins.json readable with disable and allow maps', f'{type(e).__name__}: {e}')
# A local enable beats the user-level one, so policy must be judged against the merge.
_en = dict(_enabled_plugins(HOME / 'settings.json'))
_en.update(_enabled_plugins(HOME / 'settings.local.json'))
try:
    _inst = json.loads((HOME / 'plugins' / 'installed_plugins.json')
                       .read_text(encoding='utf-8')).get('plugins') or {}
except (OSError, ValueError):
    _inst = {}
if _dis is None:
    print("  NOTE  C6 skipped: core/plugins.json could not be read")
elif not _inst:
    print("  NOTE  no installed plugins found under ~/.claude/plugins - nothing to check")
else:
    _verdicts = []
    for _pid in sorted(k for k, v in _en.items() if v is True):
        _entries = _inst.get(_pid) or []
        if not _entries:
            continue    # enabled in settings but not installed: no hook of its can run
        # Every install entry, not just the first: a second copy of the same plugin can
        # declare hooks the first does not, and only the union of them is the real answer.
        _events, _skip = {}, False
        for _entry in _entries:
            try:
                _root = pathlib.Path(_entry.get('installPath') or '.')
                _manifest = _root / '.claude-plugin' / 'plugin.json'
                # No manifest at all is not a broken read: gopls-lsp ships only LICENSE +
                # README (the marketplace copy too), so it cannot register a hook.
                if not _manifest.is_file():
                    print(f"  NOTE  {_pid}: no plugin.json at its install path; only hooks/hooks.json is read")
                _h = json.loads(_manifest.read_text(encoding='utf-8')).get('hooks') if _manifest.is_file() else None
                _e, _bad = _event_map(_root, _h)
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
                ok(False, f'{_pid} manifest readable', f'{type(e).__name__}: {e}')
                _skip = True
                break
            if _bad:
                ok(False, f'{_pid} hooks path stays inside the plugin root', str(_bad))
                _skip = True
                break
            _events.update(_e or {})
        if _skip:
            continue
        if _pid in _dis:
            ok(False, f'{_pid} is still enabled; policy disables it', 'run install.ps1')
        _sess = [e for e in SESSION_EVENTS if e in _events]
        if not _sess:
            continue
        _verdict = 'disabled' if _pid in _dis else 'allowed' if _pid in _allowed else 'unreviewed'
        if _verdict == 'unreviewed':
            ok(False, f'{_pid} injects into every session and is unreviewed',
               'add it to core/plugins.json allow or disable, then run install.ps1')
        _verdicts.append(f"{_pid} [{'+'.join(_sess)}] {_verdict}")
    print('  NOTE  session-level hooks: ' + ('; '.join(_verdicts) if _verdicts
                                             else 'none among the enabled plugins'))

print("\n=== D. settings live ===")
# A missing or hand-broken settings.json is a FAILED CHECK, not a traceback: the setup doc
# tells a fresh-machine reader this script prints ALL CLEAR or names what is wrong, and a
# stack trace names nothing and skips every section after it.
try:
    s = json.loads((HOME / 'settings.json').read_text(encoding='utf-8'))
except (OSError, ValueError) as e:
    s = {}
    ok(False, 'settings.json exists and parses', f'{type(e).__name__}: {e}')
for label, got, want in [
        ('outputStyle', s.get('outputStyle'), 'orchestrator'),
        ('fable effort', s.get('modelSettings', {}).get('claude-fable-5-1', {}).get('effortLevel'), 'high'),
        ('opus effort', s.get('modelSettings', {}).get('claude-opus-5', {}).get('effortLevel'), 'xhigh'),
        ('subagent cache TTL', s.get('subagentPromptCacheTtl'), '1h'),
        ('agent teams off', s.get('env', {}).get('CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS'), '0'),
        ('spawn depth', s.get('env', {}).get('CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH'), '1')]:
    ok(got == want, f"{label} = {want}", str(got))
# Absent is fine: the plugin was never installed on this machine, and the installer only
# writes `false` for ids the user's settings already name. Only `true` is the failure.
ok((s.get('enabledPlugins') or {}).get('simple-english@simple-english') is not True,
   'simple-english plugin not enabled (its skill is slash-only)',
   f"{(s.get('enabledPlugins') or {}).get('simple-english@simple-english')!r} - run install.ps1")
# An explicit `model: fable` spawn would otherwise spend Fable quota on a subagent seat.
ok(all(r in s.get('permissions', {}).get('deny', [])
       for r in ('Agent(model:fable)', 'Agent(model:claude-fable-5-1)')),
   'settings deny an explicit Fable subagent',
   str(s.get('permissions', {}).get('deny', [])))
# maxEffortLevel caps every frontmatter pin with no per-agent error. Checking only the top
# level missed it nested under a model, which is exactly where it would be set.
_caps = (['(top level)'] if 'maxEffortLevel' in s else []) + [
    f'modelSettings.{k}' for k, v in (s.get('modelSettings') or {}).items()
    if isinstance(v, dict) and 'maxEffortLevel' in v]
ok(not _caps, 'no maxEffortLevel silently capping the pins', str(_caps))
# The decisions injector is only load-bearing once it is REGISTERED: a hook that exists on disk
# and in no settings file injects nothing, and nothing else here would say so.
_ss = (s.get('hooks', {}) or {}).get('SubagentStart', []) or []
ok(any('kit-subagent-start.py' in h.get('command', '')
       for e in _ss for h in (e.get('hooks', []) or [])),
   'SubagentStart injector registered live', str(_ss)[:200])
ok(any(e.get('matcher') == 'builder|refuter|verifier|debugger|researcher'
       for e in _ss for h in (e.get('hooks', []) or [])
       if 'kit-subagent-start.py' in h.get('command', '')),
   'SubagentStart injector matcher = builder|refuter|verifier|debugger|researcher',
   str([e.get('matcher') for e in _ss])[:200])

print("\n=== E. roster table matches every agent file ===")
orch = (HOME / 'output-styles' / 'orchestrator.md').read_text(encoding='utf-8')
for p in sorted(glob.glob('core/agents/*.md')):
    d, _ = fm(p)
    row = re.search(rf"\|\s*\*?\*?`?{re.escape(d.get('name', ''))}`?\*?\*?\s*\|\s*\*?\*?([a-z]+)\*?\*?", orch)
    ok(row is not None and row.group(1) == d.get('model'),
       f"roster row = {d.get('name')}.md ({d.get('model')})",
       row.group(1) if row else 'no row')

print("\n=== F. gate, installer idempotency ===")
r = subprocess.run([sys.executable, 'validate_kit.py'], capture_output=True, text=True, encoding='utf-8', errors='replace')
tally = [l for l in r.stdout.splitlines() if l.startswith('checks run')]
ok(r.returncode == 0, f"validate_kit.py exits 0 -- {tally[-1] if tally else 'no tally line'}",
   r.stdout.strip().splitlines()[-3:])
# The installer must report what it actually did. It compared raw text against an
# LF-normalized file once, so it rewrote the block every run and "replaced" meant nothing.
# This is the run AFTER the one at the top of this script, so it is the one that can prove
# idempotency: a tree already installed must report unchanged.
r2 = install()
said = [l for l in r2.stdout.splitlines() if 'unchanged' in l or 'kit block' in l or 'settings.json' in l]
ok(r2.returncode == 0 and sum('unchanged' in l for l in said) == 2,
   'installer reports unchanged on an already-installed tree', said)
# The "fully global" pieces: the SessionStart notice and the two files /kit-init reads from
# ~/.claude/kit. Without them a new project starts with no gate and nothing says so.
ok('kit-session-start self-check: 8/8 passed' in r2.stdout,
   'kit-session-start self-check 8/8',
   [l for l in r2.stdout.splitlines() if 'kit-session-start' in l])
for _kf in ('project-template.md', 'audit_project.py', 'scan_project.py'):
    ok((HOME / 'kit' / _kf).exists(), f'~/.claude/kit/{_kf} published for /kit-init')
_hk = subprocess.run([sys.executable, str(HOME / 'hooks' / 'kit-session-start.py'), '--check', str(KIT)],
                     capture_output=True, text=True, encoding='utf-8', errors='replace')
ok('FAST GATE' not in (_hk.stdout or ''),
   'the installed SessionStart hook is quiet in this repo (it has a FAST GATE row)',
   (_hk.stdout or '')[:120])
# The INSTALLED injector, not the checkout's: a half-copied or older one would emit malformed
# JSON into every spawn's context, and a spawn is the one place that is never watched.
_ss_hk = subprocess.run([sys.executable, str(HOME / 'hooks' / 'kit-subagent-start.py'),
                         '--check', str(KIT)],
                        capture_output=True, text=True, encoding='utf-8', errors='replace')
_ss_out = (_ss_hk.stdout or '').strip()
try:
    _ss_ok = not _ss_out or json.loads(_ss_out).get(
        'hookSpecificOutput', {}).get('hookEventName') == 'SubagentStart'
except ValueError:
    _ss_ok = False
ok(_ss_ok, 'the installed SubagentStart injector emits nothing or a well-formed context',
   _ss_out[:160])
print("  NOTE  per-project state is checked by `python audit_project.py <repo>`, not here")
# These counts are pinned on purpose: a suite that silently shrinks is the failure this
# catches. Bump them WITH the test, never to make a red line green.
ok('83/83 passed' in r2.stdout, 'md-guard self-check 83/83',
   [l for l in r2.stdout.splitlines() if 'md-guard' in l])
ok('kit-subagent-report self-check: 10/10 passed' in r2.stdout,
   'kit-subagent-report self-check 10/10',
   [l for l in r2.stdout.splitlines() if 'kit-subagent-report' in l])
ok('kit-subagent-start self-check: 15/15 passed' in r2.stdout,
   'kit-subagent-start self-check 15/15',
   [l for l in r2.stdout.splitlines() if 'kit-subagent-start' in l])
ok('scan-project self-check: 38/38 passed' in r2.stdout,
   'scan-project self-check 38/38',
   [l for l in r2.stdout.splitlines() if 'scan-project' in l])

print('\n>>> ALL CLEAR' if not bad else '\n>>> PROBLEMS:\n  ' + '\n  '.join(bad))
sys.exit(1 if bad else 0)
