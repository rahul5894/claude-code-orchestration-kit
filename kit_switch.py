"""Turn the kit off or back on for ONE project: `python kit_switch.py off|on <project-root>`.

off writes, under <root>/.claude/:
  kit-off               the kit hooks exit silently while it exists (core/hooks/kit_off.py);
                        md-guard keeps only its read-only-agent write guard
  settings.local.json   claudeMdExcludes += the kit's rules file, so neither the main session nor
                        a subagent loads it here (measured live 2026-09-23, 2.1.280); outputStyle
                        "default" only when the style in force here is a kit style - a style the
                        project or you chose yourself stays
on undoes what off recorded in kit-off, except that it never brings a kit style back: it leaves
the project on the default style, writing outputStyle "default" if a kit style would otherwise
be in force (the user's rule, 2026-10-10). settings.local.json is the
per-machine settings file. kit-off is a plain file: gitignore it in a shared repo, or commit it
to switch the kit off in every clone. An unreadable settings.local.json stops the script before
anything is written. /kit-off, /kit-on and /kit-uninstall call this."""
import json
import os
import sys

EXCLUDE = "**/.claude/rules/orchestration-kit.md"
KIT_STYLES = ("kit-lean", "orchestrator")
USER_SETTINGS = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")


def paths(root):
    d = os.path.join(root, ".claude")
    return d, os.path.join(d, "kit-off"), os.path.join(d, "settings.local.json")


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
    with open(sf, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def style_in_force(root, local):
    """The outputStyle this project runs with: local beats project beats user (docs:
    output-styles, "A project's own settings files take precedence")."""
    for d in (local, peek(os.path.join(root, ".claude", "settings.json")), peek(USER_SETTINGS)):
        if d.get("outputStyle") is not None:
            return d["outputStyle"]
    return None


def off(root):
    d, marker, sf = paths(root)
    # A second off would record "changed nothing" over the first one's record, and on could
    # then never undo the first.
    if os.path.isfile(marker):
        print(f"kit already OFF in {root}")
        return
    data = load(sf)
    excl = data.get("claudeMdExcludes", [])
    if not isinstance(excl, list):
        sys.exit(f"{sf}: claudeMdExcludes is not a list; fix it and re-run. Nothing was changed.")
    did = {"exclude": EXCLUDE not in excl,
           "style": style_in_force(root, data) in KIT_STYLES,
           "old_style": data.get("outputStyle")}
    if did["exclude"]:
        data["claudeMdExcludes"] = excl + [EXCLUDE]
    if did["style"]:
        data["outputStyle"] = "default"
    os.makedirs(d, exist_ok=True)
    # The record first, then the change it records: a settings write that fails takes the
    # record back with it, and a record write that fails leaves the settings untouched - never
    # a changed settings file that on could not undo (refuter-02).
    with open(marker, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(did) + "\n")
    try:
        save(sf, data)
    except BaseException:
        os.remove(marker)
        raise
    print(f"kit OFF in {root}: kit rules excluded, "
          f"style {'default' if did['style'] else 'left as ' + str(style_in_force(root, data))}. "
          "Hooks are silent now; the rules drop in the next new chat here.")


def on(root):
    _, marker, sf = paths(root)
    if not os.path.isfile(marker):
        print(f"kit already ON in {root} (no .claude/kit-off)")
        return
    try:
        with open(marker, encoding="utf-8-sig") as f:
            did = json.loads(f.read() or "null")
    except (OSError, ValueError):
        did = None
    # No readable record (hand-edited, emptied): take back the kit's own two values, so the
    # kit is really on again when this says so.
    if not isinstance(did, dict):
        did = {"exclude": True, "style": True, "old_style": None}
    data = load(sf)
    excl = data.get("claudeMdExcludes")
    if did.get("exclude") and isinstance(excl, list) and EXCLUDE in excl:
        data["claudeMdExcludes"] = [e for e in excl if e != EXCLUDE]
        if not data["claudeMdExcludes"]:
            del data["claudeMdExcludes"]
    if did.get("style") and data.get("outputStyle") == "default":
        del data["outputStyle"]
    # The user runs the default style everywhere (2026-10-10): on never puts a kit style back,
    # and one in force from the project's or the user's settings is overridden here, where
    # settings.local.json beats both.
    pinned = style_in_force(root, data) in KIT_STYLES
    if pinned:
        data["outputStyle"] = "default"
    if os.path.isfile(sf) or pinned:
        save(sf, data)
    os.remove(marker)
    print(f"kit ON in {root}, style {style_in_force(root, data) or 'default'}. "
          "Hooks are on now; the rules load in the next new chat here.")


def _selftest():
    global USER_SETTINGS
    import shutil
    import tempfile
    fails = []
    base = tempfile.mkdtemp(prefix="kit-switch-")
    # The machine's own ~/.claude/settings.json never takes part. The fixture is a user who
    # opted into kit-lean at user level; the shipped state (no user style) is tested last.
    USER_SETTINGS = os.path.join(base, "user-settings.json")
    with open(USER_SETTINGS, "w", encoding="utf-8") as f:
        f.write('{"outputStyle": "kit-lean"}')

    def ok(cond, label):
        print(("PASS  " if cond else "FAIL  ") + label)
        if not cond:
            fails.append(label)

    def rt(start, project=None):
        """off then on from a given settings.local.json body (None = no file)."""
        root = tempfile.mkdtemp(dir=base)
        d, marker, sf = paths(root)
        os.makedirs(d)
        if start is not None:
            with open(sf, "w", encoding="utf-8") as f:
                f.write(start)
        if project is not None:
            with open(os.path.join(d, "settings.json"), "w", encoding="utf-8") as f:
                f.write(project)
        off(root)
        mid = load(sf)
        on(root)
        end = load(sf) if os.path.isfile(sf) else None
        return root, marker, mid, end

    _, marker, mid, end = rt(None)
    ok(mid == {"claudeMdExcludes": [EXCLUDE], "outputStyle": "default"},
       "no settings file: off excludes the rules and sets the default style")
    ok(end == {"outputStyle": "default"} and not os.path.exists(marker),
       "... and on keeps default over the user's kit style, no marker")
    own = {"outputStyle": "Concise", "claudeMdExcludes": ["**/x.md"], "permissions": {"allow": ["Bash(ls)"]}}
    _, _, mid, end = rt(json.dumps(own))
    ok(mid["outputStyle"] == "Concise" and mid["claudeMdExcludes"] == ["**/x.md", EXCLUDE],
       "a style of your own and your excludes survive off")
    ok(end == own, "... and on restores the file exactly")
    _, _, mid, end = rt('{"outputStyle": "orchestrator"}')
    ok(mid["outputStyle"] == "default" and end == {"outputStyle": "default"},
       "a kit style becomes default, and on never puts it back")
    _, _, mid, end = rt(None, project='{"outputStyle": "Explanatory"}')
    ok("outputStyle" not in mid and end == {},
       "the project's own committed style is left in force (refuter-02)")
    root = tempfile.mkdtemp(dir=base)
    off(root)
    off(root)
    on(root)
    ok(load(paths(root)[2]) == {"outputStyle": "default"}, "off twice, then on: one undo, style default")
    _, _, mid, end = rt(json.dumps({"claudeMdExcludes": [EXCLUDE]}))
    ok(end == {"claudeMdExcludes": [EXCLUDE], "outputStyle": "default"},
       "an exclude that was already yours is not removed by on")
    root = tempfile.mkdtemp(dir=base)
    off(root)
    with open(paths(root)[1], "w", encoding="utf-8") as f:
        f.write("1")
    on(root)
    ok(load(paths(root)[2]) == {"outputStyle": "default"} and not os.path.exists(paths(root)[1]),
       "a hand-edited record: on still takes the kit's two values back (refuter-02)")
    root = tempfile.mkdtemp(dir=base)
    d, marker, sf = paths(root)
    os.makedirs(d)
    with open(sf, "w", encoding="utf-8") as f:
        f.write("{ not json")
    try:
        off(root)
        ok(False, "corrupt settings.local.json: off refuses")
    except SystemExit:
        ok(not os.path.exists(marker) and open(sf, encoding="utf-8").read() == "{ not json",
           "corrupt settings.local.json: off refuses, writes no marker, file untouched")
    root = tempfile.mkdtemp(dir=base)
    d, marker, sf = paths(root)
    os.makedirs(sf)  # a directory where the file goes: the settings write itself fails
    try:
        off(root)
        ok(False, "a failed settings write: off raises")
    except (OSError, SystemExit):
        ok(not os.path.exists(marker), "a failed settings write takes the record back with it")
    # The shipped state since kit-modes D013: no user-level style, so off must not write one.
    with open(USER_SETTINGS, "w", encoding="utf-8") as f:
        f.write("{}")
    _, marker, mid, end = rt(None)
    ok(mid == {"claudeMdExcludes": [EXCLUDE]} and end == {} and not os.path.exists(marker),
       "no user style (as installed): off excludes the rules only, on leaves {}")
    _, _, mid, end = rt(None, project='{"outputStyle": "orchestrator"}')
    ok(mid["outputStyle"] == "default" and end == {"outputStyle": "default"},
       "a kit style the project committed: on overrides it with default in settings.local.json")
    shutil.rmtree(base, ignore_errors=True)
    total = 13
    print(f"{total - len(fails)}/{total} passed")
    return 1 if fails else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        sys.exit(_selftest())
    if len(sys.argv) != 3 or sys.argv[1] not in ("off", "on"):
        sys.exit("usage: python kit_switch.py off|on <project-root>")
    (off if sys.argv[1] == "off" else on)(os.path.abspath(sys.argv[2]))
