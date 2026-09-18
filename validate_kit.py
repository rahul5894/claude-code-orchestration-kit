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


def fmx(path):
    """Frontmatter of a file the kit REQUIRES. A missing one is a failed check, never a
    crash - otherwise the gate stops at the first gap and hides every later failure."""
    if not os.path.isfile(path):
        chk(False, f'{path}: exists', 'missing - later checks on it were SKIPPED')
        return {}, ''
    return fm(path)


files = sorted(slash(f) for f in glob.glob('**/*.md', recursive=True))
# The dated doc filenames are derived once, here: pinning them in two places turns the gate
# red twice for one rename.
DOCS = sorted(slash(f) for f in glob.glob('docs/*.md'))
# extras/rejected is a verbatim archive of what we do NOT install. It is not config and is
# deliberately allowed to echo other files.
cfgfiles = [f for f in files if not f.startswith('extras/rejected/')]

print('=== 1. AGENT FRONTMATTER - docs-valid values only ===')
MODELS = {'sonnet', 'opus', 'haiku', 'fable', 'inherit'}
EFFORT = {'low', 'medium', 'high', 'xhigh', 'max'}
# v2 roster: Opus 5 is the default seat everywhere - half Fable's price, same speed per turn.
# Nothing is pinned to fable, so Fable quota running out cannot break the loop. The locate
# agent shadows the built-in Explore on haiku, which has no effort parameter at all.
# refuter is the recall-biased finder at high (xhigh buys quality by making MORE tool calls);
# verifier is the precision stage at low and is the only agent carrying the exclusion list.
PINS = {'Explore': ('haiku', None), 'researcher': ('opus', 'high'), 'builder': ('opus', 'high'),
        'verifier': ('opus', 'low'), 'refuter': ('opus', 'high'), 'debugger': ('opus', 'high')}
COLORS = {'red', 'blue', 'green', 'yellow', 'purple', 'orange', 'pink', 'cyan'}
AGENTKEYS = {'name', 'description', 'tools', 'disallowedTools', 'model', 'permissionMode',
             'maxTurns', 'skills', 'mcpServers', 'hooks', 'memory', 'background', 'effort',
             'isolation', 'color', 'initialPrompt', 'experimental', 'omitClaudeMd'}
agentfiles = sorted(glob.glob('core/agents/*.md'))
chk(len(agentfiles) == len(PINS), f'roster has exactly {len(PINS)} agents',
    str([os.path.basename(p) for p in agentfiles]))
for p in agentfiles:
    d, _ = fm(p)
    n = os.path.basename(p)
    stem = n[:-3]
    chk(d is not None, f'{n}: has frontmatter')
    chk('name' in d and 'description' in d, f'{n}: required name+description')
    chk(d.get('name') == stem, f'{n}: name matches filename', d.get('name'))
    chk(d.get('model') in MODELS, f'{n}: model is a valid alias', d.get('model'))
    chk(d.get('model') != 'fable', f'{n}: not pinned to fable (quota must never break the loop)',
        d.get('model'))
    chk(d.get('effort') in EFFORT or d.get('effort') is None, f'{n}: effort is valid or absent',
        d.get('effort'))
    chk((d.get('model'), d.get('effort')) == PINS.get(stem), f'{n}: pinned to {PINS.get(stem)}',
        str((d.get('model'), d.get('effort'))))
    chk(d.get('color') in COLORS, f'{n}: color is documented', d.get('color'))
    chk(set(d) <= AGENTKEYS, f'{n}: no unknown keys', str(set(d) - AGENTKEYS))
    # A worktree gives the agent its own checkout and forfeits the shared cached prefix, so
    # no roster agent sets it - least of all a read-only reviewer that writes nothing.
    chk('isolation' not in d, f'{n}: no isolation key (a worktree forfeits the cached prefix)',
        str(d.get('isolation')))
# haiku has no effort parameter, so setting one there is a silent no-op
d, _ = fmx('core/agents/Explore.md')
chk('effort' not in d, 'Explore: no effort key (haiku ignores it)', str(d.get('effort')))

print()
print('=== 2. TOOL RESTRICTIONS ARE REAL ===')
QZ = 'mcp__qartez__qartez_'
for name, must_lack, must_have in [
        ('refuter', ['Edit', 'Write', 'NotebookEdit', 'Agent'], ['Read', 'Bash', QZ + 'refs']),
        ('Explore', ['Edit', 'Write', 'Bash', 'Read', 'Agent'],
         [QZ + 'find', QZ + 'grep', QZ + 'refs']),
        ('researcher', ['Edit', 'Write', 'WebFetch', 'WebSearch', 'Agent'],
         ['Read', QZ + 'explore', 'mcp__firecrawl__firecrawl_search', 'mcp__exa__web_search_exa',
          'mcp__context7__query-docs']),
        ('debugger', ['Edit', 'Write', 'Agent'], ['Read', 'Bash', QZ + 'locate']),
        ('builder', ['Agent'], ['Edit', 'Write', 'Bash', QZ + 'impact']),
        ('verifier', ['Edit', 'Write', 'Bash', 'Agent'], ['Read', QZ + 'read', QZ + 'refs'])]:
    d, _ = fmx(f'core/agents/{name}.md')
    t = [x.strip() for x in d.get('tools', '').split(',')]
    chk(all(m not in t for m in must_lack), f'{name}: lacks {must_lack}', str(t))
    chk(all(m in t for m in must_have), f'{name}: has {must_have}', str(t))

# A tool list is the guard, not a git-status snapshot: with background agents in flight a
# snapshot cannot attribute a write, and cannot see a write-then-revert at all.
for name in ['refuter', 'verifier', 'Explore']:
    d, _ = fmx(f'core/agents/{name}.md')
    bl = [x.strip() for x in d.get('disallowedTools', '').split(',')]
    chk(all(m in bl for m in ['Edit', 'Write', 'NotebookEdit']),
        f'{name}: disallowedTools blocks Edit/Write/NotebookEdit', str(bl))

for name, cap in [('refuter', 40), ('verifier', 20)]:
    d, _ = fmx(f'core/agents/{name}.md')
    chk(str(d.get('maxTurns')) == str(cap), f'{name}: maxTurns == {cap}', str(d.get('maxTurns')))

print()
print('=== 3. THE TWO-STAGE REVIEW IS WIRED CORRECTLY ===')
refd, ref = fmx('core/agents/refuter.md')
verd, ver = fmx('core/agents/verifier.md')
# The finder must not carry the exclusion list. A finder that filters itself drops
# half-believed candidates before anything can judge them, which is how real defects escape.
chk('review-precision' not in str(refd.get('skills')),
    'refuter: does NOT preload review-precision (a finder must not filter itself)',
    str(refd.get('skills')))
chk('review-precision' in str(verd.get('skills')),
    'verifier: preloads review-precision (precision lives in the judging stage)',
    str(verd.get('skills')))
SK = 'core/skills/review-precision/SKILL.md'
chk(os.path.isfile(SK), 'review-precision skill exists')
skill = open(SK, encoding='utf-8').read() if os.path.isfile(SK) else ''
# "invert" plus "client-decidable" anywhere was satisfied by its own negation ("we do not
# invert ... client-decidable"), so assert the inverted rule positively - one paragraph must
# say a client-decided rule is NEVER EXCLUDED - and ban the un-inverted claim outright.
paras = re.split(r'\n\s*\n', skill)
chk(any(re.search(r'client-decidable|the client decides', p) and 'never' in p.lower()
        and 'EXCLUDED' in p for p in paras),
    'review-precision: states a client-decided rule is never EXCLUDED')
chk(re.search(r'not\s+invert|client-(?:side auth\w*|decidable)[^.]*\b(?:is|are) EXCLUDED\b',
              skill, re.I) is None,
    'review-precision: does not carry the un-inverted client-authz exclusion')
# TWINS of items 1-3, same presence-only shape, found by builder-01 and closed here.
# Judging-stage-only must be stated ABOVE the exclusion list, or a finder that skims the
# top of the file never sees it - which is how rule 8 ate ten real findings once already.
_sk_lines = skill.splitlines()
_finder_at = next((i for i, l in enumerate(_sk_lines) if 'Never give it to a finder' in l), -1)
_excl_at = next((i for i, l in enumerate(_sk_lines) if l.startswith('## Exclusions')), 10 ** 6)
chk(0 <= _finder_at < _excl_at,
    'review-precision: judging-stage-only is stated above the exclusion list',
    f'finder-warning line {_finder_at}, exclusions start {_excl_at}')
# An exclusion must never be reachable for a non-security candidate. Assert the scope gate
# exists and names correctness, not just that some carve-out sentence appears somewhere.
chk(re.search(r'never\s+EXCLUDED', skill) is not None
    and re.search(r'correctness[^.]*never\s+EXCLUDED|never\s+EXCLUDED[^.]*correctness',
                  skill, re.I | re.S) is not None,
    'review-precision: correctness candidates are explicitly never EXCLUDED')
# The refuter re-running a deterministic command is minutes of wall-clock for no information,
# and it is what killed four of five review passes in the measured session.
chk('Do not run the project' in ref, 'refuter: forbidden from running the gate itself')
# Presence of the ban is not enough - a contradicting "run the gate first" line could be
# added beside it. So every sentence that mentions both the gate and running must either
# forbid it or describe it as already run by someone else.
GATE_OK = re.compile(r'do not run|never run|orchestrator ran|already ran|gate ran', re.I)
gate_run = [s.strip() for s in re.split(r'(?<=[.!?])\s+|\n\s*\n', ref)
            if 'gate' in s.lower() and re.search(r'\brun', s, re.I) and not GATE_OK.search(s)]
chk(not gate_run, 'refuter: no sentence tells it to run the gate', str(gate_run[:2]))
# Not "the three words appear somewhere": they must be the states of the JUDGED contract,
# on one line, in the output block the verifier actually fills in.
chk(any(all(w in l for w in ('CONFIRMED', 'PLAUSIBLE', 'REFUTED')) and 'path:LINE' in l
        for l in ver.splitlines()),
    'verifier: three states on the JUDGED contract line itself')
# "This is the default" never named a verdict, so "REFUTED is the default" would have passed.
# Take the bullet that claims the default and require its head to be PLAUSIBLE, exactly one.
dflt = [b.strip() for b in re.split(r'\n(?=[-*] )', ver) if re.search(r'is the default', b, re.I)]
chk(len(dflt) == 1 and re.match(r'[-*] \*\*PLAUSIBLE\*\*', dflt[0]) is not None,
    'verifier: PLAUSIBLE, and only PLAUSIBLE, is the documented default',
    str([b[:40] for b in dflt]))
chk('drops nothing' in ref or 'do not filter yourself' in ref.lower(),
    'refuter: told to drop nothing')
# The finder must carry no exclusion vocabulary and no confidence FLOOR. A floor is a
# minimum ("only above 80%"); "report it even at 40% confidence" is the opposite and must
# stay legal, so match the floor shape, not the word "confidence".
chk('EXCLUDED' not in ref
    and re.search(r'confidence floor|(?:at least|above|over|minimum of|>\s*=?)\s*\d+%'
                  r'|\d+%\s*(?:or (?:higher|more)|confident or)', ref, re.I) is None,
    'refuter: carries no exclusion list and no confidence floor')

print()
print('=== 4. COMMAND FRONTMATTER ===')
CMDKEYS = {'description', 'when_to_use', 'argument-hint', 'arguments', 'disable-model-invocation',
           'user-invocable', 'allowed-tools', 'disallowed-tools', 'model', 'effort', 'context',
           'agent', 'background', 'hooks', 'shell', 'metadata', 'license', 'compatibility'}
for p in sorted(glob.glob('core/commands/*.md')):
    d, s = fm(p)
    n = os.path.basename(p)
    chk(d is not None and 'description' in d, f'{n}: has description')
    chk(set(d) <= CMDKEYS, f'{n}: only documented keys', str(set(d) - CMDKEYS))
    # $1 is the SECOND word, not the first, so any numbered positional is a hazard here.
    chk(re.search(r'[$][0-9]', s) is None, f'{n}: no numbered positional args')
chk(os.path.isfile('core/output-styles/orchestrator.md'),
    'core/output-styles/orchestrator.md exists')
for p in sorted(glob.glob('core/output-styles/*.md')):
    d, _ = fm(p)
    chk(d is not None and 'name' in d and 'description' in d,
        f'{os.path.basename(p)}: output style has name+description')

print()
print('=== 5. THE PER-SPAWN COST BUDGET ===')
# Every non-fork subagent re-pays the whole CLAUDE.md hierarchy on every spawn. Claude Code's
# guidance is under 200 lines, but BYTES are what is actually paid and this file wraps at 90
# chars, so a line count flatters it. Budget both. 7000 bytes is roughly 1800 tokens; the
# pre-split file was 12,701 bytes.
SHARED_BYTE_BUDGET = 7000
cm_raw = open('core/CLAUDE.md', 'rb').read() if os.path.isfile('core/CLAUDE.md') else b''
cm = cm_raw.decode('utf-8').splitlines()
chk(len(cm) <= 200, 'core/CLAUDE.md is <= 200 lines (docs guidance)', str(len(cm)))
chk(len(cm_raw) <= SHARED_BYTE_BUDGET,
    f'core/CLAUDE.md is <= {SHARED_BYTE_BUDGET} bytes (this is what every spawn pays)',
    f'{len(cm_raw)} bytes')
# The output style is where the orchestrator's half went. Without keep-coding-instructions a
# custom style REPLACES Claude Code's built-in software-engineering instructions, so
# activating it would make the main session worse, silently.
osd, ostxt = fmx('core/output-styles/orchestrator.md')
chk(str(osd.get('keep-coding-instructions')).lower() == 'true',
    'orchestrator style: keep-coding-instructions true (else it strips the built-ins)',
    str(osd.get('keep-coding-instructions')))
chk(osd.get('name') == 'orchestrator', 'orchestrator style: name matches the settings value',
    str(osd.get('name')))
# Only agents that take everything from the brief may skip it - and only if they restate the
# tool rules, or they fall back to Grep on source and cost more than the flag saved.
for p in agentfiles:
    d, _ = fm(p)
    n = os.path.basename(p)
    if str(d.get('omitClaudeMd')).lower() == 'true':
        chk('qartez' in str(d.get('initialPrompt', '')),
            f'{n}: omitClaudeMd is paired with the qartez rule in initialPrompt')
# Explore is brief-driven and pays the hierarchy on every spawn for nothing, so its flag is
# asserted unconditionally - the pairing check above vanishes together with the flag.
d, _ = fmx('core/agents/Explore.md')
chk(str(d.get('omitClaudeMd')).lower() == 'true', 'Explore: omitClaudeMd true (spawn cost)',
    str(d.get('omitClaudeMd')))
chk('qartez' in str(d.get('initialPrompt', '')),
    'Explore: initialPrompt restates the qartez rule')

print()
print('=== 6. DUPLICATION ===')


def norm(s):
    s = re.sub(r'^[#>*\d.|`' + SEP + r's-]+', '', s.strip().lower())
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9 ]', ' ', s)).strip()


idx = collections.defaultdict(set)
for f in cfgfiles:
    for ln in open(f, encoding='utf-8'):
        n = norm(ln)
        if len(n.split()) >= 7:
            idx[n].add(f)
dupes = {k: v for k, v in idx.items() if len(v) > 1}
print(f'  files scanned: {len(cfgfiles)}   duplicated substantive lines: {len(dupes)}')
BUCKET_OK = {'core/CLAUDE.md', 'core/commands/task.md'}
PROSE = {'README.md', 'SETUP-NEW-MACHINE.md'} | set(DOCS)
unexplained = []
for k, v in sorted(dupes.items(), key=lambda x: -len(x[1])):
    if v <= BUCKET_OK:
        reason = 'bucket headings: CLAUDE.md defines, command emits'
    elif v <= (BUCKET_OK | PROSE):
        reason = 'config defines, prose documents'
    elif len(v & PROSE) and len(v) == 2:
        reason = 'prose restates one config line'
    else:
        reason = 'UNEXPLAINED'
        unexplained.append((k, sorted(v)))
    print(f'    [{len(v)}] {k[:48]:48s} {reason}')
chk(not unexplained, 'no unexplained duplication', str(unexplained[:3]))

print()
print('=== 7. ONE OWNER PER CONCEPT, AND THE SPLIT HOLDS ===')
# Two audiences, two files. SHARED = core/CLAUDE.md, re-paid on EVERY subagent spawn, so it
# holds only what a subagent can act on. ORCH = the output style, main session only, free per
# spawn. A concept in the wrong file is either dead weight on every agent or a rule the
# orchestrator no longer has.
SHARED, ORCH = 'core/CLAUDE.md', 'core/output-styles/orchestrator.md'
cfg = [f for f in cfgfiles if f not in PROSE]
for concept, pat, owner in [
        # an agent acts on these
        ('qartez over grep', r'[Cc]ode search is qartez', SHARED),
        ('no wholesale doc reads', r'[Nn]ever read a document wholesale', SHARED),
        ('brief is authoritative', r'The brief is the spec and it is authoritative', SHARED),
        ('bucket protocol rules', 'reverse a decision', SHARED),
        ('agents never write STATE.md', r'[Nn]ever write `STATE\.md`', SHARED),
        # The v1 wording was "the gate runs once". It is not once: the builder runs it twice
        # (baseline, then last step). The invariant that killed four review passes when it
        # was absent is that ZERO review agents run it.
        ('no review agent runs the gate', r'Zero review agents run it', SHARED),
        ('recall and precision are split', r'recall and precision are different', SHARED),
        ('security surface defined', r'A \*\*security surface\*\* is', SHARED),
        # matched on the prose, not the frontmatter - every read-only agent file legitimately
        # carries the key itself, and that is the implementation, not a second definition
        ('read-only agents blocked', r'blocks the edit tools only', SHARED),
        # only the orchestrator can act on these
        ('six-section brief', 'CURRENT STATE', ORCH),
        ('banned phrases', 'explore all approaches', ORCH),
        ('model resolution order', 'Resolution order', ORCH),
        ('roster table', r'`refuter`[^|]*\|\s*opus', ORCH),
        ('opus is the default seat', 'Opus 5 is the default seat', ORCH),
        # builder.md's description legitimately names the threshold so the orchestrator can
        # pick it; the RULE sentence is what must have one owner
        ('delegation threshold', r'exceeds \*\*~400 changed lines', ORCH),
        ('one refuter pass', 'ONE refuter pass', ORCH),
        ('batch review of small changes', 'Unreviewed since', ORCH),
        ('resume instead of re-spawn', r'Resume with `SendMessage`', ORCH),
        ('sibling cache stagger', 'stagger same-profile spawns', ORCH),
        ('measurement targets', r'turns before the\s*\n?first edit', ORCH)]:
    owners = [f for f in cfg if re.search(pat, open(f, encoding='utf-8').read())]
    chk(owner in owners, f'{concept}: defined in {os.path.basename(owner)}', str(owners))
    chk(len(owners) == 1, f'{concept}: single definition', str(owners))

# The split is only a saving if the shared file stays out of the orchestrator's business.
shared_txt = open(SHARED, encoding='utf-8').read()
for banned, why in [(r'`refuter`[^|]*\|\s*opus', 'the roster table'),
                    ('Resolution order', 'model resolution'),
                    ('400 changed lines', 'the delegation threshold'),
                    ('CURRENT STATE', 'the brief template')]:
    chk(re.search(banned, shared_txt) is None,
        f'core/CLAUDE.md does NOT carry {why} (orchestrator-only, paid per spawn)')

print()
print('=== 8. NO DANGLING REFERENCES ===')
nonmd = {slash(f) for f in glob.glob('**/*', recursive=True) if os.path.isfile(f)}
allfiles = set(files) | {slash(f) for f in nonmd}
for f in files:
    s = open(f, encoding='utf-8').read()
    # extras/project/** is a template for the TARGET repo, so its docs/ paths name files that
    # repo creates, not files here.
    pat = r'`((?:core|extras)/[A-Za-z0-9_./-]+)`' if f.startswith('extras/project/') \
        else r'`((?:core|extras|docs)/[A-Za-z0-9_./-]+)`'
    refs = set(re.findall(pat, s))
    for ref in refs:
        r = ref.rstrip('/')
        ok = r in allfiles or any(p.startswith(r + '/') for p in allfiles)
        chk(ok, f'{f} -> {ref}')
    chk('_BRIEF-TEMPLATE' not in s, f'{f}: no ref to deleted _BRIEF-TEMPLATE.md')
    chk('core/agents/scout.md' not in s, f'{f}: no ref to retired scout agent')

print()
print('=== 9. USER-SETTINGS FRAGMENT + INSTALLER ===')
import json
try:
    su = json.load(open('core/settings.user.json', encoding='utf-8'))
except Exception as e:
    su = {}
    chk(False, 'settings.user.json parses', str(e))
env = su.get('env', {})
# The documented default is three layers of nesting, so this one is load-bearing.
chk(env.get('CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH') == '1', 'env: spawn depth 1')
chk(env.get('CLAUDE_CODE_SUBAGENT_MODEL') == 'opus', 'env: off-roster subagent model opus')
chk(env.get('CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS') == '0',
    'env: agent teams pinned off (a named subagent would become a ~7x-token teammate)')
# The ponytail plugin's own SubagentStart hook has no matcher, so unscoped it injects ~1,347
# tokens into EVERY spawn. It earns that in an agent that writes or diagnoses code; a finder
# and a judge write none. The main session keeps it in full - SessionStart ignores this var.
pm = env.get('PONYTAIL_SUBAGENT_MATCHER', '')
chk(pm and all(a in pm for a in ('builder', 'debugger'))
    and not any(a in pm for a in ('refuter', 'verifier', 'Explore', 'researcher')),
    'env: ponytail scoped to the agents that touch code', repr(pm))
chk('CLAUDE_CODE_EFFORT_LEVEL' not in env,
    'env: CLAUDE_CODE_EFFORT_LEVEL absent (would override frontmatter effort)')
chk('CLAUDE_CODE_SUBAGENT_MODEL_FORCE' not in env, 'env: _FORCE absent (would erase model pins)')
# Subagent requests sit in the 5-minute cache bucket by default, even on a subscription.
chk(su.get('subagentPromptCacheTtl') == '1h', 'settings: subagentPromptCacheTtl 1h',
    str(su.get('subagentPromptCacheTtl')))
# The split only works if the style is actually switched on. Installed-but-inactive was a
# real defect once: the orchestrator's own rules were sitting on disk doing nothing.
chk(su.get('outputStyle') == 'orchestrator', 'settings: outputStyle activates the style',
    str(su.get('outputStyle')))
# The default branches a worktree from the default branch, hiding local work from the agent.
chk(su.get('worktree', {}).get('baseRef') == 'head', 'settings: worktree.baseRef head',
    str(su.get('worktree')))
ms = su.get('modelSettings', {})
chk(ms.get('claude-opus-5', {}).get('effortLevel') == 'high', 'modelSettings: opus 5 high',
    str(ms.get('claude-opus-5')))
chk(all(v.get('effortLevel') != 'max' for v in ms.values()),
    'modelSettings: no max (not accepted by the key)')
chk('maxEffortLevel' not in su and all('maxEffortLevel' not in v for v in ms.values()),
    'settings: no maxEffortLevel (it caps every agent pin silently)')
chk(os.path.isfile('install.ps1'), 'install.ps1 exists')
inst = open('install.ps1', encoding='utf-8').read() if os.path.isfile('install.ps1') else ''
for frag, label in [('core\\skills', 'installer copies skills'),
                    ('core\\output-styles', 'installer copies output styles'),
                    ('RETIRED_AGENTS', 'installer removes retired agents by name'),
                    ('RETIRED_SKILLS', 'installer removes retired skills by name'),
                    ('maxEffortLevel', 'installer warns on maxEffortLevel')]:
    chk(frag in inst, label)
# A substring only proves the text exists. These two guards were provably dead once, because
# they read the POST-merge settings, where the kit's own value always wins. So assert the
# mechanism: both must read the pre-merge copy, and the pre-merge copy must be taken before
# Merge-Into runs.
_pre_var = re.search(r'\$pre\s*=', inst)
_merge_at = inst.find('Merge-Into $set $frag')
chk(_pre_var is not None and _merge_at > 0 and _pre_var.start() < _merge_at,
    'installer: captures the user settings BEFORE the merge')
for key in ('CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS', 'subagentPromptCacheTtl'):
    guards = [l for l in inst.splitlines()
              if key in l and re.search(r'-eq|-ne|if\s*\(', l)]
    chk(bool(guards) and all('$pre' in l for l in guards),
        f'installer: the {key} guard reads $pre, not the merged result', str(guards)[:160])
chk(len(DOCS) >= 2, 'docs/ holds the plan and the research notes', str(DOCS))
for p in DOCS + ['extras/rejected/README.md', 'extras/prideconnect-section.md']:
    chk(os.path.isfile(p), f'{p} exists')

print()
# Most sections are glob-driven: one that yields nothing contributes zero checks and still
# prints "failures: 0". The floor makes a silently empty section red.
MIN_CHECKS = 190
chk(checks >= MIN_CHECKS, f'gate ran at least {MIN_CHECKS} checks (no section silently empty)',
    str(checks))
print(f'checks run: {checks}   failures: {len(fails)}')
for x in fails:
    print('  FAILED: ' + x)
sys.exit(1 if fails else 0)
