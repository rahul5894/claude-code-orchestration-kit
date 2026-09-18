---
name: review-precision
description: The exclusion list, confidence floor and drop rules a reviewer applies when judging candidate findings. Use when deciding which review candidates are real, never when looking for them.
---

# Review precision

**This list is for the judging stage only.** Never give it to a finder. A finder that
carries an exclusion list drops half-believed candidates before anything can judge them,
and that is the main way real defects escape a review.

Adapted from Anthropic's `/security-review` prompt, which gets its precision from a
separate filtering pass rather than from telling one agent to be careful. **Adapted, not
copied verbatim** — one rule is deliberately inverted (see "Local override"), and the
wording is ours.

## The bar

- A candidate is **CONFIRMED** only when you can point at the line and the described
  failure follows from the code as written.
- **REFUTED** requires the quote that makes the failure impossible: the contradicting line,
  the type or constant that forbids the input, or a guard present in this diff.
- Everything else is **PLAUSIBLE**. That is the default. "Looks fine", "the caller probably
  checks", "unlikely in practice" are not refutations.
- Report your confidence for CONFIRMED items. Below roughly 80% confidence a finding is
  PLAUSIBLE, not CONFIRMED — but it still goes forward.

## Scope — three gates before any exclusion applies

Every exclusion below is **about security noise**. Before you mark anything EXCLUDED, all
three of these must hold:

1. **The candidate is a security candidate.** A correctness, accuracy, contradiction,
   dead-code, broken-reference or "this document claims something the code does not do"
   candidate is **never EXCLUDED**, whatever file it lives in. Judge it CONFIRMED /
   PLAUSIBLE / REFUTED on the code or the text itself.
2. **The exclusion's own words fit.** Not its keyword — its meaning.
3. **The local override below does not claim it.**

The most expensive mistake this list can make is excluding a real finding because its file
extension or one of its words matched. When in doubt, PLAUSIBLE.

## Local override — this wins over every exclusion

Anthropic's list excludes client-side authorization and authentication gaps on the grounds
that the backend is responsible for validating everything. **We invert that rule.** A limit,
quota, gate or entitlement the client decides instead of the server is **never EXCLUDED**
here — not by rule 1, not by rule 2, not by the pre-filter. If a modified client could
change state to its own benefit, that is CONFIRMED. This override beats any keyword match:
a client-decidable quota finding survives even though it contains the words "limit" and
"rate".

## Exclusions — security candidates only; mark EXCLUDED and cite the number

1. **Denial of service and resource exhaustion.** Including algorithmic complexity,
   unbounded allocation from trusted input, and missing timeouts, unless the brief names
   availability as in scope.
2. **Rate limiting.** Its absence is a product decision, not a defect.
3. **Secrets at rest on the developer's own disk.** A secret committed to the repository or
   printed to a log is NOT excluded — that is CONFIRMED.
4. **Memory safety** in a memory-safe language. Only applies to `.c`, `.cc`, `.cpp`, `.h`,
   `.hpp` and unsafe blocks.
5. **Cross-site scripting in a framework that escapes by default** (React, Vue, Angular,
   Svelte), unless the diff uses an explicit escape hatch such as
   `dangerouslySetInnerHTML`, `v-html`, `bypassSecurityTrust*` or `{@html}`.
6. **Server-side request forgery where only the path is attacker-controlled** and the host
   is a fixed constant.
7. **Regular-expression denial of service** and regex injection.
8. **A security finding whose only site is a markdown, text or documentation file** — an
   injection or XSS claim about prose, for example. This rule does **not** touch a finding
   about what the document *says*: an overstated claim, a wrong number, a contradiction with
   the code, or a reference to something that no longer exists is a correctness finding in a
   `.md` file and is judged, never excluded.
9. **Test-only files and fixtures.** Unless the diff makes a test the thing that gates a
   security control in production.
10. **Environment variables, CLI flags and CI configuration are trusted input.** An operator
    who can set them already has the privilege.
11. **UUID and cryptographically-random identifiers are unguessable.** "Enumerable ID" only
    applies to sequential or short identifiers.
12. **Open redirects** where the destination is validated against an allowlist in the diff.
13. **Missing defence in depth** where one correct check already exists on the path. Say
    which check you found.
14. **Pre-existing issues the diff did not introduce or touch.** Note them once, outside the
    candidate list.
15. **Anything a linter, type checker or the project's gate already reports.** The gate ran
    before you; do not spend judgment on what it printed.
16. **Style, naming, formatting and structure with no failure scenario.** These belong in
    NOTED.
17. **Speculative future misuse.** "If someone later calls this with X" is excluded unless a
    caller in this repository actually can.

## Deterministic pre-filter

**Run the three scope gates first.** These matches only apply to a candidate that is already
established as a security candidate and is not claimed by the local override. A keyword match
is never sufficient on its own — it selects a rule to consider, and you still apply the
rule's meaning.

Path matches respect path **segments**, never bare substrings: `latest`, `inspector` and
`respect` are not test files just because they contain `test` or `spec`.

- security finding whose only site ends in `.md`, `.txt`, `.rst` → consider 8
- path has a segment equal to `test`, `tests`, `spec`, `specs`, `fixture`, `fixtures`,
  `mock`, `mocks`, `__tests__`, or a basename matching `*_test.*` / `*.test.*` /
  `test_*.*` → consider 9
- text mentions denial of service, DoS, resource exhaustion, memory leak, ReDoS or
  catastrophic backtracking → consider 1 or 7
- text mentions rate limiting → consider 2, **unless the local override claims it**
- text mentions buffer overflow, use-after-free, double free or out-of-bounds, and the file
  is not `.c/.cc/.cpp/.h/.hpp` → consider 4
- text mentions XSS and the file is a framework component with no explicit escape hatch in
  the diff → consider 5

## What this list must never do

It must not reduce the finder's output. It must not turn a security finding into NOTED
because it seems minor. And it must not be applied to a correctness candidate — these rules
are about security noise. A correctness candidate is judged only by CONFIRMED / PLAUSIBLE /
REFUTED against the code.

Report every exclusion with its number. An exclusion the orchestrator cannot see is
indistinguishable from a miss.
