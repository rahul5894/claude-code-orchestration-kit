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
        if ln[:1] in (' ', chr(9)):
            continue  # indented = nested under the key above it, not a top-level key
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
# The repo's own CLAUDE.md is an INSTANCE of extras/project/CLAUDE.md, so it necessarily
# repeats that template's headings and preamble. Excluding it keeps the duplication check
# meaningful; without it the kit could not follow its own template without going red.
# extras/rejected is a verbatim archive of what we do NOT install. It is not config and is
# deliberately allowed to echo other files.
cfgfiles = [f for f in files
            if not f.startswith('extras/rejected/') and f != 'CLAUDE.md']

print('=== 0. NO LITERAL CONTROL CHARACTERS IN SOURCE ===')
# Found 2026-09-18: validate_kit.py carried two 0x08 bytes where \\b was intended, so a
# regex read as a word boundary searched for a literal backspace, matched nothing, and the
# check built on it could never fail. A patch script written with a non-raw Python string
# turns \\b, \\f, \\a and \\v into control bytes silently; nothing else in the toolchain
# complains, and the line still LOOKS right in an editor.
CTRL = {0x08: 'backspace', 0x0c: 'formfeed', 0x07: 'bell', 0x0b: 'vtab', 0x00: 'NUL'}
for _f in sorted(glob.glob('*.py') + glob.glob('*.ps1') + glob.glob('core/**/*.md', recursive=True)):
    _b = open(_f, 'rb').read()
    _found = sorted({CTRL[c] for c in set(_b) & set(CTRL)})
    chk(not _found, f'{_f}: no literal control characters', str(_found))

print()
print('=== 0b. FRONTMATTER IS VALID YAML ===')
# The line-splitting parser below is forgiving; Claude Code's is not. Two agents shipped with
# an unquoted ": " inside initialPrompt, which YAML reads as a nested mapping. `claude plugin
# validate` said "At runtime this agent does not load at all" - two of six agents would have
# been silently absent from the next session, while every check here stayed green because the
# parser used for checking was not the parser used for loading.
try:
    import yaml as _yaml
except ImportError:
    _yaml = None
for _f in sorted(glob.glob('core/agents/*.md') + glob.glob('core/commands/*.md')
                 + glob.glob('core/skills/*/SKILL.md') + glob.glob('core/output-styles/*.md')):
    _head = open(_f, encoding='utf-8').read().split('\n---', 1)[0].lstrip('-\n')
    if _yaml:
        try:
            _parsed = _yaml.safe_load(_head)
            _err = None if isinstance(_parsed, dict) else f'parsed as {type(_parsed).__name__}'
        except Exception as e:
            _err = str(e).split('\n')[0]
        chk(_err is None, f'{_f}: frontmatter is valid YAML', str(_err))
    else:
        # No PyYAML: catch the one construct that actually broke it. An unquoted scalar
        # containing ": " is a nested mapping to YAML and a parse error in practice.
        _bad = [ln.split(':', 1)[0].strip() for ln in _head.splitlines()
                if ':' in ln and ln.split(':', 1)[1].strip()[:1] not in ('"', "'", '[', '{',
                                                                        '|', '>', '')
                and ': ' in ln.split(':', 1)[1]]
        chk(not _bad, f'{_f}: no unquoted ": " in frontmatter (breaks YAML)', str(_bad))


def _yfm(path):
    """Frontmatter as Claude Code parses it. fm()'s line splitter flattens a nested map, so
    anything under `experimental` is only visible through the real YAML parse. Like fmx(), a
    missing or unparseable file is a failed check, never a crash that stops the gate."""
    if not os.path.isfile(path):
        chk(False, f'{path}: exists', 'missing - later checks on it were SKIPPED')
        return {}
    if not _yaml:
        return {}
    _h = open(path, encoding='utf-8').read().split('\n---', 1)[0].lstrip('-\n')
    try:
        return _yaml.safe_load(_h) or {}
    except _yaml.YAMLError as e:
        chk(False, f'{path}: frontmatter parses as YAML', str(e)[:120])
        return {}


# experimental.cacheTtl (documented 2.1.248+) is a nested map, never a top-level key. The four
# Opus agents hold the 1h prompt cache; Explore (haiku) and debugger (inherit) deliberately do
# not, so a Fable session never pays to cache a seat it shares with the main conversation.
if _yaml:
    for _n in ('builder', 'refuter', 'verifier', 'researcher'):
        _efm = _yfm(f'core/agents/{_n}.md')
        chk((_efm.get('experimental') or {}).get('cacheTtl') == '1h',
            f'{_n}: experimental.cacheTtl is 1h', str(_efm.get('experimental')))
    for _n in ('Explore', 'debugger'):
        _efm = _yfm(f'core/agents/{_n}.md')
        chk('experimental' not in _efm, f'{_n}: no experimental key',
            str(_efm.get('experimental')))
else:
    chk(False, 'cacheTtl checks need PyYAML (pip install pyyaml)')

print()
print('=== 1. AGENT FRONTMATTER - docs-valid values only ===')
MODELS = {'sonnet', 'opus', 'haiku', 'fable', 'inherit'}
EFFORT = {'low', 'medium', 'high', 'xhigh', 'max'}
# Fable thinks, Opus executes. The orchestrator is whatever /model says (Fable 5.1 high, or
# Opus 5 xhigh once Fable quota is gone); the kit never sets it. The debugger INHERITS that
# seat - hard reasoning follows the orchestrator, and inherit can never break on quota.
# Everything that executes a decision already written down is pinned opus: that is how Fable
# tokens are saved. The judge (verifier) runs high because it decides what gets fixed. The
# locate agent shadows the built-in Explore on haiku, which has no effort parameter at all.
PINS = {'Explore': ('haiku', None), 'researcher': ('opus', 'high'), 'builder': ('opus', 'high'),
        'verifier': ('opus', 'high'), 'refuter': ('opus', 'high'), 'debugger': ('inherit', 'high')}
COLORS = {'red', 'blue', 'green', 'yellow', 'purple', 'orange', 'pink', 'cyan'}
AGENTKEYS = {'name', 'description', 'tools', 'disallowedTools', 'model', 'permissionMode',
             'maxTurns', 'skills', 'mcpServers', 'hooks', 'memory', 'background', 'effort',
             'isolation', 'color', 'initialPrompt', 'omitClaudeMd',
             # 'experimental' holds nested keys (cacheTtl); fm() skips indented lines so they
             # never appear here.
             'experimental'}
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
    chk(d.get('model') != 'fable', f'{n}: no HARD pin to fable (inherit follows /model; a hard pin breaks on quota)',
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
# Measured: Explore reported NO MATCHES for three things that were really in .json/.ps1/.md,
# because its body said an empty qartez result IS the answer while its initialPrompt said
# Grep is for non-code files. qartez indexes source only, so the non-code route must be
# explicit or the agent stops at the wrong index and reports absence that is not real.
_ex = re.sub(r'\s+', ' ', open('core/agents/Explore.md', encoding='utf-8').read())
chk('denies `Grep` and `Glob` on every path' in _ex,
    'Explore: told the guard denies Grep/Glob on every path and file type')
chk('OUT OF INDEX' in _ex,
    'Explore: has a verdict for a lookup its tools cannot reach')
chk('search_bodies=true' in _ex and 'will read as NO MATCHES when it is right there' in _ex,
    'Explore: search_bodies is a rule for literal-string searches')
chk('name the file types qartez actually indexed' in _ex,
    'Explore: must name the indexed file types before reporting NO MATCHES')
chk('is not' in _ex and 'not in the repository' in _ex,
    'Explore: told that an empty qartez index is not an empty repository')

print()
print('=== 2. TOOL RESTRICTIONS ARE REAL ===')
QZ = 'mcp__qartez__qartez_'
for name, must_lack, must_have in [
        ('refuter', ['Edit', 'Write', 'NotebookEdit', 'Agent'], ['Read', 'Bash', QZ + 'refs']),
        ('Explore', ['Edit', 'Write', 'Bash', 'Read', 'Agent', 'Grep', 'Glob'],
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

# Grep and Glob are denied by the qartez guard on EVERY path and file type - verified by
# running qartez-guard.exe directly against a source dir, *.md, a .json, a .ps1, and a
# directory with no qartez index at all. Granting a tool that can never run costs the agent a
# turn to discover the denial and re-plan, and it made two different models report a false
# NO MATCHES rather than admit the lookup was out of reach.
for _p in agentfiles:
    _d, _ = fm(_p)
    _tl = [x.strip() for x in _d.get('tools', '').split(',')]
    chk('Grep' not in _tl and 'Glob' not in _tl,
        f'{os.path.basename(_p)}: no Grep/Glob (the guard denies both unconditionally)',
        str([x for x in _tl if x in ('Grep', 'Glob')]))

print()
print('=== 2b. EVERY MANDATE HAS THE TOOL IT NEEDS ===')
# The rule says "code search is qartez, never Grep on source", and the guard denies Grep on
# source. An agent expected to search source therefore needs qartez_grep, or it has no legal
# way to do it at all. Measured consequence when this was missing: a refuter fell through to
# `Bash grep` (three agents had nothing whatsoever).
for name in ['refuter', 'researcher', 'builder', 'debugger', 'verifier', 'Explore']:
    d, _ = fmx(f'core/agents/{name}.md')
    t = [x.strip() for x in d.get('tools', '').split(',')]
    chk(QZ + 'grep' in t,
        f'{name}: has qartez_grep (Grep is denied on source, so this is its only legal search)',
        str([x for x in t if 'qartez' in x]))

# An order an agent cannot carry out is worse than no order: it either gets silently skipped
# or routed through a shell, and a shell write discards the whole verdict.
shared_txt = open('core/CLAUDE.md', encoding='utf-8').read()
chk('If you can write' in shared_txt and 'If you cannot' in shared_txt,
    'shared: the FINDINGS.md order is scoped to agents that can actually write')
_sh = re.sub(r'\s+', ' ', shared_txt)
chk('denies them on **every** path and file type' in _sh,
    'shared: says the guard denies Grep/Glob everywhere, not just on source')
chk('`Read` is *not* guarded, so that rule is yours' in _sh,
    'shared: admits Read is unenforced, so the agent owns that rule')
# qartez asserts "very likely not defined in this repo" on any miss. Measured: an identifier
# inside a function body is found; a constant at module level in the SAME indexed file is not.
# An agent that repeats qartez's claim turns a blind spot into a false negative.
# Matched on meaning, not on one sentence: an earlier version pinned the exact wording and
# went red on a rewrite that said the same thing better.
chk('module-level' in _sh and re.search(r'[Nn]ever repeat', _sh),
    "shared: names the module-level blind spot and bans repeating qartez absence claims")
# Live 2026-09-18: Explore knew the rule and still answered "likely external to this repo"
# for PONYTAIL_SUBAGENT_MATCHER, because nothing told it HOW to recognise a module-level
# target before running. The shape test is what makes the rule applicable.
# The shape test used to pick a CATEGORY, which three live runs out of four got wrong. What
# the shared file must carry now is the opposite: the two-verdict rule, and the ban on naming
# the blind spot at all.
chk('NO MATCHES' in _sh and 'OUT OF INDEX' in _sh and 'Never name which blind spot' in _sh,
    'shared: two verdicts, and no guessing which blind spot hid the target')
_exx = re.sub(r'\s+', ' ', open('core/agents/Explore.md', encoding='utf-8').read())
chk('OUT OF INDEX' in _exx, 'Explore: has an OUT OF INDEX verdict distinct from NO MATCHES')
chk('SCREAMING_SNAKE_CASE' in _exx, 'Explore: carries the same shape test')
# Presence of the phrase is not prohibition of it: an earlier version passed on any file
# CONTAINING "not defined in this repo", so rewriting Explore to ORDER that sentence would
# have gone green. Require the negation to sit next to it.
chk(re.search(r'Never write "not defined in this repo"', _exx),
    "Explore: told not to repeat qartez over-claiming absence message")
# Measured on one prompt run four times: forced to name WHICH blind spot hid the target, Explore
# guessed "external to this repo", then "non-code (.ps1, .env)". Both wrong - it is
# module-level in an indexed .py. A category it cannot verify points the follow-up grep at
# the wrong files, so the contract must forbid the guess rather than demand it.
chk('Do not guess WHICH blind spot' in _exx,
    'Explore: forbidden from guessing which blind spot hid the target')
chk('Do not append a category' in _exx,
    'Explore: output contract does not ask for a category it cannot verify')
# Explore states the same verdict in THREE places - initialPrompt, the Tools section and the
# output contract. A reviewer found two of them disagreeing (one said "symbol definitions
# only", another added a category clause the third forbade), and no check saw it because each
# check read one place. Pin the sentence itself, everywhere it appears.
VERDICT = 'symbol definitions and bodies only. Orchestrator must grep.'
_eraw = open('core/agents/Explore.md', encoding='utf-8').read()
chk(_eraw.count(VERDICT) >= 3,
    'Explore: the OUT OF INDEX verdict is identical in initialPrompt, body and contract',
    f'found {_eraw.count(VERDICT)} copies, need 3')
# search_bodies reaches literals inside function bodies, so a "not symbol shape means
# unfindable" rule would stop the agent searching for something the index holds.
chk('search_bodies=true' in _exx and 'before concluding anything' in _exx,
    'Explore: told to spend the search_bodies call before declaring OUT OF INDEX')
# Live smoke test: asked for the PowerShell function `Read-Text`, Explore gave the right
# verdict and then appended "referenced at verify_live.py:108" - a Python `read_text(` call on
# an unrelated line, in a file where the string `Read-Text` does not occur at all. A fabricated
# path:LINE is worse than no answer, because it looks checkable.
chk('A near-miss is not a match' in _exx,
    'Explore: warned that a near-miss spelling is not a match')
chk('Nothing follows an `OUT OF INDEX` line' in _exx,
    'Explore: nothing may be appended after the OUT OF INDEX verdict')
# That instruction does NOT hold on haiku - measured across five runs and three rewordings,
# the category still gets appended (the fabricated file:LINE did stop). So the orchestrator
# side is the real control, and it must stay: without it a wrong category silently steers the
# follow-up grep. This is load-bearing, not advice.
chk('discard any category' in open('core/output-styles/orchestrator.md', encoding='utf-8').read(),
    'orchestrator: told to discard Explore category, which prompting does not suppress')
_eip = fmx('core/agents/Explore.md')[0].get('initialPrompt', '')
chk('Never guess WHICH blind spot' in _eip,
    'Explore: initialPrompt agrees with the body (omitClaudeMd makes it the only copy)')

print()
print('=== 2bb. NO AGENT IS TOLD TO USE A TOOL IT DOES NOT HOLD ===')
# Found 2026-09-18 by auditing text against tool lists: four agents still carried
# "`Read`/`Grep`/`Glob` are for non-code files" after Grep and Glob were removed from their
# lists. Explore was the dangerous one - it runs omitClaudeMd, so its initialPrompt is the
# only tool rule it ever sees, and that prompt named two tools the guard denies everywhere.
# An agent that follows a dead instruction burns a turn and learns its search "failed".
NAMEABLE = ['Read', 'Write', 'Edit', 'NotebookEdit', 'Grep', 'Glob', 'Bash',
            'WebFetch', 'WebSearch']
# A sentence that DENIES the tool is the correct text and must stay legal.
DENIES = ('no ', 'not ', 'never', "n't", 'cannot', 'without', 'instead of', 'denies',
          'denied', 'blocks', 'blocked', 'forbid', 'rather than', 'unavailable',
          'removed', 'lack')
for f in sorted(glob.glob('core/agents/*.md')):
    d, s = fmx(f)
    held = {t.strip() for t in d.get('tools', '').split(',')}
    body = s.split('\n---', 1)[1] if '\n---' in s else s
    dead = []
    for where, txt in (('initialPrompt', d.get('initialPrompt', '')), ('body', body)):
        # Sentence-scoped, not window-scoped: a negation in the PREVIOUS sentence does not
        # make the next sentence's instruction true. That is how the builder's line survived.
        for sent in re.split(r'(?<=[.;:!?])\s+|\n\s*\n', txt):
            low = sent.lower()
            for tool in NAMEABLE:
                # `\b` treats a hyphen as a boundary, so `\bRead\b` matched the PowerShell
                # name `Read-Text` and flagged prose that never mentions the Read tool.
                # Exclude a hyphen or underscore on either side: those make a different token.
                m = re.search(rf'(?<![\w-]){tool}(?![\w-])', sent)
                if tool in held or not m:
                    continue
                # The negation has to reach THIS tool, so look only at the ~30 characters
                # BEFORE the name: English puts it there ("no Grep", "the guard denies Grep",
                # "never run qmd"). Sentence scope exempted every tool in any sentence holding
                # any negation - "`Read` is not guarded, so use Grep for markdown" cleared
                # both names on the strength of one "not" - and a symmetric window still did.
                before = low[max(0, m.start() - 30):m.start()]
                if not any(w in before for w in DENIES):
                    dead.append(f'{where}: {tool} in {sent.strip()[:60]!r}')
    chk(not dead, f'{os.path.basename(f)}: names no tool it was not given', str(dead[:2]))
# omitClaudeMd strips the shared tool rules, so the initialPrompt is the compensating move.
# Without it the agent loses "code search is qartez" and falls back to guard-denied tools.
for f in sorted(glob.glob('core/agents/*.md')):
    d, _ = fmx(f)
    if d.get('omitClaudeMd') == 'true':
        ip = d.get('initialPrompt', '')
        chk('qartez' in ip and len(ip) > 200,
            f'{os.path.basename(f)}: omitClaudeMd, so initialPrompt carries the tool rules',
            f'{len(ip)} chars')

print()
print('=== 2c. THE FINDER IS NEVER TOLD TO FILTER ===')
# The single highest-confidence defect both A/B arms found: a precision rule sitting in the
# shared file reached the finder, whose entire mandate is to drop nothing.
chk('never the finder' in shared_txt,
    'shared: "do not chase every finding" is scoped away from the finder')
_rf = open('core/agents/refuter.md', encoding='utf-8').read()
chk('not even if a brief asks for it' in _rf,
    'refuter: no full-suite escape hatch, not even via the brief')
_orch = open('core/output-styles/orchestrator.md', encoding='utf-8').read()
# Two refuters at the SAME number as the delegation threshold means every delegated change
# gets two reviewers, and "three agents on the happy path" becomes impossible.
chk('~15 files or ~800 changed lines' in _orch,
    'orchestrator: the two-refuter threshold sits above the delegation threshold')
chk('git status --short` before and after every read-only agent' in _orch,
    'orchestrator: the git-status write detector exists (a tool list cannot stop a shell write)')
chk('ACCEPT' not in _orch.split('## Verification order')[-1].split('## Measurement')[0],
    'orchestrator: no stale ACCEPT vocabulary in the verification order')
# The write-detector only applies to agents that actually hold Bash. Naming one that does not
# makes the rule's own justification false.
chk(re.search(r'not the verifier, which has no shell', re.sub(r'\s+', ' ', _orch)) is not None,
    'orchestrator: the write-detector excludes the shell-less verifier')
chk('Hinglish stays Hinglish' in _orch,
    'orchestrator: the reply-in-the-user-language rule survives')
chk(re.search(r'findings to `FINDINGS\.md` myself', re.sub(r'\s+', ' ', _orch)) is not None,
    'orchestrator: takes the FINDINGS.md duty promised to read-only agents')
# The full-suite ban has to be absolute in every agent that can run one.
# Match on normalised whitespace: these phrases wrap across lines, and a literal `in`
# check silently fails on the line break rather than on the rule being absent.
_ABS = re.compile(r'not even if a brief asks for it', re.I)
for _n in ('refuter', 'builder', 'debugger'):
    _t = re.sub(r'\s+', ' ', open(f'core/agents/{_n}.md', encoding='utf-8').read())
    chk(_ABS.search(_t) is not None,
        f'{_n}: full-suite ban is absolute, brief cannot override it')
_skl = re.sub(r'\s+', ' ', open('core/skills/review-precision/SKILL.md', encoding='utf-8').read())
# An exclusion list that can swallow a correctness finding is the failure this skill exists
# to prevent; rules 9 and 15 each did it once.
chk(re.search(r'A \*\*correctness\*\* finding', _skl) is not None
    and 'gate 1 outranks this rule' in _skl,
    'review-precision: exclusion 9 cannot swallow a correctness finding')
chk(re.search(r'never covers a finding the gate raised and the', _skl) is not None,
    'review-precision: exclusion 15 cannot swallow an ignored gate finding')
_vf = open('core/agents/verifier.md', encoding='utf-8').read()
chk('CONFIRMED(conf%)' in _vf,
    'verifier: the JUDGED contract has a slot for the confidence its skill demands')

print()
print('=== 3. THE TWO-STAGE REVIEW IS WIRED CORRECTLY ===')
refd, ref = fmx('core/agents/refuter.md')
verd, ver = fmx('core/agents/verifier.md')
# The finder must not carry the exclusion list. A finder that filters itself drops
# half-believed candidates before anything can judge them, which is how real defects escape.
chk('review-precision' not in str(refd.get('skills')),
    'refuter: does NOT preload review-precision (a finder must not filter itself)',
    str(refd.get('skills')))
# The sweep caught the verifier being told to run qmd while holding no shell. Any agent
# without Bash must never be pointed at a CLI - it silently skips the order or invents a
# workaround, and both are worse than an honest "I cannot reach that".
# Every non-trivial pattern in this file is proved against a string it MUST match and one it
# must not, before anything depends on it. Two shipped versions of the qmd pattern matched
# nothing at all and the check built on them passed for weeks. A regex is code; untested code
# in a checker is worse than no checker, because it reports green.
QMD_RE = re.compile(r'\bqmd\b')
chk(bool(QMD_RE.search('you should run qmd update now')) and not QMD_RE.search('amqmdx'),
    'QMD_RE really matches the word qmd and nothing else (self-test)')

for _n in ('verifier', 'researcher', 'Explore'):
    _d, _ = fmx(f'core/agents/{_n}.md')
    _tl = [x.strip() for x in _d.get('tools', '').split(',')]
    _txt = (_d.get('initialPrompt', '') + ' ' +
            open(f'core/agents/{_n}.md', encoding='utf-8').read())
    if 'Bash' not in _tl:
        # Window on BOTH sides: every disclaimer in this kit reads "you cannot run qmd", so a
        # forward-only lookahead calls the correct sentence a violation. Two earlier versions
        # of this very line were unmatchable - one held literal 0x08 bytes where \b was meant,
        # the next held a doubled backslash - so QMD_RE is proved against a fixture below
        # before it is trusted. A pattern nobody proved is a check nobody has.
        _bad = [m.group(0) for m in QMD_RE.finditer(_txt)
                if not any(w in _txt[max(0, m.start() - 120):m.start() + 80].lower()
                           for w in ('cannot', 'no shell', 'never run'))]
        chk(not _bad, f'{_n}: has no shell, so is never told to run qmd', str(_bad[:1]))

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
# chars, so a line count flatters it. Budget both. The pre-split file was 12,701 bytes.
#
# Raised 7000 -> 7400 on 2026-09-18, once, deliberately, and recorded rather than quietly
# widened. What bought the extra ~100 tokens per spawn: the qartez read-dedup rule (its cache
# is per SERVER, shared by every agent of a session, so a reviewer can be handed a stub for a
# body it has never seen - reproduced live) and the two-verdict search doctrine. Four
# compression passes came first; both rules prevent an agent asserting something it cannot
# see, which is worth more than 100 tokens. Compress before raising this again.
SHARED_BYTE_BUDGET = 7400
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
        ('fable thinks, opus executes', r'Execution stays on Opus, always', ORCH),
        ('debugger inherits the orchestrator seat', r'debugger is `model: inherit`', ORCH),
        # builder.md's description legitimately names the threshold so the orchestrator can
        # pick it; the RULE sentence is what must have one owner
        ('delegation threshold', r'under \*\*~30 changed lines or ~2 files\*\*', ORCH),
        ('one refuter pass', 'ONE refuter pass', ORCH),
        ('batch review of small changes', 'Unreviewed since', ORCH),
        ('resume instead of re-spawn', r'Resume with `SendMessage`', ORCH),
        ('sibling cache stagger', 'stagger same-profile spawns', ORCH),
        ('measurement targets', r'turns before the\s*\n?first edit', ORCH),
        ('no-candidates ends the loop', 'A refuter that returns no candidates ends the loop', ORCH),
        ('ops loops go to general-purpose', r'goes to\s+`general-purpose`', ORCH),
        ('kit-init before any brief', r'`/kit-init` runs\s+before any brief', ORCH),
        ('clear after a closed bucket', r'A closed bucket ends the session: `/clear`', ORCH),
        ('context boundary exit', r'context is past ~50%', ORCH),
        ('brief size cap', r'One brief stays under ~400 changed lines or ~8 files', ORCH),
        ('orchestrator turn budget', 'my own turns per task', ORCH)]:
    owners = [f for f in cfg if re.search(pat, open(f, encoding='utf-8').read())]
    chk(owner in owners, f'{concept}: defined in {os.path.basename(owner)}', str(owners))
    chk(len(owners) == 1, f'{concept}: single definition', str(owners))
# The mid-bucket exit once told the orchestrator to run `/session-handoff`; the kit ships no
# such skill, and STATE.md is the handoff.
chk('/session-handoff' not in _orch,
    'orchestrator style does not depend on a skill the kit does not ship')

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
chk(ms.get('claude-opus-5', {}).get('effortLevel') == 'xhigh',
    'modelSettings: opus 5 xhigh (fallback orchestrator seat; agent frontmatter overrides it)',
    str(ms.get('claude-opus-5')))
chk(ms.get('claude-fable-5-1', {}).get('effortLevel') == 'high',
    'modelSettings: fable 5.1 high (the primary orchestrator seat)')
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
# A project template that tells the reviewer to rerun the full suite is how a 7-second gate
# becomes a 159-second one. The template must demand a measured, test-free fast gate.
tmpl = open('extras/project/CLAUDE.md', encoding='utf-8').read()
chk('FAST GATE' in tmpl and 'no test suite' in tmpl,
    'project template demands a test-free fast gate')
chk('full test suite is what a refuter reruns' not in tmpl,
    'project template does NOT tell the reviewer to rerun the full suite')
chk('Measured' in tmpl, 'project template asks for the gate time to be measured')
# Each of these is a lesson a real run paid for. If a future edit drops one, a new project
# silently loses it, and the next agent repeats the same mistake.
for frag, why in [
        ('Agents never run these', 'names the commands agents must not run'),
        ('Security surfaces in THIS repo', 'asks the project to name its own security surfaces'),
        ('it does not cover', 'warns that the qartez guard misses Read and Bash'),
        ('Past defects', 'keeps a past-defects table the reviewer reads')]:
    chk(frag in tmpl, f'project template {why}')
bld = open('core/agents/builder.md', encoding='utf-8').read()
chk('Never run the whole test suite' in bld, 'builder: forbidden from running the full suite')
for p in DOCS + ['extras/rejected/README.md', 'extras/prideconnect-section.md']:
    chk(os.path.isfile(p), f'{p} exists')

print()
print('=== 9b. FILES A WHOLE `Read` IS DENIED ON ===')
# md-guard denies Read on any .md over 300 lines. A verifier, which has no shell and so cannot
# run qmd, hit this three times in one run because the BRIEF told it these files were short.
# The orchestrator writes that brief, so the orchestrator has to be told. This is a census,
# not a failure: the files are allowed to be long, but an agent must be sent at a line range.
_LONG = []
for _f in sorted(set(glob.glob('*.md') + glob.glob('*.py') + glob.glob('core/**/*.md', recursive=True)
                     + glob.glob('docs/*.md') + glob.glob('extras/**/*.md', recursive=True))):
    _n = sum(1 for _ in open(_f, encoding='utf-8', errors='replace'))
    if _n > 300:
        _LONG.append((_n, slash(_f)))
for _n, _f in sorted(_LONG, reverse=True):
    print(f'  NOTE  {_f} is {_n} lines - brief agents with an offset+limit, never the whole file')
# The agents that cannot fall back to a shell must carry the rule themselves.
for _n2 in ('verifier', 'researcher'):
    _d2, _s2 = fmx(f'core/agents/{_n2}.md')
    _t2 = _d2.get('initialPrompt', '') + ' ' + _s2
    chk('offset' in _t2 and 'limit' in _t2,
        f'{_n2}: has no shell, so is told to Read long files with offset+limit')

print()
print('=== 10. THE USER-FACING DOCS DESCRIBE THE KIT THAT SHIPS ===')
# README.md and SETUP-NEW-MACHINE.md are what a new machine is set up from, so a stale claim
# there is a wrong install, not a typo. Three rounds of drift were found by hand on
# 2026-09-18 - a scout row for a deleted agent, "effort: low" for an agent now on high, and
# "the refuter runs the gate first" (the rule that killed four refuters). Pin them.
USER_DOCS = ['README.md', 'SETUP-NEW-MACHINE.md']
readme = open('README.md', encoding='utf-8').read()
orch_txt = open('core/output-styles/orchestrator.md', encoding='utf-8').read()

for name in sorted(PINS):
    d, _ = fmx(f'core/agents/{name}.md')
    # The README roster row and the orchestrator roster row must both name the real model.
    for label, txt in (('README', readme), ('orchestrator style', orch_txt)):
        row = re.search(rf'^\|\s*\*?\*?`?{re.escape(name)}`?\*?\*?\s*\|([^|]*)\|',
                        txt, re.M)
        chk(row is not None, f'{label}: has a roster row for {name}')
        if row:
            cell = row.group(1)
            chk(d['model'] in cell,
                f'{label}: {name} row says model {d["model"]}', cell.strip()[:60])
            # An effort or maxTurns number quoted in the row must be the one in the file.
            for key in ('effort', 'maxTurns'):
                for claimed in re.findall(rf'{key}:\s*(\w+)', cell):
                    chk(str(d.get(key, '')) == claimed,
                        f'{label}: {name} row {key} {claimed} matches the file',
                        f'file says {d.get(key)!r}')
            # The orchestrator roster writes effort as "opus · high", with no "effort:" prefix,
            # so the loop above emitted NO check for it at all: the file could say `low` and
            # the table `high` with the gate green. Read the bare word after the model too.
            # `[*`]*` skips the markdown emphasis the roster uses around `**inherit**`.
            bare = re.search(
                rf'{re.escape(d["model"])}[*`]*\s*[·|,]\s*[*`]*(low|medium|high|xhigh|max)',
                cell)
            if bare:
                chk(d.get('effort', '') == bare.group(1),
                    f'{label}: {name} row effort {bare.group(1)} matches the file',
                    f'file says {d.get("effort")!r}')

for doc in USER_DOCS:
    s = open(doc, encoding='utf-8').read()
    # Two escape hatches removed: `(?! agent)` exempted the phrase "scout agent", which is the
    # most likely shape of a live reference, and `or 'retired' in s` passed the whole check
    # when the word "retired" appeared anywhere in the document on any subject. A mention is
    # allowed only when the word "retired" or "deleted" sits within 60 characters of it.
    _live = [m.group(0) for m in re.finditer(r'\bscout\b', s, re.I)
             if not re.search(r'retired|deleted|removed|replaced',
                              s[max(0, m.start() - 60):m.start() + 60], re.I)]
    chk(not _live, f'{doc}: no live reference to the retired scout agent', str(_live[:1]))
    # The v1 rule. Its removal is the single largest wall-clock win in the rework. A negated
    # mention ("the refuter no longer runs the gate") is the correct text, so it is allowed.
    NEG = ('no longer', 'never', 'not ', "n't", 'zero', 'stopped', 'used to')
    for pat, why in [(r'refuter[^.]{0,80}runs? the (?:fast )?gate', 'runs the gate'),
                     (r'refuter[^.]{0,60}full (?:test )?suite', 'runs the full suite')]:
        hits = [m.group(0) for m in re.finditer(pat, s, re.I)
                if not any(w in m.group(0).lower() for w in NEG)]
        chk(not hits, f'{doc}: never says the refuter {why}', str(hits[:1]))

# The delegation threshold is one number with one owner. A doc quoting a different one sends
# a reader back to spawning a pair for a two-line change.
thr = re.search(r'~(\d+) changed lines or ~(\d+) files', orch_txt)
chk(thr is not None, 'orchestrator style states the delegation threshold')
if thr:
    want = (thr.group(1), thr.group(2))
    for doc in USER_DOCS:
        s = open(doc, encoding='utf-8').read()
        # EVERY statement of it must agree, not just one of them: README states it twice,
        # so an "at least one correct mention" check passes with the other one stale.
        said = re.findall(r'~?(\d+)\s+changed lines\s*(?:or|/)\s*~?(\d+)\s+files', s)
        chk(said and all(p == want for p in said),
            f'{doc}: every delegation threshold reads {want[0]} lines / {want[1]} files',
            str(said))
# Two refuters must cost MORE than one builder+refuter pair, or every delegated change gets
# two reviewers. This equalled the delegation threshold until 2026-09-18; lowered to 30/2 on
# 2026-09-22.
two = re.search(r'~(\d+) files or ~(\d+) changed lines\*\*[^*]{0,90}gets TWO refuters', orch_txt)
chk(two is not None, 'orchestrator style states the two-refuter threshold')
# No per-doc restatement check for this one: both thresholds are written in the same sentence
# shape ("~N changed lines or ~M files"), so a regex cannot tell a delegation mention from a
# two-refuter mention, and one written to try flagged the correct 400/8 lines as wrong. The
# "strictly above" check below is what actually protects the number that matters. The brief
# size cap (orchestrator.md, "One brief stays under") is a third sentence in that same shape,
# and it must never be restated in USER_DOCS with the `N changed lines or M files` wording —
# a restatement there is indistinguishable from the other two and drifts unnoticed.
if two and thr:
    chk(int(two.group(2)) > int(thr.group(1)) and int(two.group(1)) > int(thr.group(2)),
        'two-refuter threshold is strictly above the delegation threshold',
        f'{two.group(2)}/{two.group(1)} vs {thr.group(1)}/{thr.group(2)}')

# verify_live.py covers what this file structurally cannot (the installed tree). A setup doc
# that does not send the reader to it leaves a stale install undetectable.
_setup = open('SETUP-NEW-MACHINE.md', encoding='utf-8').read()
for script, why in [
        ('verify_live.py', 'checks the installed tree, which this file cannot see'),
        ('agent_stats.py', 'turns the scoreboard into numbers read off the transcripts'),
        ('audit_project.py', 'keeps a project from restating or overriding a global rule')]:
    chk(os.path.isfile(script), f'{script} exists ({why})')
    chk(script in _setup, f'SETUP-NEW-MACHINE.md tells the reader to run {script}')

# "Fully global" (2026-09-19): a new project needs nothing copied in by hand. That rests on
# three shipped pieces plus the installer putting two of them where /kit-init can reach them
# from ANY repo. Lose any one and the next new project silently starts with no gate.
for p, why in [('core/hooks/kit-session-start.py', 'the SessionStart notice'),
               ('core/hooks/kit-session-start_test.py', 'its self-test'),
               ('core/commands/kit-init.md', 'the command that measures and writes the gate'),
               ('core/hooks/kit-subagent-report.py', 'the SubagentStop report filer'),
               ('core/hooks/kit-subagent-report_test.py', 'its self-test'),
               ('core/hooks/kit-subagent-start.py', 'the SubagentStart decisions injector'),
               ('core/hooks/kit-subagent-start_test.py', 'its self-test')]:
    chk(os.path.isfile(p), f'{p} exists ({why})')
_inst = open('install.ps1', encoding='utf-8').read() if os.path.isfile('install.ps1') else ''
for frag, label in [('kit-session-start.py', 'installer registers the SessionStart hook'),
                    ("startup|resume|clear|compact", 'SessionStart hook matches every session kind'),
                    ('kit-session-start_test.py', 'installer runs the hook self-test'),
                    ('kit-subagent-report.py', 'installer registers the SubagentStop hook'),
                    ('SubagentStop', 'the report filer is hung on the SubagentStop event'),
                    ('kit-subagent-report_test.py', 'installer runs the report filer self-test'),
                    ('kit-subagent-start.py', 'installer registers the SubagentStart hook'),
                    ('builder|refuter|verifier|debugger|researcher',
                     'the injector matches the five briefed agents and never Explore'),
                    ('kit-subagent-start_test.py', 'installer runs the injector self-test'),
                    ("kit\\project-template.md", 'installer publishes the project template to ~/.claude/kit'),
                    ("kit\\audit_project.py", 'installer publishes audit_project.py to ~/.claude/kit')]:
    chk(frag in _inst, label)
# A hook `timeout` is SECONDS, not milliseconds: 5000 is 83 minutes of a wedged hook holding
# up every Read, every session start and every finished subagent.
chk('timeout = 5000' not in _inst and len(re.findall(r'timeout = 5\b', _inst)) == 4,
    'all four hook registrations use timeout = 5 seconds, none the 5000 that reads as ms')
chk(all(r in su.get('permissions', {}).get('deny', [])
        for r in ('Agent(model:fable)', 'Agent(model:claude-fable-5-1)')),
    'settings deny an explicit Fable subagent, so a Fable spawn fails loudly instead of '
    'spending Fable quota', str(su.get('permissions', {}).get('deny', [])))
# md-guard's shell denial is keyed on agent_type, so its set has to BE the roster's read-only
# shell holders. A new agent with Bash and no Edit would otherwise write the tree freely while
# its file still calls it read-only.
_mg = open('core/hooks/md-guard.py', encoding='utf-8').read()
_ro = re.search(r'READ_ONLY_AGENTS = \{([^}]*)\}', _mg)
_ro_set = set(re.findall(r'''["']([^"']+)["']''', _ro.group(1))) if _ro else set()
_shell_only = set()
for _f in sorted(glob.glob('core/agents/*.md')):
    _head = open(_f, encoding='utf-8').read().split('\n---', 1)[0].lstrip('-\n')
    _d = ((_yaml.safe_load(_head) if _yaml else fm(_f)[0]) or {})
    # No `tools:` key means the agent holds EVERY tool, so it holds Bash and Edit unless
    # disallowedTools takes them away. Reading a missing key as "no tools" let such an agent
    # skip this check entirely.
    _dis = {t.strip() for t in str(_d.get('disallowedTools', '')).split(',')}
    _tools = ({t.strip() for t in str(_d['tools']).split(',')} if 'tools' in _d
              else {'Bash', 'Edit'}) - _dis
    if 'Bash' in _tools and 'Edit' not in _tools:
        _shell_only.add(str(_d.get('name') or os.path.basename(_f)[:-3]))
chk(_ro_set == _shell_only,
    "md-guard's read-only agent set equals every agent that holds Bash without Edit",
    f'{sorted(_ro_set)} vs {sorted(_shell_only)}')
chk('kit-subagent-start.py' in _setup,
    'SETUP-NEW-MACHINE.md names the SubagentStart decisions injector')
_ki = open('core/commands/kit-init.md', encoding='utf-8').read() if os.path.isfile('core/commands/kit-init.md') else ''
chk('never guess' in _ki.lower() and ('time' in _ki.lower()), '/kit-init measures the gate, never guesses it')
chk('60' in _ki and 'test' in _ki.lower(), '/kit-init refuses a slow gate or a test runner')
chk('do not overwrite' in _ki.lower(), '/kit-init never overwrites an existing CLAUDE.md')
chk('~/.claude/kit/project-template.md' in _ki and '~/.claude/kit/audit_project.py' in _ki,
    '/kit-init reads the template and the audit from the global kit dir, not this checkout')
# 2.1.277 reads AGENTS.md only while no CLAUDE.md sits at or above the working directory, so
# the file /kit-init writes silently switches it off unless it imports it.
chk('AGENTS.md' in _ki and '@AGENTS.md' in _ki,
    '/kit-init keeps a repo AGENTS.md alive with an @AGENTS.md import')
chk('If no candidate exists' in _ki and 'none — <what you checked>' in _ki
    and 'SKIPPED (no gate in CLAUDE.md)' in _ki,
    '/kit-init writes a none gate row for a repo with no checker')
# An end-to-end run wrote `python main.py` as the FAST GATE because AGENTS.md said to run it
# before commits. Running the program is not a static check; both ends of the loop refuse it.
chk('A gate is a static check' in _ki and 'never a gate' in _ki,
    '/kit-init refuses a program run as the gate')
chk('cp -n ~/.claude/kit/project-template.md ./CLAUDE.md' in _ki,
    '/kit-init names the one copy command that passes the guards')
# An interpreter's byte-compiler is always present and checks only syntax, so "compile" in the
# gate-kind list read as a candidate: two runs on identical repos disagreed on the row.
chk('byte-compiler' in _ki and 'compileall' in _ki,
    '/kit-init refuses an interpreter byte-compile as the gate')
_ap = open('audit_project.py', encoding='utf-8').read() if os.path.isfile('audit_project.py') else ''
chk('@AGENTS.md' in _ap, 'audit_project.py catches a CLAUDE.md that ignores the AGENTS.md beside it')
# A `none` gate row is an answer, not a gap: both ends of the loop must say so.
chk('A `none` row means `SKIPPED`' in open(SHARED, encoding='utf-8').read(),
    'core/CLAUDE.md tells the builder a none row means SKIPPED')
chk('none row accepted' in _ap, 'audit_project.py accepts a none gate row')
chk('not a program run' in _ap, 'audit_project.py rejects a program run as the gate')
# A label is not the regex behind it: both of the above passed while the checks read the whole
# row instead of the Command cell. Run three real rows through the script (~0.3 s).
import subprocess, tempfile


def _audit_row(row):
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, 'CLAUDE.md'), 'w', encoding='utf-8') as fh:
            fh.write('## Commands\n\n| Purpose | Command | Measured |\n|---|---|---|\n'
                     + row + '\n\n### Agents never run these\n')
        r = subprocess.run([sys.executable, 'audit_project.py', td],
                           capture_output=True, text=True, encoding='utf-8')
        return (r.stdout or '') + (r.stderr or '')


_PROG = 'the FAST GATE row is a static check, not a program run'
_TIMED = 'the FAST GATE row states a measured time'
# Read the probe's OWN label line (`  ok   <label>` / `  FAIL <label>`), never the final
# CLEAN verdict: audit_project.py's later sections read ~/.claude, so CLEAN also depends on
# whether the kit is installed on this machine, which is not what these three probe.
_probe = _audit_row('| **FAST GATE — agents run this** | python main.py | 0.03 s |')
chk(f'FAIL {_PROG}' in _probe, 'audit_project.py flags python main.py as a program run (probe)',
    _probe[:300])
_probe = _audit_row('| **FAST GATE — agents run this** | `none — nothing to check, '
                    '2026-09-22` | — |')
chk(f'ok   {_TIMED}' in _probe and f'FAIL {_PROG}' not in _probe,
    'audit_project.py accepts a backticked none row (probe)', _probe[:300])
_probe = _audit_row('| **FAST GATE — agents run this** | python manage.py check | 2 s |')
chk(f'ok   {_PROG}' in _probe, 'audit_project.py accepts python manage.py check (probe)',
    _probe[:300])

# Plugin policy (2026-09-20). Claude Code cannot disable one plugin's hooks, so a plugin whose
# SessionStart/UserPromptSubmit/Stop hook fires in every session is disabled whole and the part
# worth keeping ships as a kit skill. core/plugins.json is the single record of that verdict;
# an unreasoned entry is how a plugin gets waved through six months from now.
try:
    _pl = json.load(open('core/plugins.json', encoding='utf-8'))
except Exception as e:
    _pl = {}
    chk(False, 'core/plugins.json parses', str(e))
for _m in ('disable', 'allow'):
    chk(isinstance(_pl.get(_m), dict), f'core/plugins.json has a {_m} map')
    for _id, _why in (_pl.get(_m) or {}).items():
        chk(isinstance(_why, str) and _why.strip(), f'plugins.json {_m}[{_id}] gives a reason')
chk('simple-english@simple-english' in (_pl.get('disable') or {}),
    'plugins.json disables simple-english (its hooks fight the report rules)')
# The env pin above already assumes ponytail runs, so silence here would be a contradiction.
chk('ponytail@ponytail' in (_pl.get('allow') or {}), 'plugins.json allows ponytail')
chk(os.path.isfile('core/skills/simple-english/LICENSE'),
    'core/skills/simple-english/LICENSE ships (the copy is MIT, attribution required)')
_se = 'core/skills/simple-english/SKILL.md'
chk(os.path.isfile(_se), f'{_se} exists (the slash-only copy of the plugin skill)')
if os.path.isfile(_se):
    _head = open(_se, encoding='utf-8').read().split('\n---', 1)[0].lstrip('-\n')
    _sed = ((_yaml.safe_load(_head) if _yaml else fm(_se)[0]) or {})
    # Without this key the skill loads itself on any plain-English-looking request, which is
    # exactly the automatic behaviour the plugin was disabled for.
    chk(_sed.get('disable-model-invocation') in (True, 'true'),
        f'{_se}: disable-model-invocation true (slash-only)', repr(_sed.get('disable-model-invocation')))
for _frag, _label in [('plugins.json', 'installer reads the plugin policy'),
                      ('enabledPlugins', 'installer writes the disable verdict into settings')]:
    chk(_frag in _inst, _label)
_vl = open('verify_live.py', encoding='utf-8').read() if os.path.isfile('verify_live.py') else ''
for _frag, _label in [('C6', 'verify_live.py has the plugins section'),
                      ('plugins.json', 'verify_live.py reads the plugin policy')]:
    chk(_frag in _vl, _label)
for _frag, _label in [('plugins.json', 'SETUP-NEW-MACHINE.md documents the plugin policy'),
                      ('FABLE-OPUS-SPLIT.md', 'SETUP-NEW-MACHINE.md points at the model split')]:
    chk(_frag in _setup, _label)
# Both fragments above are substrings anywhere in the file: read in the wrong order, the
# policy is applied to a $set that was already serialized and the write does nothing.
_i_pol, _i_ser = _inst.find('plugins.json'), _inst.find('$json = ($set | ConvertTo-Json')
chk(0 <= _i_pol < _i_ser, 'installer applies the plugin policy before settings.json is serialized',
    f'plugins.json at {_i_pol}, serialize at {_i_ser}')
# The self-check counts are pinned in verify_live.py and quoted in the setup doc. They drifted
# apart once already (doc said 42/42 while the suite had grown to 83), and a reader on a fresh
# machine then reads a real pass as a failure.
for _hook in ('md-guard', 'kit-subagent-start'):
    _m = re.search(rf'{_hook} self-check (\d+/\d+)', _vl)
    chk(_m is not None and _m.group(1) in _setup,
        f'setup doc quotes the same self-check counts verify_live pins ({_hook})',
        _m.group(1) if _m else 'no count pinned in verify_live.py')

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
