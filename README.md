# Claude Code orchestration kit

> **This fork (2026-09-14, loop revised 2026-09-18): Fable thinks, Opus executes; a finder
> and a judge instead of one reviewer; delegation above a threshold, not by default.**
> Upstream pins haiku/sonnet/opus and bans `fable` on subagents. This fork runs on a Max
> plan where Opus quota is not the constraint and Fable quota is. The split is **what
> thinks vs what executes**. The main session is whatever `/model` says — Fable 5.1 at
> `high` while its quota lasts, Opus 5.5 at `high` after — and every design decision (what
> changes, which pattern, which helper, which library) is made there. The `debugger` is
> `model: inherit`, so hard root-cause work follows that seat. Everything else is pinned
> `opus` (builder, refuter and verifier at `high`, researcher at `medium`) — builder,
> researcher, refuter, verifier all execute a decision already written down — and locating runs on `haiku`. **No agent hard-pins `fable`, so Fable quota
> running out can never break the loop.**
>
> The brief's CONTEXT names the pattern and points at an existing `file:line` that does it
> that way; a builder that meets an unsettled choice stops and reports instead of picking.
> Review is split in two, because recall and precision are different jobs: the **refuter**
> is the finder and drops nothing, the **verifier** is the judge and returns CONFIRMED /
> PLAUSIBLE / REFUTED with PLAUSIBLE as the default. Only the judge carries the exclusion
> list. **No review agent runs the gate** — its output is pasted into the brief — which is
> what four refuters died doing in the measured session that prompted this rework.
>
> A builder runs for every non-trivial change — over ~30 changed lines or ~2 files, any new
> logic, any security surface. Only trivial edits stay in the main session, queued for one
> batched review. Search is
> qartez, never `Grep`/`Glob`; the web is Firecrawl → Exa → Context7, never
> `WebFetch`/`WebSearch`. Install is a **merge** into `~/.claude/`, never a replace.
> `validate_kit.py` pins the repo side of all this and `verify_live.py` pins the installed
> side. Upstream: [SirRuggie/claude-code-orchestration-kit](https://github.com/SirRuggie/claude-code-orchestration-kit).

## What this is

By default, every subagent runs on the same model as your main session, inherits its
effort level, and can spawn subagents of its own. Fable spawning Fable to run a grep is
how a week of quota disappears in a day.

This kit fixes that. The main session is the orchestrator: it plans, writes briefs,
reviews, and verifies. It never edits code. Five subagents do the work. Each one has a
pinned model, a pinned effort level, and a fixed tool list, and none of them can spawn
another subagent.

A **brief** is the written task each subagent receives: what to do, what not to do, and
the exact condition that means it is done.

A **bucket** is the folder that holds everything about one task: its briefs, reports,
findings, and decisions. Its name is a **slug**: a short name with no spaces, only
lowercase letters, numbers, and hyphens, so it is safe as a folder name. Example: `bug-42`.

### Two modes

The kit ships two output styles. `orchestrator` is the full loop described above: the main
session delegates to builders and reviewers, for a Fable orchestrator or large multi-part
work. `kit-lean` is for an Opus orchestrator: the main session implements changes itself,
then reviews them with the bundled `/code-review` and `/security-review`. Switch with
`/output-style kit-lean` or `/output-style orchestrator`. Hooks, agents and `CLAUDE.md`
are shared by both. The installed default is `kit-lean` (bench 2026-09-23: same spec score as full at ~60% of its cost, better robustness than plain; see bench/README.md).

## Install

```powershell
pwsh ./install.ps1      # idempotent: run after every kit edit and on every new machine
```

Who does what: [docs/FABLE-OPUS-SPLIT.md](docs/FABLE-OPUS-SPLIT.md) is the one-page split between the Fable seat (judgment) and the Opus seats (execution), and how a task moves between them.

New machine? Follow [SETUP-NEW-MACHINE.md](SETUP-NEW-MACHINE.md) first: prerequisites, qmd, the md-guard hook, checks, and the gotchas already found.

Just using it? [docs/GUIDE.md](docs/GUIDE.md) is the one-page version: install, the two modes, `/kit-off` per project, uninstall.

It copies the agents and `/task`, writes the shared rules to
`~/.claude/rules/orchestration-kit.md` (your own `~/.claude/CLAUDE.md` is left alone, and an
old kit block in it is removed), and deep-merges
`core/settings.user.json` into `~/.claude/settings.json` (backup written when it changes).
Needs Claude Code **2.1.267+** (frontmatter `effort` under a model's default-effort hold;
`/model` switches keep the prompt cache). Then: new session → `/status` shows the settings
file loaded → `/tasks` while a subagent runs shows its model.

| File | What it is |
|---|---|
| `core/CLAUDE.md` | The rules. This is the only place that defines the brief format (six sections), the bucket, and the rule that every agent has a pinned model. |
| `core/agents/` | The six agents, one file each: Explore `haiku`, researcher `opus`, builder `opus`, refuter `opus`, verifier `opus`, debugger `inherit`. Each file pins the model, the **effort**, and the tools. |
| `core/commands/task.md` | `/task` shows every open task. `/task <sentence>` continues one or starts a new one. |
| `core/settings.user.json` | The user-settings fragment the installer merges: per-model `modelSettings` effort (fable `high`, opus `high`), `env` (`CLAUDE_CODE_SUBAGENT_MODEL=opus` for off-roster agents, `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1`), brief-folder deny rules, push/reset ask rules. |

The **Response contract** section at the top of `core/CLAUDE.md` is one person's reply
preferences. Edit it to match yours.

**Verified against the official docs on 2026-09-14** (`code.claude.com/docs/en/sub-agents`,
`model-config`, `settings`): model order = per-invocation → frontmatter →
`CLAUDE_CODE_SUBAGENT_MODEL` → main (2.1.251+) · effort levels on Fable 5.1 / Opus 5.5 =
`low medium high xhigh max`; `modelSettings`/`effortLevel` accept everything but `max` ·
frontmatter `effort` overrides the session level but **not** `CLAUDE_CODE_EFFORT_LEVEL`, so
that variable is never set here · `CLAUDE_CODE_SUBAGENT_MODEL` alone leaves the built-in
Explore/Plan agents on the main model; `_FORCE` moves them but erases every pin, so it is
never set either.

## The six agents

| Agent | Model | What it does | What it cannot do |
|---|---|---|---|
| Explore | haiku, no effort (haiku ignores it) | Finds where things are in the code, through qartez. | Cannot edit. Has no `Read`: returns file paths only, never file contents. |
| researcher | opus, `effort: medium` | Answers a question from source (qartez), library docs (Context7) or the web (Firecrawl, Exa), with citations. | Cannot edit. Has no `WebFetch`/`WebSearch`. |
| builder | opus, `effort: high` | Writes the code the brief specifies, in the pattern the brief names, and runs the tests; `qartez_impact` before every edit. | The only agent with Edit and Write. Does not choose patterns: an unsettled choice is a BLOCKER, not a decision. |
| refuter | opus, `effort: high`, `maxTurns: 40` | **The finder.** Reviews the change once, correctness and security in the same pass, and forwards every candidate it can attach a failure scenario to. | Has no Edit or Write tool. **Never runs the gate** — the gate's output is in its brief. It does not decide which candidates are real. |
| verifier | opus, `effort: high`, `maxTurns: 20` | **The judge.** Returns CONFIRMED / PLAUSIBLE / REFUTED per candidate, and FIXED / NOT FIXED per must-fix after a rework. The only agent that carries the exclusion list. | Read-only, no Bash, no shell of any kind. REFUTED needs the quoted line that makes the failure impossible; otherwise PLAUSIBLE. |
| debugger | inherit (the orchestrator's model), `effort: high` | Finds the real cause of a hard bug and proves it, with runtime tools (delve, Flutter DTD, Postgres). | Has no Edit or Write tool. It explains, it does not fix. |

The normal loop is: **gate → builder → gate → refuter finds → verifier judges → you
decide.** CONFIRMED and PLAUSIBLE items become a second builder brief, then the verifier
answers FIXED or NOT FIXED per item. A second round of must-fixes, or any NOT FIXED, stops
the loop and comes back to you. Three agents on the happy path, five at most.

**Trivial edits never enter that loop.** Under ~30 changed lines or ~2 files with no new
logic, the main session edits and queues the diff for one batched review. Everything else is
a builder on Opus: measured 2026-09-22, every main-session turn on Fable re-read ~422K cached
tokens, so ten inline turns cost more than one builder.

**None of the six can spawn a subagent.** The `Agent` tool is not in any of their
tool lists, so it does not exist for them. This is enforced, not just requested. For any
other subagent you start, set this once so it cannot spawn either. In a terminal:

```bash
export CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1
```

In the desktop app there is no terminal, so put it in `~/.claude/settings.json` instead:

```json
{ "env": { "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "1" } }
```

The extras `settings.json` sets the same value for a repo. After installing, test it once:
spawn a subagent and ask it whether it has the `Agent` tool. It should say no.

## Your first task

You do not name tasks or run a command for each step. You say what you want, and Claude
keeps the bookkeeping.

1. In your repo, type `/task fix the broken menu on the settings page`. Claude opens a
   bucket for it, names it `broken-settings-menu`, shows the scope, and waits for your go.
2. Claude writes a brief for the builder and spawns it. You do not see the brief unless you
   ask. The builder makes the change, runs the tests, and writes a report.
3. Claude spawns the refuter with the same brief. The refuter reads the code change, runs
   the named tests, and answers ACCEPT or REWORK with a list of must-fix items.
4. On REWORK, Claude writes a new brief with the must-fix list, the builder fixes it, and
   the verifier confirms each item. On ACCEPT, Claude closes the bucket and tells you in
   one line. A second REWORK is not looped; Claude brings it to you.
5. Say the next thing: "now the time display is wrong". Claude sees it is a different
   task, opens a new bucket, and starts again. Ten tasks in a day means ten buckets. You
   named none of them.

Tomorrow, type `/task` with nothing after it. Claude lists every bucket, what is open,
what is blocked on you, and the next action for each.

## Where the files go

There are two places. The rule: **your personal habits go in your home folder. Facts
about a project go in that project's repo.**

### Home folder: `~/.claude/` (only you, every project)

| File | Why here |
|---|---|
| `CLAUDE.md` | Loaded automatically in every session and into every subagent. Your rules follow you to every repo. |
| `agents/*.md` | The six agents from the table above. One file each, so each one's tool list is enforced. |
| `commands/task.md` | Defines `/task`. The dashboard for every bucket. |
| `hooks/kit-context.py` | A `Stop` hook. At 45%+ context it asks for the handoff in the bucket's `STATE.md`, then "/clear, then continue". |

These files describe how *you* like to work. They say nothing about any codebase, so they
do not belong in a repo.

### The repo: `<project>/`

| File | Why here | Commit it? |
|---|---|---|
| `CLAUDE.md` | How to build and test this code, its layout, and what is dangerous in it. Every teammate and every agent needs this. | **Yes** |
| `.claude/settings.json` | Permission rules for this repo. | **Yes** |
| `.claude/scratch/<task>/` | Working notes for one task. Nobody else needs them. | **No — add it to .gitignore** |

Simple test: if a new teammate would need the file, commit it. If it only describes how you
like your answers, keep it in your home folder.

### Desktop app or terminal?

**Same thing.** Both read the same `~/.claude/` folder, which holds `CLAUDE.md`,
`settings.json`, `plugins/`, and `sessions/`. The folder `AppData/Roaming/Claude` belongs
to the separate chat app and holds no settings. Install once and both apps use it.

## Why each agent has its own file

Three reasons:

- **The tool list is a real limit.** In an agent file, `tools:` lists the only tools that
  agent gets. A tool that is not on the list does not exist for that agent. This is why
  the refuter cannot use Edit or Write. Leave `tools:` out and the agent gets every tool.
  If all six were described in one text file, that would only be a request. In
  separate files it is enforced.
- **The file is only loaded when that agent runs.** One big file with all six agents
  would have to be read by your expensive main chat every time. That is the opposite of
  saving money.
- **The `description:` line is how Claude picks an agent.** It compares your task to each
  agent's description and chooses. No guessing.

## Two things to know about subagents

- **Subagents get your CLAUDE.md files.** Both the home one and the project one. So agent
  files can say "follow the rules" instead of repeating them. It also means **every subagent
  pays for every line of both CLAUDE.md files, every time it starts.** Keep them short.
  That is about cost, not style.
- **Subagents do not see your conversation.** They get the text you send them, the CLAUDE.md
  files, and a snapshot of `git status`. Nothing else. So the brief must contain
  everything. "As we discussed" in a brief is a mistake.

## The three rules that do the real work

1. **Every agent has a pinned model.** Without one, a subagent uses your main session's
   model, and so do any subagents it spawns. That is what burns quota, not "using
   subagents". If you spawn an agent that is not one of the six, pass a model yourself.
2. **The brief is a file. Write it before you spawn the agent. Never change it after.**
   The refuter checks the work against those exact words. If the words can change, the
   review means nothing.
3. **The refuter never reads what the builder said.** It reads the brief, the code
   change, and its own test run. Builders describe their own work as better than it is.
   The code cannot do that.

## Why CLAUDE.md is so short

Every subagent loads all of CLAUDE.md, so **every line costs money every time one
starts.** About 60% of this kit's first `CLAUDE.md` was instructions only the main chat
could use. A subagent paid for those lines and could do nothing with them. You cannot move
them somewhere else, because CLAUDE.md is the only file that loads automatically.

So the split is: **CLAUDE.md holds the rules, this README holds the reasons.** Reasons do
not change what Claude does, and nothing loads this README while Claude runs. So reasons
are free here and cost money there. This kit's `CLAUDE.md` went from 2,258 to 1,324
tokens, a 41% cut, and kept all 16 rules that matter. That is about 23k tokens saved over
25 spawns.

If you add something to `CLAUDE.md`, add the rule, not the reason.

## The bucket

Each task gets one bucket inside the repo you are working in. Claude opens it when a new
task starts and closes it when the refuter accepts. A file called `INDEX.md` next to the
buckets lists all of them with status and next action. Agents share information through
these files instead of through your chat:

```
.claude/scratch/<slug>/
  STATE.md       replaced each update — what is true NOW
  FINDINGS.md    append-only — evidence, file:line
  DECISIONS.md   append-only — what changed and WHY   ← the loop-breaker
  briefs/        orders, written before spawn, then read-only
  reports/       one per brief
```

`DECISIONS.md` is the most useful file. **Every agent reads it before changing anything.
If a change would undo a decision written there, the agent stops and reports instead.**
This ends the problem where round two undoes round one, and round three undoes round two.
Add `.claude/scratch/` to `.gitignore`.

---

## extras: install only if you need them

```bash
cp extras/project/CLAUDE.md             <repo>/CLAUDE.md            # or just run /kit-init
cp extras/project/.claude/settings.json <repo>/.claude/settings.json
cat extras/project/.gitignore-snippet  >> <repo>/.gitignore
cp -r extras/project/.claude/scratch/_TEMPLATE <repo>/.claude/scratch/_TEMPLATE
```

Start Claude Code from the repo root. The paths in `settings.json` are matched from the
folder you start in, so starting from a subfolder turns those rules off.

`/kit-init` does the first line for you and fills it in: it detects and times the fast gate,
then runs `scan_project.py --apply`, which writes the **Security surfaces**, **Layout**,
**Conventions** and **Danger list** sections from what the tree actually contains, with the
evidence on every line. Nothing in those four sections is guessed: they are filled by
detection, and a section where the scan found nothing says so and refreshes on the next
`/kit-init`.

| | |
|---|---|
| `project/CLAUDE.md` | A template for a repo's own CLAUDE.md: commands table, layout, danger list, list of past defects. |
| `project/.claude/settings.json` | Blocks Edit/Write on `briefs/**`. Asks before `push`, `reset --hard`, and removing the read-only flag. Stops subagents spawning subagents. |
| `project/.claude/scratch/_TEMPLATE/` | Longer versions of the bucket files, with STOP/LOG/DEFER classes for findings. |
| `project/.gitignore-snippet` | The two lines that keep buckets out of git. |

## Facts from the official docs

- **The `model:` line in an agent file is respected.** Order of priority: a model you pass
  when spawning → the agent file's `model:` → `CLAUDE_CODE_SUBAGENT_MODEL` →
  your main chat's model. So the six agents really are pinned. Pass a model yourself only
  for an agent that is not one of the six. This order needs Claude Code 2.1.251 or newer.
  Older versions put the environment variable first.
- **`haiku` is an official short name.** So is `fable`, and **this fork hard-pins it on
  nothing.** The `debugger` is `model: inherit`, so hard reasoning follows whichever seat the
  orchestrator is on — Fable while its quota lasts, Opus after — and Fable running out can
  never break an agent. A Fable subagent's file reads and command output die with it anyway,
  while the same work done inline by a Fable main session stays in that context for every
  later turn.
- **A tool missing from `tools:` is denied.** The list is "only these". That is why the
  refuter has no Edit or Write. A file with no `tools:` line gets all tools.
- **Subagents load every CLAUDE.md**: `~/.claude/CLAUDE.md`, the project CLAUDE.md,
  `CLAUDE.local.md`, and any company policy file. Only the built-in Explore and Plan
  agents skip this. Your main session's memory is NOT passed to subagents.
- **If two agents have the same name, the project one wins.** For skills and commands it
  is the other way round: `~/.claude/commands/` beats `.claude/commands/`. Do not use the
  same name twice.
- **`$1` means the SECOND word**, because counting starts at 0. Every command in this kit
  uses `$ARGUMENTS` and splits the words itself, so this does not affect them.
- **Subagents can spawn subagents**, three levels deep by default. The six kit agents
  cannot, because `Agent` is not in their tool lists. `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1`
  closes it for every other subagent.

## Agent file settings worth knowing

The docs list 17 settings for an agent file, not just the usual 5 (`name`, `description`,
`model`, `tools`, `color`). These matter:

| Setting | Why |
|---|---|
| `effort` | `low` to `max`. **If you leave it out, the agent inherits your session's level**, so a cheap model can still be told to think hard. Set on every agent here except `Explore`, because haiku has no effort parameter at all. |
| `disallowedTools` | A block list, for when "only these tools" is too strict. Every read-only agent here carries `Edit, Write, NotebookEdit`. It blocks the edit tools only: an agent that also holds `Bash` can still write through a shell, so its own file forbids that too. |
| `skills` | Preloads a skill onto one agent. `verifier` gets `review-precision` — the exclusion list belongs to the judge and must never reach the finder. The file does sit in `~/.claude/skills/`, because `skills:` resolves installed skills by name and the installer puts it there; what keeps it off every other agent is that **no agent holds the `Skill` tool**, so only this frontmatter preload can reach it. Its description costs ~46 tokens in the session listing. Do not add more global skills casually: listings are budgeted at 1% of the context window and on overflow Claude Code drops the least-invoked descriptions. |
| `omitClaudeMd` | Launches the agent without the CLAUDE.md hierarchy. Set on `Explore`. Pair it with the tool rules in `initialPrompt`, which survives the flag — an agent that loses "code search is qartez" burns more than the file saved. |
| `maxTurns` | Set on `refuter` (40) and `verifier` (20). **Measured not to bind**: a 40-turn refuter made 45 tool calls. Treat it as a budget hint, read the agent's coverage line for the truth. |
| `isolation: worktree` | Gives the agent its own git worktree. It starts from your default branch unless `worktree.baseRef: "head"`, and holds tracked files only — no `node_modules`, no `.venv`, no `.env`. Use it when two agents must write at the same time; keep read-only agents out, because a different working directory forfeits the cached prefix. |
| `permissionMode` | Permission behavior for that agent only. **Ignored** when the main session runs in `acceptEdits` or `auto`. |
| `hooks`, `memory` | Exist, not used here. |

## The one-line quota fix

If you only want one thing from this kit, use this:

```bash
export CLAUDE_CODE_SUBAGENT_MODEL=sonnet
export CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1
```

Every subagent becomes Sonnet, and **every agent file's `model:` is ignored.** You also
cannot pass a model when spawning. This turns off the six-agent setup completely. Use
it when quota matters more than choosing the right agent for each job.
