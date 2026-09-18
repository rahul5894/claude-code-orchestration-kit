#!/usr/bin/env python3
"""Live-state check: is the INSTALLED kit the kit in this repo, and does it hold together?

`validate_kit.py` is the fast gate and reads this repository only. This script reads
`~/.claude` as well, so it catches the class of defect the gate structurally cannot:
a stale install, a settings key the merge dropped, a roster row that drifted from the
agent file, an instruction no agent can carry out with the tools it holds.

Run it after `install.ps1`, and after any change to an agent file or to the installer.
It writes nothing except through `install.ps1`, which it runs once to prove idempotency.

    python verify_live.py        # exits 0 on ALL CLEAR, 1 otherwise
"""
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

# Install first, so the sections below judge the kit rather than an out-of-date copy of it.
# Section F then runs the installer again: only a SECOND run can prove idempotency, because
# the first legitimately reports "replaced" whenever the repo moved since the last install.
first_install = subprocess.run(['pwsh', '-File', 'install.ps1'], capture_output=True, text=True)
ok(first_install.returncode == 0, 'install.ps1 exits 0', first_install.stderr.strip()[:200])

print("\n=== C. installed == repo ===")
pairs = [(p, HOME / 'agents' / os.path.basename(p)) for p in glob.glob('core/agents/*.md')]
pairs += [(p, HOME / 'commands' / os.path.basename(p)) for p in glob.glob('core/commands/*.md')]
pairs += [(p, HOME / 'output-styles' / os.path.basename(p))
          for p in glob.glob('core/output-styles/*.md')]
pairs += [(p, HOME / 'skills' / pathlib.Path(p).parent.name / 'SKILL.md')
          for p in glob.glob('core/skills/*/SKILL.md')]
stale = [str(dst) for src, dst in pairs
         if not dst.exists() or norm(pathlib.Path(src).read_text(encoding='utf-8')) != norm(dst.read_text(encoding='utf-8'))]
ok(not stale, f"all {len(pairs)} installed files byte-identical to repo", stale[:3])

print("\n=== D. settings live ===")
s = json.loads((HOME / 'settings.json').read_text(encoding='utf-8'))
for label, got, want in [
        ('outputStyle', s.get('outputStyle'), 'orchestrator'),
        ('fable effort', s.get('modelSettings', {}).get('claude-fable-5-1', {}).get('effortLevel'), 'high'),
        ('opus effort', s.get('modelSettings', {}).get('claude-opus-5', {}).get('effortLevel'), 'xhigh'),
        ('subagent cache TTL', s.get('subagentPromptCacheTtl'), '1h'),
        ('agent teams off', s.get('env', {}).get('CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS'), '0'),
        ('spawn depth', s.get('env', {}).get('CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH'), '1')]:
    ok(got == want, f"{label} = {want}", str(got))
# maxEffortLevel caps every frontmatter pin with no per-agent error.
ok('maxEffortLevel' not in s, 'no maxEffortLevel silently capping the pins')

print("\n=== E. roster table matches every agent file ===")
orch = (HOME / 'output-styles' / 'orchestrator.md').read_text(encoding='utf-8')
for p in sorted(glob.glob('core/agents/*.md')):
    d, _ = fm(p)
    row = re.search(rf"\|\s*\*?\*?`?{re.escape(d.get('name', ''))}`?\*?\*?\s*\|\s*\*?\*?([a-z]+)\*?\*?", orch)
    ok(row is not None and row.group(1) == d.get('model'),
       f"roster row = {d.get('name')}.md ({d.get('model')})",
       row.group(1) if row else 'no row')

print("\n=== F. gate, installer idempotency ===")
r = subprocess.run([sys.executable, 'validate_kit.py'], capture_output=True, text=True)
tally = [l for l in r.stdout.splitlines() if l.startswith('checks run')]
ok(r.returncode == 0, f"validate_kit.py exits 0 -- {tally[-1] if tally else 'no tally line'}",
   r.stdout.strip().splitlines()[-3:])
# The installer must report what it actually did. It compared raw text against an
# LF-normalized file once, so it rewrote the block every run and "replaced" meant nothing.
# This is the run AFTER the one at the top of this script, so it is the one that can prove
# idempotency: a tree already installed must report unchanged.
r2 = subprocess.run(['pwsh', '-File', 'install.ps1'], capture_output=True, text=True)
said = [l for l in r2.stdout.splitlines() if 'unchanged' in l or 'kit block' in l or 'settings.json' in l]
ok(r2.returncode == 0 and sum('unchanged' in l for l in said) == 2,
   'installer reports unchanged on an already-installed tree', said)
ok('24/24 passed' in r2.stdout, 'md-guard self-check 24/24',
   [l for l in r2.stdout.splitlines() if 'md-guard' in l])

print('\n>>> ALL CLEAR' if not bad else '\n>>> PROBLEMS:\n  ' + '\n  '.join(bad))
sys.exit(1 if bad else 0)
