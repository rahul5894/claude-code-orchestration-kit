#!/usr/bin/env python3
"""Is THIS project set up for the kit, and is nothing in it fighting the global rules?

    python audit_project.py <repo>        # default: the current directory
    python ~/.claude/kit/audit_project.py . # the installed copy, from any repo

Everything the kit needs is global except one file: the project's CLAUDE.md, which must name
a measured FAST GATE. Everything a project might ADD can only make things worse when it
restates or overrides a global rule - it is re-paid by every subagent on every spawn, it
drifts, and Claude Code's local settings silently beat user settings. This script reads only;
it never edits. Exit 0 when clean, 1 otherwise.

Found the hard way, 2026-09-18/19: a local `outputStyle: Concise` that switched the whole
orchestrator off in one repo; two hand-written copies of the qartez rules that had drifted
from the global text; three MCP servers defined twice with different endpoints.
"""
import json
import os
import pathlib
import re
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except (AttributeError, OSError):
    pass

HOME = pathlib.Path(os.path.expanduser('~/.claude'))
USER_JSON = pathlib.Path(os.path.expanduser('~/.claude.json'))
# The qartez tools Claude Code can reach without QARTEZ_ENABLED_TIERS. Anything else named
# as a tool sends an agent at a call that does not exist. Slash commands (`/qartez_review`)
# are real MCP prompts and are NOT tools - the first draft of this check flagged them.
REACHABLE = {'qartez_explore', 'qartez_locate', 'qartez_map', 'qartez_grep', 'qartez_find',
             'qartez_read', 'qartez_outline', 'qartez_refs', 'qartez_deps', 'qartez_stats',
             'qartez_impact', 'qartez_tools'}
# Headings that belong to the GLOBAL rules. A project section under one of these is a copy.
GLOBAL_HEADINGS = re.compile(r'^##+\s*(qartez mcp|search preference|orchestration rules|'
                             r'review: recall|task buckets|the gate|honesty|read-only agents)',
                             re.I | re.M)
bad = []


def ok(cond, label, detail=''):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + ('' if cond else f'\n         -> {detail}'))
    if not cond:
        bad.append(label)


def load_json(p):
    try:
        return json.loads(pathlib.Path(p).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else '.').resolve()
name = root.name
print(f'=== {name} ===')

# 1. The one per-project file the kit needs.
cm = root / 'CLAUDE.md'
txt = cm.read_text(encoding='utf-8', errors='replace') if cm.exists() else ''
ok(bool(txt), 'has a CLAUDE.md', 'run /kit-init')
if txt:
    gate_row = re.search(r'FAST GATE[^\n]*', txt, re.I)
    ok(gate_row is not None, 'names a FAST GATE row', 'run /kit-init')
    if gate_row:
        ok(re.search(r'\d+(\.\d+)?\s*s\b', gate_row.group(0)) is not None,
           'the FAST GATE row states a measured time', gate_row.group(0)[:80])
    ok('Agents never run these' in txt, 'names the commands agents must NOT run')

# 2. Nothing in the project restates a global rule.
if txt:
    copies = [m.group(0).strip()[:60] for m in GLOBAL_HEADINGS.finditer(txt)]
    ok(not copies, 'no section that copies a global rule (paid on every spawn, drifts)',
       str(copies))
    # An ORDER is the defect ("use Grep for markdown"), not a mention. The kit's own template
    # says "`Grep` and `Glob` are denied on every path" - a mention-with-negation-after that a
    # window-before heuristic misread as an order. Match the imperative shape only.
    orders = [txt[max(0, m.start() - 10):m.end() + 30].replace('\n', ' ')
              for m in re.finditer(r'\b(?:use|run|call|try|prefer|via|with)\s+`?(?:Grep|Glob)`?\b', txt)]
    ok(not orders, 'does not order agents to use Grep/Glob (denied everywhere)', str(orders[:2]))
    named = {t for t in re.findall(r'(?<![\w/])qartez_[a-z_]+', txt)} - REACHABLE
    ok(not named, 'names only qartez tools Claude Code can reach', str(sorted(named)))

# 3. Local settings must not override the global kit.
for rel in ('.claude/settings.json', '.claude/settings.local.json'):
    d = load_json(root / rel)
    if d is None:
        continue
    ok('outputStyle' not in d,
       f'{rel}: no outputStyle override (it would switch the orchestrator off here)',
       str(d.get('outputStyle')))
    ok('worktree' not in d, f'{rel}: no worktree key (the kit sets it globally)')
    env = d.get('env') or {}
    ok(not any(k in env for k in ('CLAUDE_CODE_EFFORT_LEVEL', 'CLAUDE_CODE_SUBAGENT_MODEL_FORCE',
                                  'CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS')),
       f'{rel}: no env key that defeats the model pins', str(sorted(env)))

# 3b. Project skills must not shadow global ones. Found 2026-09-19: a project-local
# `.claude/skills/firecrawl` from June was overriding the newer global skill in that repo,
# and three skills were copied into two repos by hand (one had already diverged).
skills_dir = root / '.claude' / 'skills'
if skills_dir.exists():
    global_skills = {p.name for p in (HOME / 'skills').iterdir()} if (HOME / 'skills').exists() else set()
    local = {p.name for p in skills_dir.iterdir() if p.is_dir()}
    shadow = sorted(local & global_skills)
    ok(not shadow, '.claude/skills shadows no global skill (the local copy silently wins)', str(shadow))
    stray = sorted(p.name for p in skills_dir.iterdir() if p.is_file())
    ok(not stray, '.claude/skills holds no loose files (Claude Code ignores them; they are dead weight)',
       str(stray))

# 4. Project MCP config must not re-define a user-scope server.
user_servers = set(((load_json(USER_JSON) or {}).get('mcpServers') or {}))
proj = load_json(root / '.mcp.json')
if proj is not None:
    dupes = sorted(set(proj.get('mcpServers') or {}) & user_servers)
    ok(not dupes, '.mcp.json defines no server that is already at user scope', str(dupes))

# 5. The global side this project depends on is actually there.
ok((HOME / 'output-styles' / 'orchestrator.md').exists(), 'global orchestrator style installed')
ok(len(list((HOME / 'agents').glob('*.md'))) >= 6, 'six kit agents installed globally')
ok({'qartez', 'firecrawl', 'exa', 'context7'} <= user_servers,
   'qartez + the researcher web servers are at user scope',
   str(sorted({'qartez', 'firecrawl', 'exa', 'context7'} - user_servers)))

print(f"\n>>> {'CLEAN' if not bad else str(len(bad)) + ' PROBLEM(S)'}")
for b in bad:
    print('   ', b)
sys.exit(1 if bad else 0)
