# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

## 5. Verify Like a Senior Reviewer — the Definition of Done

**Every piece of code is read twice: once to write it, once to defend it.** Before calling any change done, answer these — out loud, against the actual diff:

- **Would a senior Flutter + Go engineer at Google approve this, line for line?** If they'd flag it as clever-but-unclear, over-engineered, or "why not reuse X" — fix it first. Fewer, clearer lines beat more lines. No spaghetti, no workarounds, no "temporary" hacks — this is a well-maintained codebase, not a scratchpad.
- **Is this the 2026-recommended way for the stack we use?** Not "a way that works" — the *current best* way. If you're not certain it's current, you don't know yet: research with Firecrawl + Exa + Context7 (never guess from training data, never `WebSearch`/`WebFetch`) and cite what you found.
- **Is it DRY against what already exists?** Grep BEFORE writing. If the same logic lives elsewhere — even written differently — reuse or extract ONE source; never add a second spelling of the same thing. 3+ similar sites = extract; pre-mature abstraction for one site = don't.
- **Instant-load, never network-blocking.** Any user-facing surface renders from local/cache state synchronously, then revalidates in the background (SWR). Never gate UI on a network round-trip; bound every retry/replay loop. This must hold from one user to millions — Telegram/WhatsApp-grade, with zero security compromise (the LGBTQ+ threat model and the pre-deploy gate never bend for speed).

If any answer is "not yet," it isn't done. This gate is mandatory for **all** new code, however small.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
