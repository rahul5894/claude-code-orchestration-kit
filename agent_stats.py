#!/usr/bin/env python3
"""Scoreboard from the subagent transcripts Claude Code already writes to disk.

Every claim about whether the kit got faster or cheaper was previously my word against
yours. These numbers are read from
`~/.claude/projects/<project>/<sessionId>/subagents/agent-*.jsonl`, which is the same place
the 2026-09-18 rework measurements came from. Nothing here calls a model.

    python agent_stats.py                    # this repo, all sessions
    python agent_stats.py --project PrideConnect
    python agent_stats.py --since 2026-09-18 # only transcripts newer than a date

Columns, and why each one is on the list:

  turns     assistant turns. Wall-clock is a near-linear function of this and nothing else
            (measured: median 5.2 s per turn, flat across a 200k-900k context). Target <25.
  tools     tool calls. A capped agent can exceed its own maxTurns, so this is the honest
            effort number.
  orient    turns before the first Edit or Write. Builders spent 36-50% of their turns here
            before briefs carried pre-resolved anchors. Target <10; n/a for read-only agents.
  denied    guard denials. Every one is a wasted round trip caused by an agent holding or
            being told to use a tool the guard rejects. Target 0.
  suite     full-test-suite or gate commands run INSIDE the agent. The v1 rule put these in
            review agents and cost 92 of 528 agent-minutes. Target 0 for any reviewer.
  cold      first request paid full prefix price (no cache read). Two same-profile siblings
            launched together both go cold, which is why spawns are staggered ~5 s.
  mins      wall-clock for the agent.
"""
import argparse
import collections
import datetime as dt
import glob
import json
import os
import pathlib
import re
import sys

PROJECTS = pathlib.Path(os.path.expanduser('~/.claude/projects'))
# A Bash command that runs a whole suite or a gate. Deliberately broad: a false positive here
# costs a glance, a false negative hides the exact regression this column exists to catch.
SUITE = re.compile(r'\b(pytest|jest|vitest|go test|cargo test|npm (run )?test|mvn test|'
                   r'check-all|check_all|flutter test|dart test|tox|nox|make test)\b')
DENIED = re.compile(r'STOP: qartez MCP is available|md-guard:|permission denied|'
                    r'was blocked|is not allowed', re.I)
EDITORS = {'Edit', 'Write', 'NotebookEdit', 'MultiEdit'}


def walk(path):
    """Yield one summary dict per transcript. Streams line by line: these files reach tens of
    megabytes and loading one whole would defeat the point of measuring cost."""
    tools = denied = suite = 0
    orient = None
    first = last = None
    models = collections.Counter()
    toolnames = collections.Counter()
    cold = None
    # Claude Code writes ONE JSONL line per content block, so an assistant turn that emitted
    # text plus two tool calls is three lines. Counting lines inflated `turns` by 2.3x-3.9x on
    # real transcripts here and made every run look like it blew the <25 target. The turn is
    # the API response, so count distinct message ids and fall back to the line only when a
    # record carries no id.
    turn_ids = set()
    idless_turns = 0

    def turn_count():
        return len(turn_ids) + idless_turns

    for line in open(path, encoding='utf-8', errors='replace'):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        ts = d.get('timestamp')
        if ts:
            first = first or ts
            last = ts
        m = d.get('message')
        if not isinstance(m, dict):
            continue
        if d.get('type') == 'assistant':
            if m.get('id'):
                turn_ids.add(m['id'])
            else:
                idless_turns += 1
            if m.get('model'):
                models[m['model']] += 1
            u = m.get('usage') or {}
            if cold is None and (u.get('input_tokens') or u.get('cache_read_input_tokens')):
                cold = not u.get('cache_read_input_tokens')
        for c in (m.get('content') or []):
            if not isinstance(c, dict):
                continue
            if c.get('type') == 'tool_use':
                tools += 1
                name = c.get('name', '?')
                toolnames[name] += 1
                if name in EDITORS and orient is None:
                    orient = turn_count()
                if name in ('Bash', 'PowerShell'):
                    cmd = str((c.get('input') or {}).get('command', ''))
                    if SUITE.search(cmd):
                        suite += 1
            elif c.get('type') == 'tool_result':
                # `is_error` FIRST, pattern second. Matching the pattern against any tool
                # result made an agent that merely READ this file count a denial, because the
                # DENIED source line is in it; and qartez_map output listing `md-guard.py`
                # scored another. A denial is an error whose text is the guard's.
                if not c.get('is_error'):
                    continue
                # content is a LIST of blocks; stringifying and cutting at 400 chars spent the
                # budget on repr punctuation and missed a denial in any later block.
                body = c.get('content')
                if isinstance(body, list):
                    body = ' '.join(str(b.get('text', b)) if isinstance(b, dict) else str(b)
                                    for b in body)
                if DENIED.search(str(body)):
                    denied += 1
    turns = turn_count()
    mins = None
    if first and last:
        try:
            mins = (dt.datetime.fromisoformat(last.replace('Z', '+00:00'))
                    - dt.datetime.fromisoformat(first.replace('Z', '+00:00'))).total_seconds() / 60
        except ValueError:
            pass
    return dict(file=os.path.basename(path), turns=turns, tools=tools, orient=orient,
                denied=denied, suite=suite, cold=cold, mins=mins,
                model=(models.most_common(1)[0][0].split('-2')[0] if models else '?'),
                toolnames=toolnames, mtime=os.path.getmtime(path))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--project', default=None,
                    help='substring of the project folder name; default is this repo')
    ap.add_argument('--since', default=None, help='YYYY-MM-DD, by transcript mtime')
    ap.add_argument('--tools', action='store_true', help='also print the tool histogram')
    a = ap.parse_args()

    key = a.project or pathlib.Path.cwd().name
    dirs = [d for d in PROJECTS.glob('*') if key.lower().replace('-', '') in
            d.name.lower().replace('-', '')]
    if not dirs:
        sys.exit(f'no project folder under {PROJECTS} matching {key!r}')
    files = sorted(f for d in dirs for f in glob.glob(str(d / '*' / 'subagents' / 'agent-*.jsonl')))
    if a.since:
        cut = dt.datetime.fromisoformat(a.since).timestamp()
        files = [f for f in files if os.path.getmtime(f) >= cut]
    if not files:
        sys.exit(f'no subagent transcripts found for {key!r}'
                 + (f' since {a.since}' if a.since else ''))

    rows = sorted((walk(f) for f in files), key=lambda r: r['mtime'])
    # A substring match can hit several folders (a repo and its temp scratchpad copy, say).
    # Printing only dirs[0] labelled two projects' totals as one.
    label = dirs[0].name if len(dirs) == 1 else f'{len(dirs)} folders: ' + ', '.join(
        d.name[-34:] for d in dirs)
    print(f'{len(rows)} agent runs · project {label}'
          + (f' · since {a.since}' if a.since else ''))
    print(f"{'agent':20s} {'model':18s} {'turns':>5s} {'tools':>5s} {'orient':>6s} "
          f"{'denied':>6s} {'suite':>5s} {'cold':>4s} {'mins':>5s}")
    agg = collections.Counter()
    live = 0
    for r in rows:
        # A transcript with no assistant turn is an agent still in flight (or one that died
        # before its first response). Counting it as a 0-turn run would flatter every mean.
        if r['turns'] == 0:
            live += 1
            print(f"{r['file'][6:18]:20s} {'(running or no response yet)':18s}")
            continue
        agg['turns'] += r['turns']
        agg['tools'] += r['tools']
        agg['denied'] += r['denied']
        agg['suite'] += r['suite']
        # cold is None when no assistant message carried usage at all. Printing that as "no"
        # and counting it as warm reports an unknown as a measured negative, in the column
        # used to justify the spawn stagger.
        agg['cold'] += 1 if r['cold'] else 0
        agg['unknown_cold'] += 1 if r['cold'] is None else 0
        agg['mins'] += r['mins'] or 0
        print(f"{r['file'][6:18]:20s} {r['model'][:18]:18s} {r['turns']:5d} {r['tools']:5d} "
              f"{(r['orient'] if r['orient'] is not None else '-'):>6} "
              f"{r['denied']:6d} {r['suite']:5d} "
              f"{('?' if r['cold'] is None else 'yes' if r['cold'] else 'no'):>4s} "
              f"{(round(r['mins'], 1) if r['mins'] is not None else '-'):>5}")
        if a.tools:
            for n, c in r['toolnames'].most_common():
                print(f"      {c:4d}  {n}")
    n = len(rows) - live
    if not n:
        sys.exit('\nevery transcript is still in flight - nothing to total yet')
    print(f"\nTOTAL  runs {n}" + (f" (+{live} in flight, excluded)" if live else '')
          + f" · turns {agg['turns']} (mean {agg['turns']/n:.1f}) · "
          f"tools {agg['tools']} (mean {agg['tools']/n:.1f}) · "
          f"agent-minutes {agg['mins']:.1f}")
    # These three are the regressions the rework closed. Any non-zero is worth a look, not an
    # automatic failure: a builder legitimately runs the gate, and a cold sibling is expected.
    print(f"guard denials {agg['denied']} (target 0) · "
          f"suite/gate runs inside agents {agg['suite']} (target 0 for reviewers) · "
          f"cold-cache starts {agg['cold']}/{n}"
          + (f" ({agg['unknown_cold']} unknown)" if agg['unknown_cold'] else ''))


if __name__ == '__main__':
    main()
