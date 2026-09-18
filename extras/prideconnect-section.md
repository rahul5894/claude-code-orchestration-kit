# PrideConnect-only rules — paste into that repo's own `CLAUDE.md`

These four bullets were the fifth section of `.claude/behavioral-guardrails.md`. They are
the only part of that file that was not a copy of the Karpathy guidelines, and they are
**repo-specific**: a Flutter + Go stack, a named threat model, and a latency contract. In a
generic kit they would be wrong in every other repository, which is why they move here.

Paste them under a heading in PrideConnect's `CLAUDE.md`, not in `~/.claude/CLAUDE.md`.

---

## Definition of done — additions for this repo

- **Would a senior Flutter + Go engineer approve this, line for line?** If they would flag
  it as clever-but-unclear, over-engineered, or "why not reuse X" — fix it first. Fewer,
  clearer lines beat more lines. No spaghetti, no workarounds, no "temporary" hacks.
- **Is this the current recommended way for the stack we use?** Not "a way that works" —
  the current best way. If you are not certain it is current, you do not know yet: research
  with Firecrawl, Exa and Context7, never `WebSearch`/`WebFetch`, and cite what you found
  for the INSTALLED version.
- **Is it DRY against what already exists?** Grep before writing. If the same logic lives
  elsewhere, even written differently, reuse or extract ONE source. 3+ similar sites =
  extract; one site = do not abstract.
- **Instant-load, never network-blocking.** Any user-facing surface renders from local or
  cached state synchronously, then revalidates in the background. Never gate UI on a network
  round-trip; bound every retry and replay loop. This must hold from one user to millions,
  with zero security compromise — the LGBTQ+ threat model and the pre-deploy gate never bend
  for delivery speed.
