# Rejected, and why

Nothing in this folder is installed. It is here so the decision is recorded instead of
argued again. Full evidence is in `docs/RESEARCH-2026-09-18.md`.

## `behavioral-guardrails.md`

It **is** the Karpathy guidelines file: same description line ("Behavioral guidelines to
reduce common LLM coding mistakes"), same four sections in the same order — Think Before
Coding, Simplicity First, Surgical Changes, Goal-Driven Execution — plus a fifth section
that was added locally.

That fifth section is repo-specific (Flutter + Go, a named threat model, an instant-load
contract) and was moved to `extras/prideconnect-section.md`. The first four sections are
not installed, for the reasons under "Karpathy guidelines" below.

## Karpathy guidelines (`multica-ai/andrej-karpathy-skills`)

Not installed. One skill, 2,518 bytes, in a 20 KB repo. Not by Andrej Karpathy — owner is
the `multica-ai` organization, author `forrestchang`, and the README's top line advertises
that author's own product. 213,642 stars on 28 commits; last push 2026-04-20; issues
disabled; 101 open PRs; `"license": null` despite README and frontmatter claiming MIT.

The source is one Karpathy post whose own text says these failures persisted *despite*
"a few simple attempts to fix it via instructions in CLAUDE.md" — the primary source
undercuts the remedy.

Against Anthropic's skill-authoring test ("only add context Claude doesn't already have")
it fails: no repo-specific facts, no commands, no scripts, no security content. Two of its
rules actively fight this kit:

- *"If something is unclear, stop. Name what's confusing. Ask."* — unexecutable in a
  subagent, which has no user to ask. A builder burns a turn and returns a non-answer.
- *"Every changed line should trace directly to the user's request."* — argues a builder out
  of the root-cause fix, because a guard in the shared function touches code the ticket
  never named.

Worth harvesting, if not already present in ponytail's wording: "match existing style even
if you'd do it differently", and "unrelated dead code: mention it, don't delete it". Its
`EXAMPLES.md` (14.8 KB of before/after diffs) is the only dense content in the repo, does
not ship with the plugin, and would be useful only as review fixtures.

## Other things considered and dropped

| considered | why not |
|---|---|
| `advisorModel: fable` roster-wide | the advisor's transcript read is never cached, and on subscription plans a Fable advisor bills to usage credits outside the plan |
| a brief-review agent before the builder | one anonymous unpublished eval as its only evidence, and it adds a serial step |
| a `Stop` hook blocking session exit until review | turns every abandoned experiment into a forced review |
| an `async` gate hook on `Edit\|Write` | async hooks cannot gate, and the matcher fires once per edit |
| a forked reviewer to skip the cold diff read | a fork inherits the main session's model and destroys the independence the review exists for |
| per-agent MCP **tool** allowlists as a token play | tool definitions are already deferred; only server instructions prose is not |
| agent teams | experimental, off by default, ~7x tokens, and a named subagent silently becomes a teammate |
| BMAD / spec-kit / claude-flow / SuperClaude | same feature: BMAD Full 6 days and $200 against 1.2 days and $75 for the light flows |
