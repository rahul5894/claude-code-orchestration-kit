# New machine setup: orchestration kit, qmd, md-guard

This page is for you, on a fresh Windows machine. Follow it top to bottom.
It takes about 20 minutes. Every step has a check. Do not skip a check.

Last verified: 2026-09-16 on Windows 11, Claude Code 2.1.270, qmd 2.8.3, Python 3.12.10.

## 1. Prerequisites

Install these first. Open a new terminal after each install so PATH updates.

| Tool | Why | Check |
|---|---|---|
| Claude Code (VS Code extension or CLI) | the host | `claude --version` |
| PowerShell 7 | runs `install.ps1` | `pwsh --version` |
| Git | clones the kit | `git --version` |
| Node 22 or newer | qmd is an npm package | `node --version` |
| Python 3.12 or newer, on PATH | runs the md-guard hook | `python -c "import sys; print(sys.version)"` |

If Python is missing: `winget install Python.Python.3.12`. The installer looks for
`python3.13`, `python3.12`, `python`, `python3`, `py` in that order and pins the first
one that reports 3.12 or newer.

## 2. Orchestration kit

```powershell
git clone <your-remote> D:\Projects\claude-code-orchestration-kit
cd D:\Projects\claude-code-orchestration-kit
pwsh -NoProfile -File .\install.ps1
```

Expected output, in this order:

```
agents:   builder, debugger, refuter, researcher, scout
commands: task
CLAUDE.md: kit block appended        (or "replaced" / "unchanged" on a re-run)
settings.json: merged (backup written)
md-guard: registered in settings.json
md-guard self-check: 24/24 passed
done. ...
```

What the installer does. It copies `core/agents/*.md` and `core/commands/*.md` into
`~/.claude/`. It writes the kit block into `~/.claude/CLAUDE.md` between two marker
comments and leaves your own text alone. It deep-merges `core/settings.user.json` into
`~/.claude/settings.json` and writes a backup first. It copies `core/hooks/*.py` into
`~/.claude/hooks/` and registers the md-guard hook once. It is safe to run again after
every kit change. A second run prints `unchanged` and `already registered`.

Checks:

1. `~/.claude/agents/` has 6 files. `builder.md` and `researcher.md` say `effort: high`.
   `refuter.md` says `effort: xhigh` and `maxTurns: 40`. `scout.md` says `effort: low`.
   `verifier.md` says `effort: low` and `maxTurns: 8`.
2. `~/.claude/settings.json` has no `CLAUDE_CODE_EFFORT_LEVEL` and no
   `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` under `env`. Either one silently overrides every
   agent file. The installer warns if it finds them.
3. Start a new Claude Code session. `/status` shows the settings file loaded.

## 3. qmd (local markdown search)

qmd is the search engine that keeps big markdown docs out of the context window. It
indexes `.md` files and returns file, line and a short window instead of the whole file.

```powershell
npm install -g @tobilu/qmd
qmd --version                                    # 2.8.3 or newer
qmd collection add D:\Projects\PrideConnect\Planning --name planning
qmd update
qmd search "next session pick" -c planning --full-path -n 5
```

The last command must print hits with `D:\...\file.md:LINE` paths. If it prints
`qmd://` URIs, `--full-path` is missing.

One collection per project. Add one the first time you use qmd in a repo:
`qmd collection add <docs-dir> --name <repo>`. The docs dir is the folder that holds the
project's planning markdown, or the repo root. `qmd collection list` shows what exists.

Rules that are not optional:

- Always pass `-c <collection>`. Without it, other projects' documents leak into the
  results.
- Always pass `--full-path`. Without it, nothing else can open the hit.
- Read a hit with `qmd get "<path>:<line>:<count>"`. Never pipe qmd into `head`,
  `tail` or `sed`. It slices itself, and piping breaks its document ids.
- Run `qmd cleanup` after you move or delete documents. `qmd update` alone leaves ghost
  entries.
- Never run `qmd embed`, `qmd query` or `qmd vsearch`. See "What we found" below.
- Do not install the qmd Claude Code plugin or skill. Its instructions say "default to
  `qmd query`", which hangs on this setup. The routing rules live in
  `~/.claude/CLAUDE.md` instead.

## 4. md-guard hook

`~/.claude/hooks/md-guard.py` is a PreToolUse hook on `Read`, `Bash` and `PowerShell`.
It makes the qmd rules enforced instead of remembered.

It denies:

- `Read` of a `.md` file with more than 300 lines, unless `limit` is 300 or less.
- A shell read (`cat`, `sed`, `grep`, `rg`, `head`, `tail`, `awk`, `Get-Content`,
  `Select-String`) of a `.md` file with more than 300 lines, or of a path it cannot
  find, when the command has no column cap.

It allows: small files, writes (`>`, `>>`, heredocs, `sed -i`, `tee`), counts
(`wc`, `grep -c`), capped output (`| cut -c1-300`, PowerShell `.Substring(`), any
command that calls `qmd`, and `git` commands. Each `&&` / `;` segment of a command is
judged on its own, so `rm big.md; git status | head` passes.

The deny message tells Claude the exact qmd or capped command to run instead.

Check: `python ~/.claude/hooks/md-guard_test.py` prints `24/24 passed`. The test
builds its own fixtures in a temp folder, so it runs on any machine. The installer runs
it for you.

Known gaps, on purpose:

- `grep -rn X some/dir/` with no `.md` in the command is not gated.
- Any crash inside the hook allows the call. It is a token guard, not a security
  boundary.
- A partial `Read` (with `limit`) still counts as "read" for a later `Edit`, so agents
  can append to big docs without reading them whole. Verified 2026-09-16.

## 5. What we found on 2026-09-16, so you do not find it again

- The qmd Claude Code plugin cache was stuck at version `0.1.0` from February to
  August 2026. Anyone who installed the plugin never received skill updates until
  qmd 2.8.3 fixed the version bump (qmd issue #789). We do not use the plugin, so this
  cannot hit us, but it is the reason "the skill looks stale" reports existed.
- `qmd query` and `qmd vsearch` hang with no output when no embeddings exist. They try
  to pull GGUF models. `qmd embed` would download about 2.5 GB of models. BM25
  `qmd search` is enough at our corpus size, so all three stay banned.
- qmd 2.5.2 fixed global npm installs failing on Windows (qmd issues #668, #452). Do
  not install anything older than 2.5.2 on Windows.
- Some of our planning docs have paragraph-long lines. A `grep -n "^## " file | head -80`
  returned 123 KB because 80 lines were 1.5 KB each. `head` limits lines, not columns.
  This is why the hook demands a column cap and why the qmd window is the right tool.
- The hook's first version had four false positives that would have broken daily
  work: heredoc writes, `cat >>` appends, `sed -i` edits, and a `head` in an unrelated
  command segment. It also missed `bash -c` and the PowerShell tool. All six are now
  test cases.
- Effort decision: builder and researcher run at `high`, refuter at `xhigh`. The brief
  already names the pattern, so the builder does not need extra thinking. Reviewing
  does. Fable (main session) decides, Opus executes. Opus tokens are not the
  constraint. Fable context size and wall-clock are.
- Review loop, revised 2026-09-16 after measuring 7 agents and about 37 minutes per
  item: the refuter now runs ONCE per change with both mandates and a `maxTurns: 40`
  cap, and runs only the tests the brief names. A REWORK goes to one builder pass and
  then to the read-only `verifier` (`maxTurns: 8`), which answers FIXED or NOT FIXED
  per must-fix line. A second REWORK stops the loop. Small changes (2 files, 40 lines,
  no security surface) spawn nothing: they are noted under `## Unreviewed since <sha>`
  in the bucket's `STATE.md` and reviewed in one batch at commit, at 3 changes or 5
  files, or with the next builder change. A security-surface change is never batched.
  Live test on 2026-09-16: the
  verifier confirmed one real fix with three line numbers and refuted one planted fake
  fix with the exact line. Research basis: startdebugging.net (117 transcripts: cost is
  the agent loop, not the startup context), dev.to "6 stages to 1" (a chain that
  re-reviews after every fix never reaches zero findings), claude-code issue #89249
  (built-in `/review` fanned out to 14 agents, so it is not a cheaper substitute).
- Machine gate before any agent. The F-511 rework was for three stale `.g.dart` files,
  which `dart run build_runner build --only-check` reports in 19 seconds; the agents
  spent about 19 minutes on it. Each project names a fast gate in its own `CLAUDE.md`
  (PrideConnect: `make gate-fast`, about a minute: codegen staleness, `flutter
  analyze`, `go build`, `go vet`). The orchestrator runs it before spawning a refuter. A
  red gate goes straight back to the builder with the gate output; no review agents run
  until it is green.
- Permission deny rules must use `Edit(path)`, never `Write(path)`. Claude Code only
  matches file checks against `Edit` rules, and `Edit` rules cover every file-editing
  tool. The kit shipped `Write(...)` entries that did nothing and printed a warning on
  every headless run. Removed 2026-09-16 from the kit and from `~/.claude/settings.json`.
- Run an agent headless to test it without restarting the session:
  `claude -p --agent verifier --output-format text --allowedTools "Read,Grep,Glob" < prompt.txt`.
  The interactive `Agent` tool only lists agent files that existed when the session
  started.
- Claude Code 2.1.271 adds `omitClaudeMd` to agent frontmatter. It lets a subagent run
  without loading CLAUDE.md files. It fits `scout` (locations only). We were on 2.1.270,
  so it is not applied yet. Apply it to `scout.md` after the upgrade and re-run the
  installer.

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `md-guard: no Python 3.12+ on PATH` | Python missing or old | install 3.12, open a new terminal, re-run `install.ps1` |
| Hook never fires | settings loaded before the change | start a new Claude Code session |
| Hook fires on a file you must read | it has more than 300 lines | `Read` with `offset` + `limit`, or `qmd get "<path>:<line>:<count>"` |
| `qmd search` returns other projects' docs | `-c` missing | add `-c <collection>` |
| `qmd search` prints `qmd://` URIs | `--full-path` missing | add `--full-path` |
| `qmd query` hangs | no embeddings, model download | never use it; use `qmd search` |
| `qmd` command not found after npm install | npm global bin not on PATH | `npm config get prefix`, add that folder to PATH |
| Two md-guard entries in settings.json | edited by hand | delete one; the installer only ever adds one |
| Agents ignore their `effort` | `CLAUDE_CODE_EFFORT_LEVEL` set in `env` | remove it from `settings.json` |

## 7. Final checklist

- [ ] `pwsh install.ps1` printed `md-guard self-check: 24/24 passed`
- [ ] `qmd search "<anything>" -c <collection> --full-path -n 5` printed `D:\...md:LINE` hits
- [ ] In a new Claude Code session, asking Claude to read a 300+ line `.md` whole is
      denied and the message names the qmd command
- [ ] `/next-item` (or any task) shows builder then ONE refuter on Opus in the Agent map;
      a rework shows builder then verifier, never a second refuter pair
