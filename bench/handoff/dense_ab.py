"""Dense-STATE A/B (bucket handoff-timeline): does STATE.md written denser keep what the next
session needs? Uses the 4 real chains of the 2026-10-07 handoff A/B (bench/results/handoff-ab/,
their probes are already written from each session A's raw transcript).

Per chain, only the STATE.md block of kit_now.md (the old /continue material: STATE + DECISIONS
+ FINDINGS) is rewritten by Opus under the DENSE rules below - nothing else changes. Then a
cold, tool-less reader answers the same probes from each arm and a blind grader scores them
(ab.py's prompts and calls). Arms: kit_base (kit_now.md as written, re-read today) and kit_dense.

Adopt the dense rules only if kit_dense scores >= kit_base AND its STATE block is <= 70% of the
tokens (plan, 2026-10-09).

    python bench/handoff/dense_ab.py [chain ...] [--samples 2]
"""
import concurrent.futures as cf
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ab  # noqa: E402

CHAINS = ("frontdesk", "qartez", "scraper", "win11")
ab.ARMS["kit_base"] = ["kit_base.md"]
ab.ARMS["kit_dense"] = ["kit_dense.md"]

DENSE = """Rewrite the STATE.md below - a handoff note a fresh AI session resumes a task from - into
its DENSEST form that loses NOTHING.

Rules:
- Keep every fact, number, path, command, ID, error string, version, date, decision, reason,
  trap, open question and next step. If you are unsure whether something matters, keep it.
- Keep every quote of the user WORD FOR WORD, in its original language, inside quotes.
- Copy paths, commands, IDs, numbers and errors exactly, in backticks.
- Compress only the wording: fragments not sentences, `key: value`, `->` for cause, `·` between
  items on one line, no articles or filler, no repeated fact (say it once).
- Keep the section headings (## ...) the note has, in its order; a section may become one line.
- Output ONLY the rewritten STATE.md, nothing before or after it.

=== STATE.md ===
{STATE}
=== END ==="""


def split_state(text):
    """(before, STATE block, after) of a kit_now.md: from `# STATE` to the next top-level
    heading or tool-call record."""
    m = re.search(r"^# STATE\b.*$", text, re.M)
    if not m:
        return None
    rest = text[m.start():]
    end = re.search(r"^(# (?!STATE)|## (Bash|Read) \{)", rest[1:], re.M)
    cut = m.start() + 1 + end.start() if end else len(text)
    return text[:m.start()], text[m.start():cut], text[cut:]


def prepare(chain):
    base = ab.read_file(chain, "kit_now.md")
    parts = split_state(base) if base else None
    if not parts:
        return f"{chain}: no STATE block, skipped"
    shutil.copy(ab.p(chain, "kit_now.md"), ab.p(chain, "kit_base.md"))
    dst = ab.p(chain, "kit_dense.md")
    if not os.path.exists(dst):
        out = ab.claude(DENSE.replace("{STATE}", parts[1].strip()))
        dense = out["text"].strip()
        if not dense.startswith("#"):
            return f"{chain}: rewrite failed: {out.get('error', dense[:200])!r}"
        with open(dst, "w", encoding="utf-8") as f:
            f.write(parts[0] + dense + "\n\n" + parts[2])
    dense_block = split_state(ab.read_file(chain, "kit_dense.md"))[1]
    return (f"{chain}: STATE {len(parts[1]) // 4} -> {len(dense_block) // 4} tokens "
            f"({len(dense_block) * 100 // max(len(parts[1]), 1)}%)")


def report(chains):
    rows = {}
    for chain in chains:
        probes = {x["id"]: x for x in json.load(open(ab.p(chain, "probes.json"), encoding="utf-8"))["probes"]}
        for fn in sorted(os.listdir(ab.p(chain, "grades"))):
            arm = fn.rsplit("-", 1)[0]
            if arm not in ("kit_base", "kit_dense"):
                continue
            g = {x.get("id"): x for x in json.load(open(ab.p(chain, "grades", fn), encoding="utf-8"))["grades"]
                 if isinstance(x, dict)}
            r = rows.setdefault(arm, {"score": 0.0, "n": 0, "wrong": 0, "chain": {}})
            cs = r["chain"].setdefault(chain, [0.0, 0])
            for pid in probes:
                s = float((g.get(pid) or {}).get("score") or 0)
                r["score"] += s
                r["n"] += 1
                r["wrong"] += bool((g.get(pid) or {}).get("wrong"))
                cs[0] += s
                cs[1] += 1
    tok = {}
    for chain in chains:
        for arm, f in (("kit_base", "kit_base.md"), ("kit_dense", "kit_dense.md")):
            t = ab.read_file(chain, f)
            parts = split_state(t) if t else None
            if parts:
                tok.setdefault(arm, []).append(len(parts[1]) // 4)
    print(f"{'arm':10} {'score':>6} {'wrong':>5} {'STATE tok (sum)':>16}  " + " ".join(f"{c:>9}" for c in chains))
    for arm in ("kit_base", "kit_dense"):
        r = rows.get(arm)
        if not r:
            continue
        per = " ".join(f"{r['chain'].get(c, [0, 1])[0] * 100 / max(r['chain'].get(c, [0, 1])[1], 1):>8.0f}%" for c in chains)
        print(f"{arm:10} {r['score'] * 100 / max(r['n'], 1):>5.1f}% {r['wrong']:>5} {sum(tok.get(arm, [])):>16}  {per}")


def main(argv):
    samples = 2
    if "--samples" in argv:
        samples = int(argv[argv.index("--samples") + 1])
    chains = [c for c in argv if c in CHAINS] or list(CHAINS)
    with cf.ThreadPoolExecutor(4) as ex:
        for line in ex.map(prepare, chains):
            print(line, flush=True)
    ab.cmd_read(chains, samples, ["kit_base", "kit_dense"])
    ab.cmd_grade(chains)
    report(chains)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1:])
