import re, glob, os, sys, collections

SEP = chr(92)
fails = []
checks = 0


def chk(cond, label, detail=''):
    global checks
    checks += 1
    print(('PASS  ' if cond else 'FAIL  ') + label + (f'  -> {detail}' if (detail and not cond) else ''))
    if not cond:
        fails.append(label)


def slash(p):
    return p.replace(SEP, '/')


def fm(path):
    s = open(path, encoding='utf-8').read()
    if not s.startswith('---'):
        return None, s
    end = s.index(chr(10) + '---', 3)
    d = {}
    for ln in s[3:end].strip().split(chr(10)):
        if ':' in ln:
            k, v = ln.split(':', 1)
            d[k.strip()] = v.strip()
    return d, s


files = sorted(slash(f) for f in glob.glob('**/*.md', recursive=True))

print('=== 1. AGENT FRONTMATTER — docs-valid values only ===')
MODELS = {'sonnet', 'opus', 'haiku', 'fable', 'inherit'}
EFFORT = {'low', 'medium', 'high', 'xhigh', 'max'}
# Two-model roster: fable (high) thinks — the main session decides, the debugger proves
# root causes; opus (xhigh) executes decisions already made — locate, research, build
# from a brief that names the pattern, review. The scout runs low: a lookup does not think.
PINS = {'scout': ('opus', 'low'), 'researcher': ('opus', 'xhigh'), 'builder': ('opus', 'xhigh'),
        'refuter': ('opus', 'xhigh'), 'debugger': ('fable', 'high')}
COLORS = {'red', 'blue', 'green', 'yellow', 'purple', 'orange', 'pink', 'cyan'}
AGENTKEYS = {'name', 'description', 'tools', 'disallowedTools', 'model', 'permissionMode',
             'maxTurns', 'skills', 'mcpServers', 'hooks', 'memory', 'background', 'effort',
             'isolation', 'color', 'initialPrompt', 'experimental'}
for p in sorted(glob.glob('core/agents/*.md')):
    d, _ = fm(p)
    n = os.path.basename(p)
    chk(d is not None, f'{n}: has frontmatter')
    chk('name' in d and 'description' in d, f'{n}: required name+description')
    chk(d.get('name') == n[:-3], f'{n}: name matches filename', d.get('name'))
    chk(d.get('model') in MODELS, f'{n}: model is a valid alias', d.get('model'))
    chk(d.get('model') not in {'sonnet', 'haiku'}, f'{n}: model is fable or opus only', d.get('model'))
    chk(d.get('effort') in EFFORT, f'{n}: effort is valid', d.get('effort'))
    chk((d.get('model'), d.get('effort')) == PINS.get(n[:-3]), f'{n}: pinned to {PINS.get(n[:-3])}',
        str((d.get('model'), d.get('effort'))))
    chk(d.get('color') in COLORS, f'{n}: color is documented', d.get('color'))
    chk(set(d) <= AGENTKEYS, f'{n}: no unknown keys', str(set(d) - AGENTKEYS))

print()
print('=== 2. TOOL RESTRICTIONS ARE REAL ===')
QZ = 'mcp__qartez__qartez_'
for name, must_lack, must_have in [
        ('refuter', ['Edit', 'Write', 'NotebookEdit', 'Agent'], ['Read', 'Bash', QZ + 'refs']),
        ('scout', ['Edit', 'Write', 'Bash', 'Read', 'Agent'], [QZ + 'find', QZ + 'grep', QZ + 'refs']),
        ('researcher', ['Edit', 'Write', 'WebFetch', 'WebSearch', 'Agent'],
         ['Read', QZ + 'explore', 'mcp__firecrawl__firecrawl_search', 'mcp__exa__web_search_exa',
          'mcp__context7__query-docs']),
        ('debugger', ['Edit', 'Write', 'Agent'], ['Read', 'Bash', QZ + 'locate']),
        ('builder', ['Agent'], ['Edit', 'Write', 'Bash', QZ + 'impact'])]:
    d, _ = fm(f'core/agents/{name}.md')
    t = [x.strip() for x in d['tools'].split(',')]
    chk(all(m not in t for m in must_lack), f'{name}: lacks {must_lack}', str(t))
    chk(all(m in t for m in must_have), f'{name}: has {must_have}', str(t))

print()
print('=== 3. COMMAND FRONTMATTER ===')
CMDKEYS = {'description', 'when_to_use', 'argument-hint', 'arguments', 'disable-model-invocation',
           'user-invocable', 'allowed-tools', 'disallowed-tools', 'model', 'effort', 'context',
           'agent', 'background', 'hooks', 'shell', 'metadata', 'license', 'compatibility'}
for p in sorted(glob.glob('core/commands/*.md')):
    d, s = fm(p)
    n = os.path.basename(p)
    chk(d is not None and 'description' in d, f'{n}: has description')
    chk(set(d) <= CMDKEYS, f'{n}: only documented keys', str(set(d) - CMDKEYS))
    chk(re.search(r'[$][0-9]', s) is None, f'{n}: no 0-based positional args')

print()
print('=== 4. DUPLICATION ===')


def norm(s):
    s = re.sub(r'^[#>*\d.|`' + SEP + r's-]+', '', s.strip().lower())
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9 ]', ' ', s)).strip()


idx = collections.defaultdict(set)
for f in files:
    for ln in open(f, encoding='utf-8'):
        n = norm(ln)
        if len(n.split()) >= 7:
            idx[n].add(f)
dupes = {k: v for k, v in idx.items() if len(v) > 1}
print(f'  files scanned: {len(files)}   duplicated substantive lines: {len(dupes)}')
BUCKET_OK = {'core/CLAUDE.md', 'core/commands/task.md'}
unexplained = []
for k, v in sorted(dupes.items(), key=lambda x: -len(x[1])):
    reason = ''
    if v <= BUCKET_OK:
        reason = 'bucket headings: CLAUDE.md defines, command emits'
    elif v <= (BUCKET_OK | {'README.md'}):
        reason = 'bucket structure: CLAUDE.md defines, command creates, README documents'
    elif 'README.md' in v and len(v) == 2:
        reason = 'README is docs, not config'
    else:
        reason = 'UNEXPLAINED'
        unexplained.append((k, v))
    print(f'    [{len(v)}] {k[:48]:48s} {reason}')
chk(not unexplained, 'no unexplained duplication', str(unexplained[:2]))

print()
print('=== 5. ONE OWNER PER CONCEPT (config only) ===')
cfg = [f for f in files if 'README' not in f]
for concept, pat in [('six-section brief', 'CURRENT STATE'),
                     ('banned phrases', 'explore all approaches'),
                     ('model resolution order', 'Resolution order'),
                     ('roster table', r'`scout`[^|]*\|\s*opus'),
                     ('two-model rule', 'Two models only'),
                     ('two refuters', 'two refuters'),
                     ('bucket protocol rules', 'reverse a decision')]:
    owners = [f for f in cfg if re.search(pat, open(f, encoding='utf-8').read())]
    definers = [f for f in owners if f == 'core/CLAUDE.md']
    chk(len(owners) >= 1, f'{concept}: exists at all', 'ZERO owners - concept vanished')
    chk(len(definers) == 1 or len(owners) == 1, f'{concept}: single definition', str(owners))
    if owners != ['core/CLAUDE.md']:
        print(f'       (also referenced in: {[o for o in owners if o != "core/CLAUDE.md"]})')

print()
print('=== 6. NO DANGLING REFERENCES ===')
nonmd = {slash(f) for f in glob.glob('**/*', recursive=True) if os.path.isfile(f)}
allfiles = set(files) | {slash(f) for f in nonmd}
for f in files:
    s = open(f, encoding='utf-8').read()
    refs = set(re.findall(r'`((?:core|extras)/[A-Za-z0-9_./-]+)`', s))
    for ref in refs:
        r = ref.rstrip('/')
        ok = r in allfiles or any(p.startswith(r + '/') for p in allfiles)
        chk(ok, f'{f} -> {ref}')
    chk('_BRIEF-TEMPLATE' not in s, f'{f}: no ref to deleted _BRIEF-TEMPLATE.md')

print()
print('=== 7. USER-SETTINGS FRAGMENT + INSTALLER ===')
import json
try:
    su = json.load(open('core/settings.user.json', encoding='utf-8'))
except Exception as e:
    su = {}
    chk(False, 'settings.user.json parses', str(e))
env = su.get('env', {})
chk(env.get('CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH') == '1', 'env: spawn depth 1')
chk(env.get('CLAUDE_CODE_SUBAGENT_MODEL') == 'opus', 'env: off-roster subagent model opus')
chk('CLAUDE_CODE_EFFORT_LEVEL' not in env, 'env: CLAUDE_CODE_EFFORT_LEVEL absent (would override frontmatter effort)')
chk('CLAUDE_CODE_SUBAGENT_MODEL_FORCE' not in env, 'env: _FORCE absent (would erase model pins)')
ms = su.get('modelSettings', {})
chk(ms.get('claude-fable-5-1', {}).get('effortLevel') == 'high', 'modelSettings: fable high')
chk(ms.get('claude-opus-5', {}).get('effortLevel') == 'xhigh', 'modelSettings: opus xhigh')
chk(all(v.get('effortLevel') != 'max' for v in ms.values()), 'modelSettings: no max (not accepted by the key)')
chk(os.path.isfile('install.ps1'), 'install.ps1 exists')

print()
print(f'checks run: {checks}   failures: {len(fails)}')
for x in fails:
    print('  FAILED: ' + x)
sys.exit(1 if fails else 0)
