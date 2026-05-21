#!/usr/bin/env python3
"""Calibrate CLAUDE_SESSION_LIMIT and CLAUDE_WEEKLY_LIMIT from claude.ai percentages."""

import json, os, statistics
from datetime import datetime
from claude_tokens.__main__ import collect, WEIGHT_CACHE_READ_SESSION, WEIGHT_CACHE_READ_WEEKLY
from claude_tokens.config import offer_save

CALIB_PATH  = os.path.expanduser("~/.claude/claude-tokens-calibrations.json")
MAX_HISTORY = 60


# ---------------------------------------------------------------------------
# History persistence
# ---------------------------------------------------------------------------

def _load_history():
    if not os.path.exists(CALIB_PATH):
        return []
    try:
        with open(CALIB_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError, ValueError):
        return []


def _save_history(history):
    try:
        with open(CALIB_PATH, "w", encoding="utf-8") as f:
            json.dump(history[-MAX_HISTORY:], f, indent=2)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Weight learning
# ---------------------------------------------------------------------------

def _implied_weight(x1, y1, p1, x2, y2, p2):
    """Solve for w given two calibration points: x + w*y = p * L_true."""
    denom = p2 * y1 - p1 * y2
    if abs(denom) < 1:
        return None
    w = (p1 * x2 - p2 * x1) / denom
    return w if 0.0 <= w <= 2.0 else None


def _learn_weight(history):
    """Pairwise median w from all combinations. Returns (w, n_pairs)."""
    estimates = []
    for i in range(len(history)):
        for j in range(i + 1, len(history)):
            a, b = history[i], history[j]
            w = _implied_weight(a["sess_x"], a["sess_y"], a["sess_pct"],
                                b["sess_x"], b["sess_y"], b["sess_pct"])
            if w is not None:
                estimates.append(w)
    if not estimates:
        return None, 0
    return statistics.median(estimates), len(estimates)



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fmt(n):
    if n >= 1_000_000: return f"{n/1_000_000:.2f}M"
    if n >= 1_000:     return f"{n/1_000:.1f}k"
    return str(n)


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


def _show_drift(prev, sess_limit, week_limit):
    try:
        elapsed = datetime.now() - datetime.fromisoformat(prev["ts"])
    except (KeyError, ValueError):
        return
    mins  = int(elapsed.total_seconds() / 60)
    label = f"{mins}m" if mins < 60 else f"{mins // 60}h {mins % 60:02d}m"
    sess_d = (sess_limit - prev["sess_limit"]) / prev["sess_limit"] * 100
    week_d = (week_limit - prev["week_limit"]) / prev["week_limit"] * 100
    print(f"\n  Drift since last calibration ({label} ago):")
    print(f"    Session limit: {fmt(prev['sess_limit'])} → {fmt(sess_limit)}  ({sess_d:+.1f}%)")
    print(f"    Weekly  limit: {fmt(prev['week_limit'])} → {fmt(week_limit)}  ({week_d:+.1f}%)")


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------

def run():
    """Run calibration interactively. Returns (sess_limit, week_limit) or None."""
    print("\nClaude Tokens — Calibration")
    print("Open claude.ai → Settings → Usage and read the percentages.\n")

    print("Collecting current token counts...")
    sess, week, _, _ = collect()

    sess_x = sess["input"] + sess["output"] + sess["cw"]
    sess_y = sess["cr"]
    sess_w = sess_x + int(sess_y * WEIGHT_CACHE_READ_SESSION)

    week_x = week["input"] + week["output"] + week["cw"]
    week_y = week["cr"]
    week_w = week_x + int(week_y * WEIGHT_CACHE_READ_WEEKLY)

    print(f"  Session tokens: {fmt(sess_w)}")
    print(f"  Weekly  tokens: {fmt(week_w)}\n")

    if sess_w == 0 or week_w == 0:
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

    # Single-point estimates
    sess_limit = round(sess_w / sess_pct)
    week_limit = round(week_w / week_pct)

    # Load persistent history
    history = _load_history()

    # Drift vs most recent calibration
    if history:
        _show_drift(history[-1], sess_limit, week_limit)

    # Build new entry and merge into history
    entry = {
        "ts":         datetime.now().isoformat(),
        "sess_x":     sess_x, "sess_y":   sess_y, "sess_pct": sess_pct,
        "sess_limit": sess_limit,
        "week_x":     week_x, "week_y":   week_y, "week_pct": week_pct,
        "week_limit": week_limit,
    }
    all_history = history + [entry]

    # Learn from all historical pairs
    w_learned, n_pairs = _learn_weight(all_history)
    n_pts = len(all_history)

    # Single-point limits are ALWAYS what gets returned and saved —
    # they're computed with the same weight the TUI uses, so they're always consistent.
    saves = {
        "CLAUDE_SESSION_LIMIT": str(sess_limit),
        "CLAUDE_WEEKLY_LIMIT":  str(week_limit),
    }

    if w_learned is not None and n_pairs >= 1:
        print(f"\n  Historical weight estimate — {n_pts} calibrations, {n_pairs} pairs:")
        print(f"    Learned CLAUDE_WEIGHT_CACHE_READ_SESSION = {w_learned:.4f}")
        current_w = WEIGHT_CACHE_READ_SESSION
        if abs(w_learned - current_w) >= 0.005:
            # Recompute sess_limit using w_learned so it stays consistent with
            # the new weight on restart — old limit + new weight = wrong percentage.
            sess_limit_w = round((sess_x + w_learned * sess_y) / sess_pct)
            print(f"    (current: {current_w})")
            print(f"    Saving weight + consistent limit: {fmt(sess_limit_w)}")
            saves["CLAUDE_WEIGHT_CACHE_READ_SESSION"] = f"{w_learned:.4f}"
            saves["CLAUDE_SESSION_LIMIT"] = str(sess_limit_w)
            sess_limit = sess_limit_w
        else:
            print(f"    Weight well-calibrated.")

    print(f"\n  Limits:")
    print(f"    CLAUDE_SESSION_LIMIT = {sess_limit:,}  ({fmt(sess_limit)})")
    print(f"    CLAUDE_WEEKLY_LIMIT  = {week_limit:,}  ({fmt(week_limit)})")

    offer_save(saves)
    _save_history(all_history)

    input("\nPress Enter to return to monitor...")
    return sess_limit, week_limit


def main():
    """Standalone entry point."""
    run()


if __name__ == "__main__":
    main()
