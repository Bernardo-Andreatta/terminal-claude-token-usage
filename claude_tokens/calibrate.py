#!/usr/bin/env python3
"""Calibrate CLAUDE_SESSION_LIMIT and CLAUDE_WEEKLY_LIMIT from claude.ai percentages."""

import sys
from claude_tokens.__main__ import collect


def ask_pct(label):
    while True:
        raw = input(f"  {label} usage % shown on claude.ai: ").strip().rstrip("%")
        try:
            v = float(raw)
            if 0 < v < 100:
                return v / 100
        except ValueError:
            pass
        print("  Enter a number between 1 and 99.")


def fmt(n):
    if n >= 1_000_000: return f"{n/1_000_000:.2f}M"
    if n >= 1_000:     return f"{n/1_000:.1f}k"
    return str(n)


def run():
    """Run calibration interactively. Returns (sess_limit, week_limit) or None if aborted."""
    print("\nClaude Tokens — Calibration")
    print("Open claude.ai → Settings → Usage and read the percentages.\n")

    print("Collecting current token counts...")
    sess, week, _, _ = collect()

    sess_weighted = sess["input"] + sess["output"] + sess["cw"] + int(sess["cr"] * 0.1)
    week_weighted = week["input"] + week["output"] + week["cw"]

    print(f"  Session tokens (weighted): {fmt(sess_weighted)}")
    print(f"  Weekly  tokens:            {fmt(week_weighted)}\n")

    if sess_weighted == 0 or week_weighted == 0:
        print("No token data found. Use Claude Code first, then re-run.")
        input("\nPress Enter to return...")
        return None

    try:
        sess_pct = ask_pct("Session")
        week_pct = ask_pct("Weekly")
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        input("\nPress Enter to return...")
        return None

    sess_limit = round(sess_weighted / sess_pct)
    week_limit = round(week_weighted / week_pct)

    print(f"\nCalculated limits:")
    print(f"  CLAUDE_SESSION_LIMIT = {sess_limit:,}  ({fmt(sess_limit)})")
    print(f"  CLAUDE_WEEKLY_LIMIT  = {week_limit:,}  ({fmt(week_limit)})")
    print(f"\nTo save permanently, add to ~/.zshrc:")
    print(f"  export CLAUDE_SESSION_LIMIT={sess_limit}")
    print(f"  export CLAUDE_WEEKLY_LIMIT={week_limit}")

    input("\nPress Enter to return to monitor...")
    return sess_limit, week_limit


def main():
    """Standalone entry point."""
    result = run()
    if result:
        sl, wl = result
        print(f"\nRun 'source ~/.zshrc' after updating env vars.")


if __name__ == "__main__":
    main()
