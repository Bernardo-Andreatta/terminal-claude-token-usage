#!/usr/bin/env python3
"""Interactive color picker for claude-tokens display roles."""

import os
import re
from claude_tokens.config import offer_save

R = "\033[0m"
B = "\033[1m"
D = "\033[2m"

_NAMED = [
    ("black",          30), ("red",            31), ("green",          32),
    ("yellow",         33), ("blue",            34), ("magenta",        35),
    ("cyan",           36), ("white",           37), ("bright_black",   90),
    ("bright_red",     91), ("bright_green",    92), ("bright_yellow",  93),
    ("bright_blue",    94), ("bright_magenta",  95), ("bright_cyan",    96),
    ("bright_white",   97),
]
_NAME_MAP = {name: code for name, code in _NAMED}


def _ansi(name_or_code):
    if name_or_code in _NAME_MAP:
        return f"\033[{_NAME_MAP[name_or_code]}m"
    try:
        return f"\033[{int(name_or_code)}m"
    except (ValueError, TypeError):
        return ""


def _swatch(color):
    return f"{_ansi(color)}██{R}"


_ANSI_RE = re.compile(r'\033\[[^m]*m')


def _preview(choices, warn_enabled=True):
    sess_col = _ansi(choices.get("CLAUDE_COLOR_SESSION", "cyan"))
    week_col = _ansi(choices.get("CLAUDE_COLOR_WEEK",    "magenta"))
    ok_col   = _ansi(choices.get("CLAUDE_COLOR_OK",      "green"))   if warn_enabled else sess_col
    warn_col = _ansi(choices.get("CLAUDE_COLOR_WARN",    "yellow"))  if warn_enabled else week_col
    crit_col = _ansi(choices.get("CLAUDE_COLOR_CRIT",    "red"))     if warn_enabled else week_col

    W = 40
    bar_w = W - 2

    def bar(ratio, section_col):
        f = int(ratio * bar_w)
        if warn_enabled:
            bar_col = section_col if ratio < 0.75 else (warn_col if ratio < 0.90 else crit_col)
        else:
            bar_col = section_col
        return f"{bar_col}{'█' * f}{R}{D}{'░' * (bar_w - f)}{R}"

    def vlen(s): return len(_ANSI_RE.sub('', s))
    def row(s=""):
        pad = " " * max(0, W - vlen(s))
        print(f"  │ {s}{pad} │")

    print(f"\n  ╭{'─' * (W + 2)}╮")
    row(f"  {D}Preview{R}")
    row()
    row(f"  {sess_col}{B}Session{R}  {D}resets in 2h 14m{R}")
    row(f"  {bar(0.36, sess_col)}")
    row(f"  {B}2.72M{R} / 7.63M  (36%)")
    row(f"  {ok_col}4.91M remaining{R}")
    row(f"  {D}42 msgs  ≈ $1.23{R}")
    row()
    row(f"  {week_col}{B}Week{R}  {D}resets Tue 05/26 15:00{R}")
    row(f"  {bar(0.92, week_col)}")
    row(f"  {B}24.18M{R} / 26.23M  (92%)")
    row(f"  {crit_col}2.05M remaining{R}")
    row(f"  {D}187 msgs  ≈ $5.67{R}")
    row()
    print(f"  ╰{'─' * (W + 2)}╯")


def _pick_color(role_label, current):
    per_row = 4
    print(f"\n  {B}{role_label}{R}  current: {_swatch(current)} {current}\n")
    for i, (name, code) in enumerate(_NAMED):
        num = str(i + 1).rjust(2)
        swatch = f"\033[{code}m██{R}"
        entry = f"  {D}{num}{R}) {swatch} {name:<16}"
        print(entry, end="")
        if (i + 1) % per_row == 0:
            print()
    print("\n")
    while True:
        try:
            raw = input(f"  Enter name or number [{current}]: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            return None
        if not raw:
            return current
        if raw in _NAME_MAP:
            return raw
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(_NAMED):
                return _NAMED[idx][0]
        except ValueError:
            pass
        print("  Invalid — enter a name or number 1–16.")


_ROLES_BASE = [
    ("CLAUDE_COLOR_SESSION", "Session section", "cyan"),
    ("CLAUDE_COLOR_WEEK",    "Week section",    "magenta"),
]
_ROLES_WARN = [
    ("CLAUDE_COLOR_OK",   "OK / remaining",  "green"),
    ("CLAUDE_COLOR_WARN", "Warn bar (≥75%)", "yellow"),
    ("CLAUDE_COLOR_CRIT", "Crit bar (≥90%)", "red"),
]


def run():
    """Run color picker interactively. Returns dict of {env_var: value} or None if aborted."""
    print("\nClaude Tokens — Color Picker\n")

    # Ask about warning colors
    current_warn = os.environ.get("CLAUDE_WARN_COLORS", "1").strip() not in ("0", "false", "no", "off")
    default_label = "Y/n" if current_warn else "y/N"
    try:
        raw = input(f"  Enable warning colors (bar/remaining change at 75%/90%)? [{default_label}]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        return None
    if raw in ("y", "yes"):
        warn_enabled = True
    elif raw in ("n", "no"):
        warn_enabled = False
    else:
        warn_enabled = current_warn

    roles = _ROLES_BASE + (_ROLES_WARN if warn_enabled else [])
    choices = {"CLAUDE_WARN_COLORS": "1" if warn_enabled else "0"}

    for env_var, label, default in roles:
        current = os.environ.get(env_var, default)
        result = _pick_color(label, current)
        if result is None:
            print("\nCancelled.")
            input("\nPress Enter to return...")
            return None
        choices[env_var] = result
        _preview(choices, warn_enabled)

    # Collect non-default values to save
    all_roles = _ROLES_BASE + _ROLES_WARN
    saves = {e: choices[e] for e, _, d in all_roles if e in choices and choices[e] != d}
    if warn_enabled != current_warn:
        saves["CLAUDE_WARN_COLORS"] = choices["CLAUDE_WARN_COLORS"]
    if saves:
        offer_save(saves)
    else:
        print("\n  (all defaults — nothing to save)")

    input("\nPress Enter to return to monitor...")
    return choices


def main():
    """Standalone entry point."""
    run()


if __name__ == "__main__":
    main()
