"""kit_off() is True in a project that turned the kit off: /kit-off (and /kit-uninstall) write
`.claude/kit-off` at the project root. Every kit hook calls it first and then exits without a
word. The root is CLAUDE_PROJECT_DIR, the launch dir, which is also where Claude Code reads the
settings.local.json that drops the kit's rules and style; os.getcwd() only when it is unset.
A hook that then picks another root to write into or read from (payload cwd, D011) passes it
as `root`, so a project switched off is never touched through that fallback either."""
import os

MARKER = os.path.join(".claude", "kit-off")


def kit_off(root=None):
    if root is not None:
        return os.path.isfile(os.path.join(root, MARKER))
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return os.path.isfile(os.path.join(root, MARKER))
