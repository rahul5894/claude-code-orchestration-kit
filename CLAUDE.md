# claude-code-orchestration-kit — working rules

Repo-specific rules only. The orchestration loop, model routing, agent roster, brief format
and reporting rules live in `~/.claude/CLAUDE.md` and the `orchestrator` output style.

**This repo IS the kit.** Editing `core/` changes what every other project loads on its next
`install.ps1`, so a mistake here ships everywhere. That is the only thing that makes this
repo unusual.

---

## Commands — the gate agents run, and the ones they must not

| Purpose | Command | Measured |
|---|---|---|
| **FAST GATE — agents run this** | `python validate_kit.py` | **0.1 s** |
| Live-state check (**I run this**) | `python verify_live.py` | **8.6 s** — installs twice |
| Install into `~/.claude` | `pwsh -File install.ps1` | 1.2 s |
| Scoreboard from transcripts | `python agent_stats.py --since <YYYY-MM-DD>` | ~1 s |

`validate_kit.py` reads this repository only and is the diff-scoped gate: ~450 checks, no test
suite, no network. `verify_live.py` also reads `~/.claude`, runs `install.ps1` twice and
shells out to `claude plugin validate` and `qartez doctor` — which is why it is not the gate.

### Agents never run these

- `python verify_live.py` — it **writes to `~/.claude`** through `install.ps1`. Only I run it.
- `pwsh -File install.ps1` — same reason.
- `claude update`, `claude plugin update`, `claude mcp add` — they change the machine.
- **Never print an MCP config.** `claude mcp get <server>` and a raw read of `.mcp.json` or
  `~/.claude.json` put live API keys into the transcript. Measured 2026-09-18: one such call
  leaked a Firecrawl key and forced a rotation. Read key *names* only.

## Security surfaces in THIS repo

There is no server and no database, so the general list mostly does not apply. What does:

- `install.ps1` — writes into `~/.claude`, merges `settings.json`, registers a hook. A defect
  here corrupts the user's own config. Every change gets the four-state probe in
  `verify_live.py` section C3 (nothing installed / empty CLAUDE.md / empty settings / corrupt
  settings).
- `core/settings.user.json` — `env` keys here silently defeat every model and tool pin.
- `core/agents/*.md` frontmatter — `tools` and `disallowedTools` ARE the security boundary for
  read-only agents; nothing else stops a write.
- `.mcp.json`, `.mcp.template.json` — the live one is gitignored and holds real keys. Only the
  template is committed, and every value in it is a `${VAR}` placeholder.

## Code navigation

qartez indexes **only the Python files** here — `validate_kit.py`, `verify_live.py`,
`agent_stats.py`, `core/hooks/*.py`. Everything this repo is actually made of — the agent
markdown, `install.ps1`, the docs — is **not in the index**. So `OUT OF INDEX` is the normal
answer in this repo, not a surprise, and `Bash grep ... | cut -c1-300` is the working tool for
anything that is not a Python symbol.

## Danger list

- **Never edit `core/CLAUDE.md` past its byte budget without reading the reason** in
  `validate_kit.py` section 5. Every subagent of every project re-pays that file on every
  spawn.
- **A patch script written with a non-raw Python string turns `\b` into a backspace byte.**
  That shipped: a regex read as a word boundary searched for a literal control character,
  matched nothing, and the check built on it passed for days. Section 0 of the gate now
  rejects any literal control character in source. Use `Edit`, not a `str.replace` script,
  for anything containing a regex.
- **Frontmatter is YAML.** An unquoted `": "` inside `initialPrompt` makes the whole agent
  fail to load, silently — `claude plugin validate` is the only thing that says so, and
  section 0b of the gate now parses it with real PyYAML.
- Windows console is cp1252: read and write subprocess output as UTF-8 explicitly, or a
  caught failure prints as a crash and an empty stdout reads as "the tool said nothing".

## Past defects worth not repeating

| What escaped | Why the gate missed it |
|---|---|
| A check that could never fail | Its pattern was unmatchable; nothing proved the pattern itself |
| Two agents that would not load | The checker parsed frontmatter with a line-splitter, not YAML |
| `turns` inflated 2.3-3.9x | One JSONL line per content block was counted as one turn |
| A reviewer judging a stub | qartez dedups per server, and every agent shares that process |
| A brief that called a 341-line file short | Nobody had counted; section 9b now prints the census |
