"""Config file persistence for claude-tokens settings."""

import os

CONFIG_PATH = os.path.expanduser("~/.claude/claude-tokens.conf")


def load(path=CONFIG_PATH):
    """Load config into os.environ — env vars already set take priority."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip()
                if k and v and k not in os.environ:
                    os.environ[k] = v


def save(updates: dict, path=CONFIG_PATH):
    """Write/update keys in config file, preserving existing lines and comments."""
    lines = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()

    # Track which keys still need to be written (not yet updated in-place)
    remaining = dict(updates)

    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.partition("=")[0].strip()
            if k in remaining:
                new_lines.append(f"{k}={remaining.pop(k)}\n")
                continue
        new_lines.append(line)

    # Append any keys not already in the file
    if remaining:
        if new_lines and new_lines[-1].strip():
            new_lines.append("\n")
        for k, v in remaining.items():
            new_lines.append(f"{k}={v}\n")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


def is_first_run(path=CONFIG_PATH) -> bool:
    if not os.path.exists(path):
        return True
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip().startswith("CLAUDE_ONBOARDED="):
                return False
    return True


def mark_onboarded(path=CONFIG_PATH):
    save({"CLAUDE_ONBOARDED": "1"}, path)


def offer_save(updates: dict, path=CONFIG_PATH):
    """Ask user to save updates to config file. Returns True if saved."""
    try:
        ans = input(f"\n  Save to {path}? [Y/n]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        return False
    if ans in ("", "y", "yes"):
        save(updates, path)
        print(f"  Saved.")
        return True
    return False
