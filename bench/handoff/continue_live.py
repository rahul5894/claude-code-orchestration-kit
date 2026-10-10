"""Live test: does /continue route a request to the right task (bucket continue-router)?
Drives the real Claude Code binary headless (stream-json) with whatever kit is installed in
~/.claude - run it before and after an install to compare.

A fixture shop app (real source files and git history that match the handoffs) holds three
open tasks and one closed two days ago:
  login-dark-mode  OPEN, one step from done (code in the working tree, only the commit is left)
  invoice-export   OPEN, mid-way (the CSV writer is a TODO)
  payment-retry    BLOCKED on one answer from the user (the retry delays)
  profile-avatar   CLOSED 2 days ago (committed)
Each scenario is a fresh window (a new session) that types one /continue:
  plain       /continue                                -> recommend login-dark-mode, ask
  match       /continue <more for the login dark mode>  -> login-dark-mode, confirm first
  new         /continue <a pricing page>               -> a new task, ask new vs finish first
  closed      /continue <more for the avatar upload>   -> offer to reopen profile-avatar
  ambiguous   /continue <"the billing work">           -> ask: invoice-export or payment-retry
  unblock     /continue <the retry delays>             -> payment-retry, confirm first
Right = it put the expected task first (the recommended option), asked before doing anything,
and changed no file before the answer. Also counted: bucket files it opened before answering
(the cards exist so that it opens none) and the cost. With --follow, `match`, `new` and
`closed` get a second turn that takes the recommended option, and the files are checked after.

    python bench/handoff/continue_live.py [--model opus] [--samples 2] [--follow] [--keep] [--tag old]
Writes only into temp project dirs (their transcripts land in ~/.claude/projects, as any
session's). Results: bench/results/continue-live/<tag>.json.
"""
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import queue

CLAUDE = os.environ.get("CLAUDE_CODE_EXECPATH") or shutil.which("claude") or "claude"
DROP = ("CLAUDE_PROJECT_DIR", "CLAUDE_PID", "CLAUDE_CODE_SESSION_ID", "CLAUDECODE",
        "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SSE_PORT")
SLUGS = ("login-dark-mode", "invoice-export", "payment-retry", "profile-avatar")


def day(n):
    return time.strftime("%Y-%m-%d", time.localtime(time.time() - n * 86400))


def states():
    return {
        "login-dark-mode": f"""# STATE — login-dark-mode
About: Dark mode for the login page - a theme toggle in its header, colours from src/styles/tokens.css.
Updated: {day(1)} 18:10 IST   Status: OPEN   Priority: P2
## Objective
The login page follows a dark theme when the user picks it; the choice is remembered.
## Repo
branch master, 2 files changed and not committed (src/pages/Login.tsx, src/styles/tokens.css)
## Scope — in
src/pages/Login.tsx, src/styles/tokens.css, the header toggle
## Scope — out
the rest of the app's pages
## Next action
Only the commit is left: run the gate, then commit `feat: login dark mode`.
## User said
- "toggle header mein hi rakhna"
""",
        "invoice-export": f"""# STATE — invoice-export
Updated: {day(2)} 12:00 IST   Status: OPEN   Priority: P2
## Objective
Export the billing screen's invoices as CSV (date, number, customer, amount, GST).
## Scope — in
src/billing/export.ts, the Export button on the billing screen (already wired)
## Next action
Write the CSV writer in src/billing/export.ts (the TODO in exportInvoices), then its tests (3 of 6 steps done).
""",
        "payment-retry": f"""# STATE — payment-retry
About: Retry failed card payments automatically, 3 attempts with backoff, then email the customer.
Updated: {day(3)} 16:30 IST   Status: BLOCKED   Priority: P2
## Objective
A failed card payment is retried 3 times with growing delays before the customer is emailed.
## Next action
Blocked on the user: which retry delays - 1/5/15 minutes or 1/2/4 hours? Then write src/payments/retry.ts next to charge.ts.
""",
        "profile-avatar": f"""# STATE — profile-avatar
About: Avatar upload on the profile page with a square crop, files up to 2 MB.
Updated: {day(2)} 20:00 IST   Status: CLOSED {day(2)} - shipped in commit "feat: avatar upload with square crop, 2 MB limit"
## Objective
Users upload an avatar on the profile page, crop it square; files up to 2 MB (MAX_AVATAR_BYTES in src/pages/Profile.tsx).
## Next action
None - closed.
""",
    }


INDEX = ("# Task index\n<!-- One line per bucket. Claude updates this whenever a bucket changes. -->\n"
         "| slug | status | updated | next action |\n|---|---|---|---|\n"
         "| profile-avatar | DONE | {d2} | none - shipped |\n"
         "| payment-retry | BLOCKED | {d3} | waiting: which retry delays |\n"
         "| invoice-export | OPEN | {d2} | CSV writer, then tests |\n"
         "| login-dark-mode | OPEN | {d1} | commit is left |\n")

SOURCE = {
    "package.json": '{\n  "name": "shop-app",\n  "private": true,\n  "scripts": {"test": "echo ok"}\n}\n',
    "src/pages/Login.tsx": "export function Login() {\n  return (\n    <main className=\"login\">\n"
                           "      <header><h1>Sign in</h1></header>\n      <form>{/* email, password */}</form>\n"
                           "    </main>\n  );\n}\n",
    "src/styles/tokens.css": ":root {\n  --bg: #ffffff;\n  --fg: #111111;\n}\n",
    "src/billing/BillingScreen.tsx": "import { exportInvoices } from './export';\n\nexport function BillingScreen() {\n"
                                     "  return <button onClick={() => exportInvoices([])}>Export</button>;\n}\n",
    "src/billing/export.ts": "export type Invoice = { date: string; number: string; customer: string; amount: number; gst: string };\n\n"
                             "export function exportInvoices(invoices: Invoice[]): string {\n"
                             "  // TODO: CSV writer (date, number, customer, amount, GST)\n  return '';\n}\n",
    "src/payments/charge.ts": "export async function chargeCard(customerId: string, cents: number): Promise<boolean> {\n"
                              "  return true;\n}\n",
}
AVATAR = ("export const MAX_AVATAR_BYTES = 2 * 1024 * 1024;\n\nexport function Profile() {\n"
          "  return <section><input type=\"file\" accept=\"image/*\" /> {/* square crop */}</section>;\n}\n")
DARK_LOGIN = ("import { useState } from 'react';\n\nexport function Login() {\n"
              "  const [dark, setDark] = useState(localStorage.getItem('theme') === 'dark');\n"
              "  return (\n    <main className={dark ? 'login dark' : 'login'}>\n"
              "      <header><h1>Sign in</h1>\n"
              "        <button onClick={() => { localStorage.setItem('theme', dark ? 'light' : 'dark'); setDark(!dark); }}>Theme</button>\n"
              "      </header>\n      <form>{/* email, password */}</form>\n    </main>\n  );\n}\n")
DARK_TOKENS = ":root {\n  --bg: #ffffff;\n  --fg: #111111;\n}\n.dark {\n  --bg: #111111;\n  --fg: #f5f5f5;\n}\n"

SCENARIOS = {
    "plain": ("/continue", "login-dark-mode"),
    "match": ("/continue login page ke dark mode mein ek 'system theme' option bhi chahiye, aur header ka logo mat badalna",
              "login-dark-mode"),
    "new": ("/continue humein ek naya pricing page banana hai jisme teen plans ke cards hon", "new"),
    "closed": ("/continue avatar upload mein ab 5 MB tak ki file allow karni hai", "profile-avatar"),
    "ambiguous": ("/continue billing wala kaam aage badhao", "invoice-export|payment-retry"),
    "unblock": ("/continue payment retry ke delays 1, 5 aur 15 minute rakho", "payment-retry"),
}


def write(root, rel, text):
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def git(root, *args):
    subprocess.run(["git", "-c", "user.name=dev", "-c", "user.email=dev@shop.test", *args], cwd=root,
                   capture_output=True)


def project():
    root = tempfile.mkdtemp(prefix="kit-cont-")
    write(root, "CLAUDE.md", "# shop app\n| **FAST GATE — agents run this** | `npm test` | 0.5 s |\n")
    write(root, ".gitignore", ".claude/scratch/\nnode_modules/\n")
    for rel, text in SOURCE.items():
        write(root, rel, text)
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "init: shop app")
    write(root, "src/pages/Profile.tsx", AVATAR)
    git(root, "add", "-A")
    git(root, "commit", "-qm", "feat: avatar upload with square crop, 2 MB limit")
    write(root, "src/pages/Login.tsx", DARK_LOGIN)   # done, not committed: only the commit is left
    write(root, "src/styles/tokens.css", DARK_TOKENS)
    scratch = ".claude/scratch/"
    for slug, text in states().items():
        write(root, scratch + slug + "/STATE.md", text)
        write(root, scratch + slug + "/FINDINGS.md", f"# FINDINGS — {slug}\n")
        write(root, scratch + slug + "/DECISIONS.md", f"# DECISIONS — {slug}\n")
    write(root, scratch + "INDEX.md", INDEX.format(d1=day(1), d2=day(2), d3=day(3)))
    for slug, age_h in (("login-dark-mode", 20), ("invoice-export", 50), ("payment-retry", 70), ("profile-avatar", 44)):
        p = os.path.join(root, ".claude", "scratch", slug, "STATE.md")
        t = time.time() - age_h * 3600
        os.utime(p, (t, t))
    return root


class Window:
    def __init__(self, root, model):
        env = {k: v for k, v in os.environ.items() if k not in DROP}
        cmd = [CLAUDE, "-p", "--input-format", "stream-json", "--output-format", "stream-json",
               "--verbose", "--permission-mode", "bypassPermissions"]
        if model:
            cmd += ["--model", model]
        self.p = subprocess.Popen(cmd, cwd=root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL)
        self.q = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        self.tools_offered = []

    def _read(self):
        for raw in self.p.stdout:
            try:
                self.q.put(json.loads(raw.decode("utf-8", "replace")))
            except ValueError:
                pass

    def say(self, text, timeout=480):
        """One user message -> (result text, [tool_use blocks in order], result event)."""
        msg = {"type": "user", "message": {"role": "user", "content": text}}
        self.p.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
        self.p.stdin.flush()
        tools = []
        while True:
            o = self.q.get(timeout=timeout)
            if o.get("type") == "system" and o.get("subtype") == "init":
                self.tools_offered = list(o.get("tools") or [])
            if o.get("type") == "assistant":
                for b in (o.get("message") or {}).get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        tools.append({"name": b.get("name"), "input": b.get("input") or {}})
            if o.get("type") == "result":
                return str(o.get("result") or ""), tools, o

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=90)
        except Exception:
            self.p.kill()


def bucket_reads(tools):
    """Bucket files a turn opened: {slug: count}, from tool inputs (Read paths, shell commands)."""
    out = {}
    for t in tools:
        text = json.dumps(t["input"], ensure_ascii=False)
        for slug in SLUGS:
            if re.search(r"scratch[/\\\\]+" + re.escape(slug) + r"[/\\\\]", text):
                out[slug] = out.get(slug, 0) + 1
    return out


def changed(tools):
    """True when the turn changed a file or committed: it should have asked first."""
    for t in tools:
        if t["name"] in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
            return True
        cmd = str(t["input"].get("command") or "")
        if t["name"] in ("Bash", "PowerShell") and re.search(r"git\s+commit|>>?\s*\S|\bmkdir\b|Set-Content|Add-Content|New-Item", cmd):
            return True
    return False


def options_of(tools):
    for t in tools:
        if t["name"] == "AskUserQuestion":
            qs = t["input"].get("questions") or []
            if qs:
                return [str(o.get("label", "")) + " :: " + str(o.get("description", "")) for o in qs[0].get("options") or []]
    return []


NEW_WORDS = re.compile(r"new task|naya task|new bucket|naya bucket|open (?:a )?new|start (?:a )?new|naya kaam", re.IGNORECASE)
REC = re.compile(r"recommend|suggest|sujhav|salah|\(recommended\)", re.IGNORECASE)


def pick_of(text, options):
    """The task the answer puts first: AskUserQuestion's first option, else the slug (or a new
    task) nearest to a 'recommend' word, else the first one named."""
    if options:
        first = options[0].lower()
        hits = [s for s in SLUGS if s in first]
        return "new" if NEW_WORDS.search(first) and not hits else (hits[0] if hits else "?")
    low = text.lower()
    marks = [m.start() for m in REC.finditer(low)]
    cands = [(m.start(), s) for s in SLUGS for m in re.finditer(re.escape(s), low)]
    cands += [(m.start(), "new") for m in NEW_WORDS.finditer(low)]
    if marks and cands:
        dist, pos, who = min((min(abs(c - k) for k in marks), c, s) for c, s in cands)
        if dist <= 160:
            return who
    return min(cands)[1] if cands else "?"


def run(name, model, follow, keep):
    prompt, want = SCENARIOS[name]
    root = project()
    w = Window(root, model)
    row = {"scenario": name, "want": want, "root": root}
    try:
        text, tools, res = w.say(prompt)
        opts = options_of(tools)
        row.update(text=text, options=opts, pick=pick_of(text, opts), reads=bucket_reads(tools),
                   changed=changed(tools), cost=res.get("total_cost_usd") or 0.0, turns=res.get("num_turns"),
                   asked=bool(opts) or "?" in text[-700:], ask_tool_offered="AskUserQuestion" in w.tools_offered,
                   tools=[t["name"] for t in tools])
        if follow and name in ("match", "new", "closed"):
            text2, tools2, res2 = w.say("haan, jo aapne recommend kiya wahi karo")
            row["cost"] += res2.get("total_cost_usd") or 0.0
            row["follow"] = check_follow(name, root, tools2)
            row["text2"] = text2
    except queue.Empty:
        row.update(text="(timeout)", options=[], pick="timeout", reads={}, changed=False, cost=0.0, asked=False)
    finally:
        w.close()
        if not keep:
            shutil.rmtree(root, ignore_errors=True)
    return row


def check_follow(name, root, tools):
    scratch = os.path.join(root, ".claude", "scratch")
    reads = bucket_reads(tools)

    def text(*p):
        try:
            return open(os.path.join(scratch, *p), encoding="utf-8").read()
        except OSError:
            return ""
    new = sorted(d for d in os.listdir(scratch)
                 if os.path.isdir(os.path.join(scratch, d)) and d not in SLUGS and not d.startswith("_"))
    if name == "match":
        st = text("login-dark-mode", "STATE.md").lower()
        return {"instruction_in_state": "system theme" in st or "system-theme" in st,
                "read_history": reads.get("login-dark-mode", 0) > 0,
                "other_buckets_opened": sorted(s for s in reads if s != "login-dark-mode"), "new_buckets": new}
    if name == "closed":
        st = text("profile-avatar", "STATE.md")
        return {"reopened": bool(re.search(r"Status\W{1,6}OPEN", st)), "index_open": bool(re.search(
                r"\|\s*profile-avatar\s*\|\s*OPEN", text("INDEX.md"))), "new_buckets": new,
                "other_buckets_opened": sorted(s for s in reads if s != "profile-avatar")}
    return {"new_buckets": new, "in_index": bool(new) and all(d in text("INDEX.md") for d in new),
            "about_line": any("About:" in text(d, "STATE.md") for d in new),
            "other_buckets_opened": sorted(reads)}


NUMBERED = re.compile(r"(?:^|\s)\**1[.)]\**\s.+?(?:^|\s)\**2[.)]\**\s", re.DOTALL)


def asked_of(row):
    """It asked: an AskUserQuestion call, a question mark, or numbered options to pick from
    (headless runs have no AskUserQuestion; run 3 wrote "pick a number: 1. ... 2. ...")."""
    text = row.get("text") or ""
    return bool(row.get("options")) or "?" in text or bool(NUMBERED.search(text))


def right(row):
    """Asked before changing anything, and routed as the scenario wants: plain/match/unblock -
    the task first; closed - reopen that task; ambiguous - both billing tasks offered; new - it
    says the request is a new task (recommending a nearly done task first is the rule, D004)."""
    text = ((row.get("text") or "") + " " + " ".join(row.get("options") or [])).lower()
    if row.get("changed") or not asked_of(row):
        return False
    name = row["scenario"]
    if name == "ambiguous":
        return "invoice-export" in text and "payment-retry" in text
    if name == "new":
        return bool(NEW_WORDS.search(text))
    if name == "closed":
        return row["pick"] == "profile-avatar" and "reopen" in text
    return row["pick"] in row["want"].split("|")


def main():
    arg = sys.argv[1:]
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results", "continue-live")
    if "--rescore" in arg:  # score saved runs again with today's rules, no model call
        for tag in arg[arg.index("--rescore") + 1].split(","):
            rows = json.load(open(os.path.join(out, f"{tag}.json"), encoding="utf-8"))
            for r in rows:
                r["pick"] = pick_of(r.get("text") or "", r.get("options") or [])
            per = {}
            for r in rows:
                per.setdefault(r["scenario"], []).append(right(r))
            print(f"{tag:6} right {sum(map(right, rows))}/{len(rows)}  "
                  + "  ".join(f"{k} {sum(v)}/{len(v)}" for k, v in per.items())
                  + f"  | changed-first {sum(bool(r.get('changed')) for r in rows)}"
                  + f"  bucket-reads {sum(sum((r.get('reads') or {}).values()) for r in rows)}"
                  + f"  ${sum(r.get('cost') or 0 for r in rows):.2f}")
        return
    model = arg[arg.index("--model") + 1] if "--model" in arg else None
    samples = int(arg[arg.index("--samples") + 1]) if "--samples" in arg else 1
    only = arg[arg.index("--only") + 1].split(",") if "--only" in arg else list(SCENARIOS)
    jobs = [(s, i) for s in only for i in range(samples)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        rows = list(ex.map(lambda j: run(j[0], model, "--follow" in arg, "--keep" in arg), jobs))
    good = 0
    for r in rows:
        ok = right(r)
        r["right"] = ok
        r["asked"] = asked_of(r)
        good += ok
        print(f"{r['scenario']:9} want {r['want']:28} got {r['pick']:16} asked {str(r['asked']):5} "
              f"changed-first {str(r['changed']):5} bucket-reads {sum(r['reads'].values()):2} "
              f"${r['cost']:.3f} {'OK ' if ok else 'BAD'}  tools {r.get('tools')}")
        if r.get("options"):
            print(f"          options: {r['options']}")
        print(f"          reply: {' '.join((r.get('text') or '').split())[:420]}")
        if "follow" in r:
            print(f"          follow-up: {r['follow']}")
    print(f"\nright: {good}/{len(rows)}   bucket files opened before answering: "
          f"{sum(sum(r['reads'].values()) for r in rows)}   cost: ${sum(r['cost'] for r in rows):.2f}   "
          f"AskUserQuestion offered: {sorted({str(r.get('ask_tool_offered')) for r in rows})}")
    os.makedirs(out, exist_ok=True)
    tag = arg[arg.index("--tag") + 1] if "--tag" in arg else "run"
    with open(os.path.join(out, f"{tag}.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
