#!/usr/bin/env python3
"""Calibrate CLAUDE_SESSION_LIMIT and CLAUDE_WEEKLY_LIMIT from claude.ai percentages."""

import json, os, statistics
from datetime import datetime
from claude_tokens.__main__ import (
    collect, WEIGHT_CACHE_READ_SESSION, WEIGHT_CACHE_READ_WEEKLY, PRICING_MODEL,
)
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
            if 0 < v <= 100:
                return v / 100
        except ValueError:
            pass
        print("  Enter a number between 1 and 100.")


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
    sess, week, _ = collect()

    # x = cost-weighted non-cache-read tokens, y = cost-weighted cache reads
    # (see _rec_units). The learned weight scales y, exactly as before.
    sess_x = sess["x"]
    sess_y = sess["y"]
    sess_w = sess_x + round(sess_y * WEIGHT_CACHE_READ_SESSION)

    week_x = week["x"]
    week_y = week["y"]
    week_w = week_x + round(week_y * WEIGHT_CACHE_READ_WEEKLY)

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

    week_limit = round(week_w / week_pct)

    # Load persistent history
    history = _load_history()

    # Learn from history + this point to determine final weight before computing limit
    entry_draft = {
        "ts":         datetime.now().isoformat(),
        "sess_x":     sess_x, "sess_y":   sess_y, "sess_pct": sess_pct,
        "week_x":     week_x, "week_y":   week_y, "week_pct": week_pct,
    }
    all_history = history + [{**entry_draft, "sess_limit": 0, "week_limit": 0}]
    w_learned, n_pairs = _learn_weight(all_history)
    n_pts = len(all_history)

    # Determine the weight that will be in effect after saving
    final_w = WEIGHT_CACHE_READ_SESSION
    weight_changed = False
    if w_learned is not None and n_pairs >= 1 and abs(w_learned - WEIGHT_CACHE_READ_SESSION) >= 0.005:
        weight_changed = True
        final_w = w_learned

    # Limit is always anchored to the user's entered % using the final weight.
    # This guarantees the TUI shows exactly what the user typed.
    sess_limit = round((sess_x + round(sess_y * final_w)) / sess_pct)

    sess_check = (sess_x + round(sess_y * final_w)) / sess_limit * 100
    week_check = week_w / week_limit * 100
    print(f"\n  Round-trip check (TUI will display these):")
    print(f"    Session: entered {sess_pct*100:.0f}% → will show {sess_check:.1f}%")
    print(f"    Weekly:  entered {week_pct*100:.0f}% → will show {week_check:.1f}%")

    # Drift vs most recent calibration
    if history:
        _show_drift(history[-1], sess_limit, week_limit)

    # Build final history entry
    entry = {**entry_draft, "sess_limit": sess_limit, "week_limit": week_limit}
    all_history[-1] = entry

    saves = {
        "CLAUDE_SESSION_LIMIT": str(sess_limit),
        "CLAUDE_WEEKLY_LIMIT":  str(week_limit),
        "CLAUDE_PRICING_MODEL": PRICING_MODEL,
    }

    if w_learned is not None and n_pairs >= 1:
        print(f"\n  Historical weight estimate — {n_pts} calibrations, {n_pairs} pairs:")
        print(f"    Learned CLAUDE_WEIGHT_CACHE_READ_SESSION = {w_learned:.4f}")
        if weight_changed:
            saves["CLAUDE_WEIGHT_CACHE_READ_SESSION"] = f"{w_learned:.4f}"
            os.environ["CLAUDE_WEIGHT_CACHE_READ_SESSION"] = f"{w_learned:.4f}"
            print(f"    (was: {WEIGHT_CACHE_READ_SESSION:.4f}, limit adjusted to keep {sess_pct*100:.0f}%)")
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
