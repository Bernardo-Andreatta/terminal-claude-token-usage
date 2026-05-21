#!/usr/bin/env python3
"""Claude Code live token tracker — q to quit, r to refresh now."""

import json, os, re, glob, sys, time, signal
from datetime import datetime, timedelta, timezone
from collections import defaultdict

PROJECTS_DIR  = os.path.expanduser("~/.claude/projects")
REFRESH_SECS  = int(os.environ.get("CLAUDE_REFRESH", "15"))

limits = {
    "session": int(os.environ.get("CLAUDE_SESSION_LIMIT", "0")),
    "weekly":  int(os.environ.get("CLAUDE_WEEKLY_LIMIT",  "0")),
}

PRICE_INPUT       = float(os.environ.get("CLAUDE_PRICE_INPUT",       "3.00"))
PRICE_OUTPUT      = float(os.environ.get("CLAUDE_PRICE_OUTPUT",      "15.00"))
PRICE_CACHE_WRITE = float(os.environ.get("CLAUDE_PRICE_CACHE_WRITE", "3.75"))
PRICE_CACHE_READ  = float(os.environ.get("CLAUDE_PRICE_CACHE_READ",  "0.30"))

R  = "\033[0m"
B  = "\033[1m"
D  = "\033[2m"
CY = "\033[36m"
MA = "\033[35m"
YE = "\033[33m"
RE = "\033[31m"
GR = "\033[32m"

CLEAR_HOME = "\033[H\033[J"
HIDE_CUR   = "\033[?25l"
SHOW_CUR   = "\033[?25h"

_ansi = re.compile(r'\033\[[^m]*m')
def vlen(s): return len(_ansi.sub('', s))
def c(s, *codes): return "".join(codes) + s + R

def fmt(n):
    if n >= 1_000_000: return f"{n/1_000_000:.2f}M"
    if n >= 1_000:     return f"{n/1_000:.1f}k"
    return str(n)

def calc_cost(inp, out, cw, cr):
    return (inp * PRICE_INPUT + out * PRICE_OUTPUT +
            cw * PRICE_CACHE_WRITE + cr * PRICE_CACHE_READ) / 1_000_000

def pbar(used, limit, width, col):
    if limit <= 0:
        return c("█" * width, D)
    ratio  = min(used / limit, 1.0)
    filled = int(ratio * width)
    col    = col if ratio < 0.75 else (YE if ratio < 0.90 else RE)
    return c("█" * filled, col) + c("░" * (width - filled), D)

def week_start_utc():
    now = datetime.now(timezone.utc)
    days_since_tue = (now.weekday() - 1) % 7
    reset = (now - timedelta(days=days_since_tue)).replace(
        hour=15, minute=0, second=0, microsecond=0)
    if reset > now:
        reset -= timedelta(days=7)
    return reset

def collect():
    now         = datetime.now(timezone.utc)
    cutoff_week = week_start_utc()
    cutoff_scan = now - timedelta(hours=12)   # scan 12h to detect session boundary
    events: list[tuple[datetime, int, int, int, int]] = []

    for path in glob.glob(os.path.join(PROJECTS_DIR, "**", "*.jsonl"), recursive=True):
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw: continue
                    try: rec = json.loads(raw)
                    except json.JSONDecodeError: continue
                    ts  = rec.get("timestamp")
                    msg = rec.get("message", {})
                    if not isinstance(msg, dict): continue
                    usage = msg.get("usage")
                    if not isinstance(usage, dict) or not ts: continue
                    try:
                        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    except (TypeError, ValueError):
                        try:    dt = datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc)
                        except: continue
                    if dt < cutoff_scan: continue
                    inp = usage.get("input_tokens", 0)
                    out = usage.get("output_tokens", 0)
                    cw  = usage.get("cache_creation_input_tokens", 0)
                    cr  = usage.get("cache_read_input_tokens", 0)
                    events.append((dt, inp, out, cw, cr))
        except (OSError, PermissionError): continue

    events.sort(key=lambda e: e[0])

    # Find session start: largest gap between consecutive events (most likely reset point)
    # Fall back to rolling 5h if no meaningful gap found
    sess_start = now - timedelta(hours=5)
    if len(events) >= 2:
        max_gap = timedelta(minutes=30)   # ignore gaps < 30min
        max_i   = -1
        for i in range(1, len(events)):
            g = events[i][0] - events[i - 1][0]
            if g > max_gap:
                max_gap = g
                max_i   = i
        if max_i != -1:
            sess_start = events[max_i][0]

    sess = defaultdict(int)
    week = defaultdict(int)
    sess_oldest: datetime | None = None

    for path in glob.glob(os.path.join(PROJECTS_DIR, "**", "*.jsonl"), recursive=True):
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw: continue
                    try: rec = json.loads(raw)
                    except json.JSONDecodeError: continue
                    ts  = rec.get("timestamp")
                    msg = rec.get("message", {})
                    if not isinstance(msg, dict): continue
                    usage = msg.get("usage")
                    if not isinstance(usage, dict) or not ts: continue
                    try:
                        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    except (TypeError, ValueError):
                        try:    dt = datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc)
                        except: continue

                    inp = usage.get("input_tokens", 0)
                    out = usage.get("output_tokens", 0)
                    cw  = usage.get("cache_creation_input_tokens", 0)
                    cr  = usage.get("cache_read_input_tokens", 0)

                    if dt >= sess_start:
                        sess["input"]  += inp; sess["output"] += out
                        sess["cw"]     += cw;  sess["cr"]     += cr
                        sess["msgs"]   += 1
                        if sess_oldest is None or dt < sess_oldest:
                            sess_oldest = dt

                    if dt >= cutoff_week:
                        week["input"]  += inp; week["output"] += out
                        week["cw"]     += cw;  week["cr"]     += cr
                        week["msgs"]   += 1
        except (OSError, PermissionError): continue

    sess_reset = (sess_start + timedelta(hours=5)).astimezone()
    return sess, week, sess_oldest, sess_reset

W = 40

def line(s=""):
    pad = " " * max(0, W - vlen(s))
    print(f"│ {s}{pad} │", flush=True)

def render(sess, week, sess_oldest, sess_reset, calib_msg=None):
    wend       = (week_start_utc() + timedelta(days=7)).astimezone()
    now_local  = datetime.now()
    BAR_W      = W - 2

    sess_remaining = sess_reset - datetime.now().astimezone()
    sess_rem_secs  = max(0, int(sess_remaining.total_seconds()))
    sess_rem_h     = sess_rem_secs // 3600
    sess_rem_m     = (sess_rem_secs % 3600) // 60
    sess_sublabel  = f"resets in {sess_rem_h}h {sess_rem_m:02d}m"

    def section(label, sublabel, data, limit, col, cr_weight=0.0):
        inp, out, cw, cr = data["input"], data["output"], data["cw"], data["cr"]
        total = inp + out + cw + int(cr * cr_weight)
        usd   = calc_cost(inp, out, cw, cr)
        msgs  = data["msgs"]

        line(c(f"  {label}", B + col) + c(f"  {sublabel}", D))
        line(f"  {pbar(total, limit, BAR_W, col)}")
        used_s = c(fmt(total), B)
        if limit > 0:
            rem     = max(limit - total, 0)
            pct     = min(total / limit * 100, 100)
            rem_col = GR if rem > limit * 0.25 else (YE if rem > limit * 0.10 else RE)
            line(f"  {used_s} / {fmt(limit)}  ({pct:.0f}%)")
            line(f"  {c(fmt(rem) + ' remaining', rem_col)}")
        else:
            line(f"  {used_s}")
        line(f"  {c(str(msgs) + ' msgs', D)}  {c('≈ $' + f'{usd:.2f}', YE)}")

    print("\n\n", end="", flush=True)
    print(c("  ~ estimates only · Anthropic usage API is private", D), flush=True)
    print(f"╭{'─' * (W + 2)}╮", flush=True)
    line(c(f"  {now_local.strftime('%a %Y-%m-%d  %H:%M:%S')} Claude Tokens", D))
    line()
    section("Session", sess_sublabel, sess, limits["session"], CY, cr_weight=0.1)
    line()
    section("Week", f"resets {wend.strftime('%a %m/%d %H:%M')}", week, limits["weekly"], MA, cr_weight=0.0)
    line()
    print(f"╰{'─' * (W + 2)}╯", flush=True)

    hint = c(f"  refresh {REFRESH_SECS}s · q quit · r refresh · c calibrate", D)
    if limits["session"] == 0 or limits["weekly"] == 0:
        hint += c("  |  set CLAUDE_SESSION_LIMIT / CLAUDE_WEEKLY_LIMIT", D)
    print(hint, flush=True)

    if calib_msg:
        print(c(f"  {calib_msg}", YE), flush=True)

def setup_terminal():
    """Non-blocking single-keypress input."""
    import tty, termios
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    return fd, old

def restore_terminal(fd, old):
    import termios
    termios.tcsetattr(fd, termios.TCSADRAIN, old)

def key_available(fd):
    import select
    r, _, _ = select.select([fd], [], [], 0)
    return bool(r)

def main():
    def bye(*_):
        sys.stdout.write(SHOW_CUR)
        sys.stdout.flush()
        sys.exit(0)
    signal.signal(signal.SIGINT,  bye)
    signal.signal(signal.SIGTERM, bye)

    try:
        fd, old_tty = setup_terminal()
        interactive = True
    except Exception:
        interactive = False
        fd = old_tty = None

    sys.stdout.write(HIDE_CUR)
    sys.stdout.flush()

    try:
        last_refresh = 0.0
        calib_msg    = None
        while True:
            now = time.monotonic()
            force = (now - last_refresh) >= REFRESH_SECS

            if interactive and key_available(fd):
                ch = os.read(fd, 1)
                if ch in (b'q', b'Q'):
                    break
                if ch in (b'r', b'R'):
                    force = True
                if ch in (b'c', b'C'):
                    restore_terminal(fd, old_tty)
                    sys.stdout.write(SHOW_CUR)
                    sys.stdout.flush()
                    from claude_tokens.calibrate import run as calibrate_run
                    result = calibrate_run()
                    if result:
                        limits["session"], limits["weekly"] = result
                        calib_msg = (
                            f"Limits updated. To save permanently: "
                            f"export CLAUDE_SESSION_LIMIT={limits['session']} "
                            f"CLAUDE_WEEKLY_LIMIT={limits['weekly']}"
                        )
                    try:
                        fd, old_tty = setup_terminal()
                    except Exception:
                        pass
                    sys.stdout.write(HIDE_CUR)
                    sys.stdout.flush()
                    force = True

            if force:
                sess, week, sess_oldest, sess_reset = collect()
                sys.stdout.write(CLEAR_HOME)
                sys.stdout.flush()
                render(sess, week, sess_oldest, sess_reset, calib_msg)
                last_refresh = time.monotonic()

            time.sleep(0.1)
    finally:
        if interactive and old_tty is not None:
            restore_terminal(fd, old_tty)
        sys.stdout.write(SHOW_CUR)
        sys.stdout.flush()

if __name__ == "__main__":
    main()
