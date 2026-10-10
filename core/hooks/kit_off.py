"""kit_off() is True unless the project turned the kit on. The kit is OFF by default (bucket
kit-default-off-optimize, D002): it is ON exactly where /kit-on wrote the kit's rules copy,
<root>/.claude/rules/orchestration-kit.md, first line the installer's HEADER - the file Claude Code
itself loads as a project rule, so the hooks and the rules are on or off together. A file of that
name that is not the kit's (no HEADER) turns nothing on. Every kit hook calls this first and then
exits without a word. The root is CLAUDE_PROJECT_DIR, the launch dir - where Claude Code loads the
copy from; os.getcwd() only when it is unset. A hook that then picks another root to write into or
read from (payload cwd, D011) passes it as `root`, and a project that is off itself is never
touched through that fallback (D004). Only `os` is imported: an off project's hooks exit before
their heavy imports."""
import os

RULES = os.path.join(".claude", "rules", "orchestration-kit.md")
HEADER = b"<!-- orchestration-kit"


def launch_root():
    """The project a session runs in: CLAUDE_PROJECT_DIR, its launch dir; os.getcwd() when unset."""
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def kit_off(root=None):
    try:
        with open(os.path.join(launch_root() if root is None else root, RULES), "rb") as f:
            return f.read(len(HEADER)) != HEADER
    except OSError:
        return True
