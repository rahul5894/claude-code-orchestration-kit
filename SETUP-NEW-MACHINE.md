# New machine setup: orchestration kit, qmd, md-guard

This page is for you, on a fresh Windows machine. Follow it top to bottom.
It takes about 20 minutes. Every step has a check. Do not skip a check.

Which model runs which agent, and why, is not repeated here: see `docs/FABLE-OPUS-SPLIT.md`.

Last verified: 2026-09-23 on Windows 11, Claude Code 2.1.280 (2.1.280+ required: older builds reject `claude-opus-5-5` and map `opus` to Opus 5), qmd 2.8.3, Python 3.12.10.

**`claude --version` is not the version your session is running.** Measured 2026-09-18: the
CLI binary at `~/.local/bin/claude.exe` reported **2.1.270** while the running VS Code
session's own transcripts recorded **2.1.274** — the editor manages its build separately.
Read the truth from a transcript, not from the CLI:

```
python -c "import json;print(json.loads(open(r'<transcript>.jsonl').readline())['version'])"
```

`json.loads(...readline())`, not `json.load(...)`: a `.jsonl` is one JSON object **per line**,
so `json.load` on the whole file raises `JSONDecodeError: Extra data: line 2 column 1` and
sends you back to the CLI number this section exists to distrust.

or the first line of any `~/.claude/projects/*/*/subagents/agent-*.jsonl`. Trusting the CLI
number sent one upgrade down a wrong diagnosis here.

**Keep Claude Code current anyway.** `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` turns
auto-update off as a side effect, so the CLI binary sat unchanged from 2026-08-27. Two
releases in that gap matter to this kit: **2.1.271 added `omitClaudeMd`**, and **2.1.274
fixed "sub-agents and background agents being reported as failed, with their result never
delivered"** — the exact symptom of a fan-out where half the agents come back empty,
reported upstream on this same OS with a trigger around five concurrent agents. Run
`claude update` by hand, or unset that env var to let it update itself (which also
re-enables telemetry and feature flags).

## 1. Prerequisites

Install these first. Open a new terminal after each install so PATH updates.

| Tool | Why | Check |
|---|---|---|
| Claude Code (VS Code extension or CLI) | the host | `claude --version` |
| PowerShell 7 | runs `install.ps1` | `pwsh --version` |
| Git | clones the kit | `git --version` |
| Node 22 or newer | optional: npm-based MCP servers | `node --version` |
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
agents:        builder, debugger, Explore, refuter, researcher, verifier
commands: task
rules/orchestration-kit.md: written  (or "unchanged" on a re-run)
settings.json: merged (backup written)
md-guard: registered in settings.json
kit-session-start: registered in settings.json
kit-subagent-report: registered in settings.json
kit-subagent-start: registered in settings.json
kit-context: registered in settings.json
md-guard self-check: 121/121 passed
kit-session-start self-check: 25/25 passed
kit-subagent-report self-check: 12/12 passed
kit-subagent-start self-check: 18/18 passed
kit-context self-check: 21/21 passed
kit_off self-check: 11/11 passed
kit-switch self-check: 12/12 passed
scan-project self-check: 38/38 passed
done. ...
```

What the installer does. It copies `core/agents/*.md` and `core/commands/*.md` into
`~/.claude/`. It writes the shared rules to `~/.claude/rules/orchestration-kit.md`, a file of
their own so `/kit-off` can drop them from one project, and leaves `~/.claude/CLAUDE.md` to you
(an old kit block between marker comments there is removed, with a backup). It deep-merges `core/settings.user.json` into
`~/.claude/settings.json` and writes a backup first. It copies `core/hooks/*.py` into
`~/.claude/hooks/` and registers the md-guard hook once. It is safe to run again after
every kit change. A second run prints `unchanged` and `already registered`.

Two modes. The installer copies both output styles into `~/.claude/output-styles/`:
`orchestrator` (the full delegate-and-review loop, for a Fable orchestrator or large
multi-part work) and `kit-lean` (an Opus main session that implements itself and reviews
with the native `/code-review` and `/security-review`). `settings.json` gets no output style:
Claude Code's own default stays (both kit modes are opt-in). Switch with `/output-style kit-lean` or
`/output-style orchestrator`; hooks and agents are the same in both.

Checks:

1. `python verify_live.py`. It must print `ALL CLEAR` and exit 0. This reads `~/.claude`,
   not just the repo, so it is the check that catches a stale install: every installed
   file byte-identical to the repo, every effort pin and `env` key live in
   `settings.json`, the roster table in the output style matching the agent files, and no
   agent holding a tool the qartez guard denies or carrying an order it has no tool for.
   Every one of its sections is break-tested. Run it after every kit change, not only on
   a new machine. `python validate_kit.py` is the faster repo-only half and runs inside it.
2. `python agent_stats.py` after you have run some agents. It reads the transcripts Claude
   Code already writes and prints turns, tool calls, orientation turns, guard denials,
   suite runs inside agents, cold-cache starts and wall-clock, per agent. This is how you
   answer "did the kit help" with numbers instead of an opinion. `--project <name>` reads
   another repo, `--since YYYY-MM-DD` limits the window, `--tools` adds the tool histogram.
3. `~/.claude/settings.json` has no `CLAUDE_CODE_EFFORT_LEVEL` and no
   `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` under `env`. Either one silently overrides every
   agent file. The installer warns if it finds them.
3. Start a new Claude Code session. `/status` shows the settings file loaded.

## 2b. MCP servers

**The four servers the agents actually need live at USER scope, not per project.** `qartez`
backs every agent's search; `firecrawl`, `exa` and `context7` are the researcher's only web
tools, because it has no `WebFetch`/`WebSearch` on purpose. A project-scoped config would
leave the researcher mute in every repo you forgot to copy it into, so put them in
`~/.claude.json` once:

```
claude mcp add --scope user --transport http context7 https://mcp.context7.com/mcp --header "CONTEXT7_API_KEY: $env:CONTEXT7_API_KEY"
claude mcp add --scope user --transport http exa "https://mcp.exa.ai/mcp?tools=web_search_exa,web_fetch_exa" --header "x-api-key: $env:EXA_API_KEY"
claude mcp add --scope user firecrawl -e FIRECRAWL_API_KEY=$env:FIRECRAWL_API_KEY -- npx -y firecrawl-mcp
```

Two syntax traps, both hit here on 2026-09-18: the **server name comes before `-e`** (it is
variadic, so it swallows the name), and `--scope user` writes `~/.claude.json`, which then
holds live keys — never commit or sync that file. Check with
`python -c "import json,os;print(sorted(json.load(open(os.path.expanduser('~/.claude.json')))['mcpServers']))"`.

**Set `QARTEZ_READ_DEDUP=0` in the qartez server's `env`.** qartez caches served source per
*server process*, and **every agent of a session shares that process**, so a second read of a
symbol returns `// (served earlier by this server: ...; not in YOUR context? fresh=true)`
instead of the body. Reproduced on 2026-09-18: the orchestrator read a symbol, then a fresh
verifier asked for the same one and got the stub — its own words, *"any statement I made
about that function's correctness would have been invention rather than reading."* The saving
is illusory here because subagents share no context, and the failure is silent. `fresh=true`
per call is the fallback; the env var is the control, because it cannot be forgotten.

**After any qartez upgrade, restart Claude Code.** `verify_live.py` section C4 compares the
start time of every running `qartez.exe` with the write time of the binary on disk and fails
when one is older: until the restart, every agent is served the *previous* qartez while
`qartez --version` says otherwise. The doctor's own `restart_required_after_upgrade` is not
used — it is a hardcoded `true` in 0.27.0, so it can never say "no".

`.mcp.template.json` is the *project* MCP config with every credential replaced by an
environment variable, for the extra servers a single repo needs (Atlassian, SSH, mssql,
scrapling, chrome-devtools). The live `.mcp.json` is gitignored on purpose: it carries API
keys, and a key that reaches git history is leaked for good.

On a new machine:

1. Set these in the user environment (System Properties > Environment Variables, or
   `setx`): `CONTEXT7_API_KEY`, `FIRECRAWL_API_KEY`, `EXA_API_KEY`, `EXPRESSVPN_TOKEN`,
   `ATLASSIAN_API_TOKEN`, `DANTE_SSH_KEY`.
2. Run the three `claude mcp add --scope user` commands above.
3. Only if this repo needs the extras: `Copy-Item .mcp.template.json .mcp.json`
4. Start Claude Code from the repo root; `/mcp` lists what connected.

Two entries are machine-specific and will not resolve until their paths exist: `mssql`
(`D:\sql2019-setup\mssql-environments.json`) and `emclient`
(`d:/Projects/my-scraper-project/tools/emclient_mcp.py`). Remove them from `.mcp.json` on a
machine that does not have those, or the servers show as failed to connect.

## 2c. A new project: open it and run `/kit-init`

Everything in the kit is global — agents, output style, hooks, the shared rules, qartez and
the researcher's web servers at user scope. **The only per-project thing is a `CLAUDE.md`
with a measured FAST GATE row**, and the kit now creates that itself:

1. Open the repo in Claude Code. A global `SessionStart` hook (`kit-session-start.py`) sees
   there is no FAST GATE row and injects one line telling the orchestrator to run `/kit-init`
   before delegating anything. It also lists the open task buckets for the model and, on
   startup and `/clear`, shows you "Open task(s): ... - type /continue to resume". It writes
   nothing. A `SubagentStart` hook
   (`kit-subagent-start.py`) injects the `DECISIONS.md` of every OPEN or BLOCKED bucket in
   `.claude/scratch/INDEX.md` into each spawned agent, so a settled decision binds an agent
   that never saw the conversation.
2. Run `/kit-init`. It detects the gate from `package.json` / `pyproject` / `Makefile` /
   `go.mod` / `pubspec`, **runs it once and times it**, refuses anything over 60 s or
   containing a test runner, writes `CLAUDE.md` from `~/.claude/kit/project-template.md`
   with the real number in, and finishes with `python ~/.claude/kit/audit_project.py .`.
3. The four detected sections are filled by detection, not by hand. `/kit-init` also runs
   `~/.claude/kit/scan_project.py --apply`,
   which fills **Security surfaces in THIS repo**, **Layout**, **Conventions** and **Danger
   list** from what the tree actually contains — one regex per category, counted per file,
   the evidence on every line. It never guesses: a section where nothing was detected says
   so and refreshes on the next `/kit-init`, and a section you filled in yourself is reported
   `kept` and left alone. The detected security list is a floor, not a ceiling.


**Never add to a project what the kit already provides globally.** `audit_project.py`
flags it: a `## Qartez MCP` section, a restated web-tool order,
a `.mcp.json` entry for a server already at user scope, and a
`.claude/skills/<name>` that shadows a global skill of the same name (a June copy of
`firecrawl` was silently beating the August global one). Each is re-paid by every subagent
on every spawn and drifts from the global text.

**A skill two repos share is a global skill.** `prompt-master`, `session-handoff` and
`resume-handoff` were hand-copied into both repos and one pair had already diverged; they
now live in `~/.claude/skills/` once. Tool cheat-sheets about qartez/Firecrawl/Exa belong to
those tools' own global skills and docs, never in a repo's `docs/`. What a project keeps in
`.claude/skills/` is only what is true of that codebase alone (PrideConnect: `phone-test`,
`crypto-media-audit`, `mcp-tools` for its Maestro/postgres servers; the scraper:
`county-onboarding`).

## 3. qmd: dropped (2026-09-23)

The kit no longer uses qmd. Over 14 days of transcripts it was called 10 times against about
250 md-guard denials: after a denial the model went to `grep -n ... | cut -c1-300` and a
`Read` window anyway. md-guard now suggests exactly that. A qmd install you already have does
no harm; `npm uninstall -g @tobilu/qmd` removes it.

## 4. md-guard hook

`~/.claude/hooks/md-guard.py` is a PreToolUse hook on `Read`, `Bash` and `PowerShell`.
It makes "read big docs in windows" enforced instead of remembered.

It denies:

- `Read` of a `.md` file with more than 300 lines, unless `limit` is 300 or less.
- A shell read (`cat`, `sed`, `grep`, `rg`, `head`, `tail`, `awk`, `Get-Content`,
  `Select-String`) of a `.md` file with more than 300 lines, or of a path it cannot
  find, when the command has no column cap.

- Any `Bash` / `PowerShell` command with a named write shape (redirection, `sed -i`, `tee`,
  rm/mv/cp, tree-changing `git`, a write-mode `open(`, a package install) when the payload's
  `agent_type` is `refuter` or `debugger` — the two read-only agents that hold a shell.

It allows: small files, writes from anyone else (`>`, `>>`, heredocs, `sed -i`, `tee`), counts
(`wc`, `grep -c`), capped output (`| cut -c1-300`, PowerShell `.Substring(`), and `git`
commands. Each `&&` / `;` segment of a command is
judged on its own, so `rm big.md; git status | head` passes.

The deny message tells Claude the capped `grep -n` + `Read` window to use instead.

Check: `python ~/.claude/hooks/md-guard_test.py` prints `121/121 passed`. The test
builds its own fixtures in a temp folder, so it runs on any machine. The installer runs
it for you.

`~/.claude/hooks/kit-subagent-start.py` is the other half of the same idea: a `SubagentStart`
hook that injects the `DECISIONS.md` of every OPEN or BLOCKED bucket in `.claude/scratch/INDEX.md` into
each spawned builder, refuter, verifier, debugger and researcher, capped at 6000 characters.
Check: `python ~/.claude/hooks/kit-subagent-start_test.py` prints `18/18 passed`.

`~/.claude/hooks/kit-context.py` is a `Stop` hook. At 45%+ context, the first stop in each
10-point band asks the model to write the handoff into the bucket's `STATE.md` and tell you
"/clear, then /continue"; later stops show "Context N% full". It stays silent while a
background agent runs and never blocks a headless `claude -p` run.
Check: `python ~/.claude/hooks/kit-context_test.py` prints `21/21 passed`.

Known gaps, on purpose:

- `grep -rn X some/dir/` with no `.md` in the command is not gated.
- Any crash inside the hook allows the call. It is a token guard, not a security
  boundary.
- A partial `Read` (with `limit`) still counts as "read" for a later `Edit`, so agents
  can append to big docs without reading them whole. Verified 2026-09-16.

## Plugins

A plugin with a `SessionStart`, `UserPromptSubmit` or `Stop` hook talks in every session you
open, and Claude Code cannot switch off one plugin's hooks: `hooks.md` offers `disableAllHooks`
and nothing narrower. So the choice is per plugin, whole, and `core/plugins.json` records it as
two maps of plugin id to reason:

- `disable` — `install.ps1` writes `enabledPlugins[<id>] = false` into your `settings.json`
  for every id in this map that your settings already mention.
- `allow` — reviewed and kept. The installer ignores it; it only keeps C6 quiet.

`python verify_live.py` section C6 reads the manifest of every plugin enabled in the user's
`settings.json` or `settings.local.json`, handles inline, path, list and side-file hook
declarations, and fails on a `SessionStart`, `UserPromptSubmit` or `Stop` hook that policy does
not name; a project-level enable of a disabled plugin is reported by C5. When you install one:

1. Run `python verify_live.py`. C6 names it if it injects into every session.
2. Add its id to `allow` or `disable` in `core/plugins.json` with a reason, then `pwsh
   install.ps1`.

`simple-english@simple-english` is in `disable`: its SessionStart hook injects ~700 tokens of
reply rules and its Stop hook nags "five sentences or fewer", both against the orchestrator's
report format. The skill is worth keeping, so the kit ships its own copy at
`core/skills/simple-english/` (MIT, AminBlg/SimpleEnglish 2.0.2) with
`disable-model-invocation: true`: it runs only when you type `/simple-english`.

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
  This is why the hook demands a column cap.
- The hook's first version had four false positives that would have broken daily
  work: heredoc writes, `cat >>` appends, `sed -i` edits, and a `head` in an unrelated
  command segment. It also missed `bash -c` and the PowerShell tool. All six are now
  test cases.
- Effort decision: builder, researcher, refuter and verifier run at `high`. The brief
  already names the pattern, so the builder does not need extra thinking. Reviewing
  does. Fable (main session) decides, Opus executes. Opus tokens are not the
  constraint. Fable context size and wall-clock are.
- Review loop, revised 2026-09-18 after measuring one 310-minute session (63 agents,
  1,493 model turns). Two things changed. **The refuter no longer runs the gate**: the v1
  rule "run the fast gate as your FIRST step" made every review agent run the project's
  full test suite, which is what killed four of five refuters in that session and cost
  92 minutes of the 528 agent-minutes. The gate's verbatim output now goes in the brief.
  **And review is split into recall and precision**: the refuter finds and drops nothing,
  the verifier judges CONFIRMED / PLAUSIBLE / REFUTED and is the only holder of the
  exclusion list. The binary ACCEPT/REWORK had no PLAUSIBLE state, so an uncertain-but-real
  bug died at the refuter with no record.
- Delegation threshold: raised to 400/8 on 2026-09-18 for wall-clock, then lowered on
  2026-09-22 — a builder runs for everything over ~30 changed lines or ~2 files, any new
  logic, or a security surface at any size. The old threshold was 2 files and 40
  lines, roughly 10x too strict against the 200-400 LOC window where peer review finds
  70-90% of defects. Below the threshold the main session does the work and notes it under
  `## Unreviewed since <sha>` in the bucket's `STATE.md`; one batched refuter pass reviews
  the accumulated diff at commit, at the threshold, or with the next builder change. A
  security-surface change is never batched. Revised 2026-09-22: the inline threshold is ~30
  changed lines / ~2 files with no new logic; the 400/8 numbers now trigger only the batched
  review. Reason in docs/FABLE-OPUS-SPLIT.md.
- Earlier live test on 2026-09-16: the
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
- The fast gate runs inside the builder twice — on the untouched tree as a baseline, and
  again as its last step — and **inside no review agent at all**; the orchestrator pastes its
  verbatim output into the brief instead. Device drives, E2E and the full suite run once,
  after the review, never before it.
- One folder per task: `.claude/scratch/<slug>/` holds briefs, research, reports. The
  kit used to deny writes under `briefs/`, which forced a second folder per task under
  `.planning/quick/`; that deny rule was removed 2026-09-16 (a brief is still never
  edited after spawn — a rule, not a permission). `_closed/` stays denied.
- Permission deny rules must use `Edit(path)`, never `Write(path)`. Claude Code only
  matches file checks against `Edit` rules, and `Edit` rules cover every file-editing
  tool. The kit shipped `Write(...)` entries that did nothing and printed a warning on
  every headless run. Removed 2026-09-16 from the kit and from `~/.claude/settings.json`.
- `maxTurns` counts assistant turns, not tool calls: the verifier checked 15 items in
  30 seconds inside an 8-turn cap by batching reads (measured 2026-09-16). It is now 20.
  **Do not rely on the cap binding** — measured 2026-09-18, a `maxTurns: 40` refuter made
  45 tool calls and a `maxTurns: 8` verifier made 22, so read the agent's own coverage
  line instead. A capped agent still returns what it had, marked partial; **resume it with
  `SendMessage` rather than re-spawning cold**, because a resumed run keeps its history and
  reads its own warm cache. A diff over ~15 files or ~800 changed lines gets two refuters partitioned
  by file and staggered ~5 seconds apart, since a review's output cap scales with effort
  and not with diff size.
- Run an agent headless to test it without restarting the session:
  `claude -p --agent verifier --output-format text < prompt.txt`. Do not pass
  `--allowedTools`: it overrides the agent's own pinned tool list, which is the thing you
  are testing. The interactive `Agent` tool only lists agent files that existed when the
  session started.
- `omitClaudeMd: true` in agent frontmatter launches a subagent without the user, project
  and local `CLAUDE.md` files. It is set on `Explore`, which needs locations and nothing
  else. Added in Claude Code **2.1.271**. **Verified working on 2.1.276** (2026-09-18): five
  `Explore` agents were asked whether their context held the shared orchestration rules and
  all five answered NO, while still locating their symbol correctly in two tool calls. That
  saves roughly **2,460 tokens per `Explore` spawn** — the shared block plus the user
  preamble. No before-measurement exists, so *when* it started working here is UNVERIFIED;
  the session was already on 2.1.274, so it was most likely never inert at all.
  The flag only pays off because `Explore` carries its tool rules in `initialPrompt`, which
  survives it. **Never set `omitClaudeMd` on an agent without moving its tool rules there
  first**: an agent that loses "code search is qartez" falls back to guard-denied tools and
  burns more than the file saved.

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `md-guard: no Python 3.12+ on PATH` | Python missing or old | install 3.12, open a new terminal, re-run `install.ps1` |
| Hook never fires | settings loaded before the change | start a new Claude Code session |
| Hook fires on a file you must read | it has more than 300 lines | `grep -n "<anchor>" <file> \| cut -c1-300`, then `Read` with `offset` + `limit` |
| Two md-guard entries in settings.json | edited by hand | delete one; the installer only ever adds one |
| Agents ignore their `effort` | `CLAUDE_CODE_EFFORT_LEVEL` set in `env` | remove it from `settings.json` |

## 7. Final checklist

- [ ] `pwsh install.ps1` printed `md-guard self-check: 121/121 passed`
- [ ] the same run printed `kit-session-start self-check: 25/25 passed`
- [ ] the same run printed `kit-subagent-report self-check: 12/12 passed`
- [ ] the same run printed `kit-subagent-start self-check: 18/18 passed`
- [ ] the same run printed `kit-context self-check: 21/21 passed`
- [ ] the same run printed `scan-project self-check: 38/38 passed`
- [ ] `verify_live.py` C6 lists no unreviewed plugin
- [ ] In a new Claude Code session, asking Claude to read a 300+ line `.md` whole is
      denied and the message names the capped `grep -n` + `Read` window
- [ ] `/next-item` (or any task) shows builder then ONE refuter on Opus in the Agent map;
      a rework shows builder then verifier, never a second refuter pair
