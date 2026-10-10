"""Turn the kit on or off for ONE project: `python kit_switch.py on|off <project-root>`.

The kit is OFF in every project by default (bucket kit-default-off-optimize, D002). It is ON
exactly when <root>/.claude/rules/orchestration-kit.md - the kit's own rules copy - exists:
Claude Code loads it in the main session and in every subagent like any project rule, and every
kit hook looks for it first (core/hooks/kit_off.py). One file is both the switch and the rules.

on   copies the installed rules (orchestration-kit.md beside this script, ~/.claude/kit/) to
     that path, lists it in the repo's .git/info/exclude so it is never committed by accident,
     keeps the project on the default style (a kit style in force here is overridden with
     outputStyle "default" in .claude/settings.local.json - the user's rule, 2026-10-10), and
     clears what the old default-on kit left: .claude/kit-off and the claudeMdExcludes entry
     that would hide the copy.
off  deletes the copy - only when its first line is the kit's header - and resets a kit style
     in force to "default". The hooks go quiet at their next event; the rules leave with the
     next new chat (/clear or a new window).
An unreadable settings.local.json stops the script before anything is written.
/kit-on, /kit-off, /kit-init and /kit-uninstall call this."""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# The hooks' own switch, rules guard and writer - one definition for both: installed, ~/.claude/hooks/
# beside this script's ~/.claude/kit/; in the kit checkout, core/hooks/.
sys.path[:0] = [os.path.join(os.path.dirname(HERE), "hooks"), os.path.join(HERE, "core", "hooks")]
from kit_off import HEADER, RULES, kit_off  # noqa: E402
from kit_index import installed_rules, rules_blocker, sync_rules  # noqa: E402

SOURCE = installed_rules()
# Left by the default-on kit's /kit-off. The exclude matches the project copy too, so on drops it.
LEGACY_MARKER = os.path.join(".claude", "kit-off")
EXCLUDE = "**/.claude/rules/orchestration-kit.md"
KIT_STYLES = ("kit-lean", "orchestrator")
USER_SETTINGS = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")


def local_settings(root):
    return os.path.join(root, ".claude", "settings.local.json")


def load(sf):
    if not os.path.isfile(sf):
        return {}
    # utf-8-sig: an editor's BOM is not a reason to refuse the file.
    with open(sf, encoding="utf-8-sig", errors="strict") as f:
        try:
            text = f.read()
        except UnicodeDecodeError:
            sys.exit(f"{sf} is not UTF-8; fix it and re-run. Nothing was changed.")
    try:
        data = json.loads(text) if text.strip() else {}
    except ValueError:
        sys.exit(f"{sf} is not valid JSON; fix it and re-run. Nothing was changed.")
    if not isinstance(data, dict):
        sys.exit(f"{sf} is not a JSON object; fix it and re-run. Nothing was changed.")
    return data


def peek(sf):
    """A settings file only read, never written: unreadable counts as empty."""
    try:
        with open(sf, encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(sf, data):
    os.makedirs(os.path.dirname(sf), exist_ok=True)
    with open(sf, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def style_in_force(root, local):
    """The outputStyle this project runs with: local beats project beats user (docs:
    output-styles, "A project's own settings files take precedence")."""
    for d in (local, peek(os.path.join(root, ".claude", "settings.json")), peek(USER_SETTINGS)):
        if d.get("outputStyle") is not None:
            return d["outputStyle"]
    return None


def default_style(root, data):
    """outputStyle "default" into `data` when a kit style is in force here; True when it did."""
    if style_in_force(root, data) in KIT_STYLES:
        data["outputStyle"] = "default"
        return True
    return False


def exclude_from_git(root):
    """The copy into the repo's own .git/info/exclude - local, never committed - so `git add -A`
    cannot publish it; a project in a subfolder of its repo is listed by its path from the top.
    Nothing when root is no git work tree or git is missing."""
    try:
        r = subprocess.run(["git", "-C", root, "rev-parse", "--git-path", "info/exclude", "--show-prefix"],
                           capture_output=True, text=True, timeout=15)
        out = r.stdout.split("\n")
        if r.returncode or not out[0].strip():
            return
        path = os.path.join(root, out[0].strip())
        line = "/" + (out[1].strip() if len(out) > 1 else "") + RULES.replace(os.sep, "/")
        text = ""
        if os.path.isfile(path):
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        if line not in text.splitlines():
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8", newline="\n") as f:
                f.write(("" if not text or text.endswith("\n") else "\n") + line + "\n")
    except (OSError, subprocess.SubprocessError):
        pass


def on(root, source=SOURCE):
    try:
        with open(source, "rb") as f:
            rules = f.read()
    except OSError:
        sys.exit(f"{source} is missing: run install.ps1 in the kit checkout. Nothing was changed.")
    if not rules.startswith(HEADER):
        sys.exit(f"{source} is not the kit's rules file. Nothing was changed.")
    # The home folder (its .claude is Claude Code's config), a link on the way, a file of that name
    # that is the project's own: the rule the session-start refresh follows too (kit_index).
    why = rules_blocker(root)
    if why:
        sys.exit(f"{os.path.join(root, RULES)}: {why}. Nothing was changed.")
    was_on = not kit_off(root)
    sf = local_settings(root)
    data = load(sf)
    changed = default_style(root, data)
    excl = data.get("claudeMdExcludes")
    if isinstance(excl, list) and EXCLUDE in excl:
        data["claudeMdExcludes"] = [e for e in excl if e != EXCLUDE]
        if not data["claudeMdExcludes"]:
            del data["claudeMdExcludes"]
        changed = True
    if changed:
        save(sf, data)
    # The copy is the switch, so it is written last and whole: a crash before this line leaves the
    # kit off, never half on.
    written = sync_rules(root, rules) == "written"
    try:
        os.remove(os.path.join(root, LEGACY_MARKER))
    except OSError:
        pass
    exclude_from_git(root)
    state = ("already ON, rules refreshed" if written else "already ON") if was_on else "ON"
    print(f"kit {state} in {root}, style {style_in_force(root, data) or 'default'}. Hooks run from "
          "their next event; the kit rules load in the next new chat here (/clear).")


def off(root):
    sf = local_settings(root)
    data = load(sf)
    copy = os.path.join(root, RULES)
    present = os.path.isfile(copy)
    if present and kit_off(root):
        sys.exit(f"{copy} is not the kit's (its first line is no `<!-- orchestration-kit` header), "
                 "so it was left as it is. Nothing was changed.")
    if default_style(root, data):
        save(sf, data)
    if present:
        os.remove(copy)
        try:
            os.rmdir(os.path.dirname(copy))  # only when the kit's file was all it held
        except OSError:
            pass
    print(f"kit {'OFF' if present else 'already OFF'} in {root}. The hooks are silent from their "
          "next event; the kit rules leave with the next new chat here (/clear).")


def _selftest():
    global USER_SETTINGS
    import shutil
    import tempfile
    fails = []
    base = tempfile.mkdtemp(prefix="kit-switch-")
    # The machine's own ~/.claude/settings.json never takes part: a user who opted into
    # kit-lean at user level first, the shipped state (no user style) later.
    USER_SETTINGS = os.path.join(base, "user-settings.json")
    with open(USER_SETTINGS, "w", encoding="utf-8") as f:
        f.write('{"outputStyle": "kit-lean"}')
    src = os.path.join(base, "orchestration-kit.md")
    with open(src, "wb") as f:
        f.write(HEADER + b" (fork of x) -->\n# rules v1\n")

    def ok(cond, label):
        print(("PASS  " if cond else "FAIL  ") + label)
        if not cond:
            fails.append(label)

    def project(local=None, shared=None):
        root = tempfile.mkdtemp(dir=base)
        os.makedirs(os.path.join(root, ".claude"))
        for name, body in (("settings.local.json", local), ("settings.json", shared)):
            if body is not None:
                with open(os.path.join(root, ".claude", name), "w", encoding="utf-8") as f:
                    f.write(body)
        return root

    def read(path, mode="r"):
        with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as f:
            return f.read()

    def refused(fn, *args):
        try:
            fn(*args)
        except SystemExit:
            return True
        return False

    git = True
    try:
        root = project()
        ok(kit_off(root), "a new project is off: no rules copy, the hooks stay silent")
        on(root, src)
        copy = os.path.join(root, RULES)
        ok(read(copy, "rb") == read(src, "rb") and not kit_off(root)
           and load(local_settings(root)) == {"outputStyle": "default"},
           "on: the rules copy is the installed file byte for byte, the hooks see the kit on, and the "
           "user's kit-lean is overridden with default here")
        with open(src, "ab") as f:
            f.write(b"# rules v2\n")
        on(root, src)
        ok(read(copy, "rb").endswith(b"# rules v2\n"), "on twice: idempotent, a changed source refreshes the copy")
        off(root)
        ok(kit_off(root) and not os.path.exists(copy) and not os.path.isdir(os.path.dirname(copy)),
           "off: the copy goes, its emptied .claude/rules/ with it, the hooks see the kit off")
        off(root)
        ok(kit_off(root), "off twice: still off, no error")
        root = project()
        os.makedirs(os.path.join(root, ".claude", "rules"))
        with open(os.path.join(root, RULES), "w", encoding="utf-8") as f:
            f.write("# the project's own file of that name\n")
        ok(refused(off, root) and read(os.path.join(root, RULES)) == "# the project's own file of that name\n",
           "off never deletes a file at that path that is not the kit's")
        legacy = json.dumps({"claudeMdExcludes": ["**/x.md", EXCLUDE], "permissions": {"allow": ["Bash(ls)"]}})
        root = project(legacy)
        with open(os.path.join(root, LEGACY_MARKER), "w", encoding="utf-8") as f:
            f.write("{}")
        on(root, src)
        ok(load(local_settings(root)) == {"claudeMdExcludes": ["**/x.md"], "permissions": {"allow": ["Bash(ls)"]},
                                          "outputStyle": "default"}
           and not os.path.exists(os.path.join(root, LEGACY_MARKER)),
           "on clears the old kit's marker and the exclude that would hide the copy; the user's own keys stay")
        root = project("{ not json")
        ok(refused(on, root, src) and not os.path.exists(os.path.join(root, RULES))
           and read(local_settings(root)) == "{ not json",
           "a corrupt settings.local.json: on refuses, writes no copy, leaves the file as it was")
        root = project()
        ok(refused(on, root, os.path.join(base, "missing.md")) and kit_off(root),
           "no installed rules file: on refuses and the kit stays off")
        with open(USER_SETTINGS, "w", encoding="utf-8") as f:  # the shipped state: no user style
            f.write("{}")
        root = project(shared='{"outputStyle": "orchestrator"}')
        on(root, src)
        ok(load(local_settings(root)) == {"outputStyle": "default"},
           "a kit style the project committed: on overrides it with default in settings.local.json")
        root = project('{"outputStyle": "Explanatory"}')
        on(root, src)
        off(root)
        ok(load(local_settings(root)) == {"outputStyle": "Explanatory"}, "a style of your own survives on and off")
        root = project('{"outputStyle": "kit-lean"}')
        on(root, src)
        with open(local_settings(root), "w", encoding="utf-8") as f:
            f.write('{"outputStyle": "kit-lean"}')
        off(root)
        ok(load(local_settings(root)) == {"outputStyle": "default"}, "off resets a kit style in force to default")
        root = project()
        git = subprocess.run(["git", "init", "-q", root], capture_output=True).returncode == 0
        if git:
            on(root, src)
            on(root, src)
            excl = read(os.path.join(root, ".git", "info", "exclude"))
            st = subprocess.run(["git", "-C", root, "status", "--porcelain", "--untracked-files=all"],
                                capture_output=True, text=True).stdout
            sub = os.path.join(root, "app")
            os.makedirs(os.path.join(sub, ".claude"))
            on(sub, src)
            st2 = subprocess.run(["git", "-C", root, "status", "--porcelain", "--untracked-files=all"],
                                 capture_output=True, text=True).stdout
            ok(excl.splitlines().count("/.claude/rules/orchestration-kit.md") == 1 and "orchestration-kit" not in st
               and "/app/.claude/rules/orchestration-kit.md" in read(os.path.join(root, ".git", "info", "exclude"))
               and "orchestration-kit" not in st2,
               "in a git repo the copy is listed once in .git/info/exclude and never shows as untracked; "
               "a project in a subfolder of its repo is listed by its path from the top")
        else:
            print("SKIP  git is not installed: the .git/info/exclude case")
        # on never writes over a file of that name that is the project's own, nor where a link points.
        root = project()
        os.makedirs(os.path.join(root, ".claude", "rules"))
        with open(os.path.join(root, RULES), "w", encoding="utf-8") as f:
            f.write("# the project's own file of that name\n")
        own_kept = refused(on, root, src) and read(os.path.join(root, RULES)) == "# the project's own file of that name\n"
        victim = os.path.join(base, "victim.txt")
        with open(victim, "w", encoding="utf-8") as f:
            f.write("keep me\n")
        outside = os.path.join(base, "outside")
        os.makedirs(outside)
        try:
            root = project()  # a rules folder that is a link: the copy would land where it points
            os.symlink(outside, os.path.join(root, ".claude", "rules"), target_is_directory=True)
            dir_refused = refused(on, root, src) and os.listdir(outside) == []
            root = project()  # a `.tmp` link planted beside the copy: the writer's tmp is its own
            os.makedirs(os.path.join(root, ".claude", "rules"))
            os.symlink(victim, os.path.join(root, RULES + ".tmp"))
            on(root, src)
            tmp_safe = read(victim) == "keep me\n" and not kit_off(root)
        except OSError:
            print("SKIP  this machine cannot create symlinks: the two link cases (counted as passed)")
            dir_refused = tmp_safe = True
        ok(own_kept and dir_refused and tmp_safe and kit_off(os.path.join(base, "nowhere")),
           "on refuses the project's own file of that name and a linked rules folder; a planted `.tmp` "
           "link is never written through; a file without the kit's header is no switch")
        # The home folder: its .claude IS Claude Code's config, where a copy would be the GLOBAL
        # rules file - on every project.
        home = os.path.join(base, "home")
        os.makedirs(os.path.join(home, ".claude"))
        saved = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(home, ".claude")
        try:
            ok(refused(on, home, src) and not os.path.exists(os.path.join(home, RULES)),
               "on refuses the home folder: its .claude is the config dir, a copy there would load in every project")
        finally:
            if saved is None:
                os.environ.pop("CLAUDE_CONFIG_DIR", None)
            else:
                os.environ["CLAUDE_CONFIG_DIR"] = saved
    finally:
        shutil.rmtree(base, ignore_errors=True)
    total = 15 - (0 if git else 1)
    print(f"{total - len(fails)}/{total} passed")
    return 1 if fails else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        sys.exit(_selftest())
    if len(sys.argv) != 3 or sys.argv[1] not in ("off", "on"):
        sys.exit("usage: python kit_switch.py on|off <project-root>")
    (off if sys.argv[1] == "off" else on)(os.path.abspath(sys.argv[2]))
