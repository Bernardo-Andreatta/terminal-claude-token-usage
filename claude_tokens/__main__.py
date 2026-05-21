#!/usr/bin/env python3
"""Claude Code live token tracker — q to quit, r to refresh now."""

import json, os, re, glob, sys, time, signal
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from claude_tokens.config import load as _load_config

_load_config()  # populate os.environ from config file before reading constants

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

# Session and weekly use different cache-read weights — claude.ai appears to count
# cache reads for session quota (~10% weight) but not for weekly quota.
WEIGHT_CACHE_READ_SESSION = float(os.environ.get("CLAUDE_WEIGHT_CACHE_READ_SESSION", "0.1"))
WEIGHT_CACHE_READ_WEEKLY  = float(os.environ.get("CLAUDE_WEIGHT_CACHE_READ_WEEKLY",  "0.0"))
WEEK_RESET_UTC_HOUR = 15  # Tuesday 15:00 UTC = noon US Eastern (Anthropic's observed reset time)

R  = "\033[0m"
B  = "\033[1m"
D  = "\033[2m"

_NAMED = {
    "black": 30, "red": 31, "green": 32, "yellow": 33,
    "blue": 34, "magenta": 35, "cyan": 36, "white": 37,
    "bright_black": 90, "bright_red": 91, "bright_green": 92,
    "bright_yellow": 93, "bright_blue": 94, "bright_magenta": 95,
    "bright_cyan": 96, "bright_white": 97,
}

def _col(env_var, default_code):
    v = os.environ.get(env_var, "").strip().lower()
    if not v:
        return f"\033[{default_code}m"
    if v in _NAMED:
        return f"\033[{_NAMED[v]}m"
    try:
        return f"\033[{int(v)}m"
    except ValueError:
        return f"\033[{default_code}m"

CY = _col("CLAUDE_COLOR_SESSION", 36)
MA = _col("CLAUDE_COLOR_WEEK",    35)
GR = _col("CLAUDE_COLOR_OK",      32)
YE = _col("CLAUDE_COLOR_WARN",    33)
RE = _col("CLAUDE_COLOR_CRIT",    31)

WARN_COLORS = os.environ.get("CLAUDE_WARN_COLORS", "1").strip() not in ("0", "false", "no", "off")

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
    if WARN_COLORS:
        col = col if ratio < 0.75 else (YE if ratio < 0.90 else RE)
    return c("█" * filled, col) + c("░" * (width - filled), D)

def week_start_utc():
    now = datetime.now(timezone.utc)
    days_since_tue = (now.weekday() - 1) % 7
    reset = (now - timedelta(days=days_since_tue)).replace(
        hour=WEEK_RESET_UTC_HOUR, minute=0, second=0, microsecond=0)
    if reset > now:
        reset -= timedelta(days=7)
    return reset

_file_cache: dict[str, tuple] = {}

def _read_file_records(path: str) -> list:
    """Return cached (dt, inp, out, cw, cr) tuples; re-reads only if file changed."""
    try:
        st = os.stat(path)
        cached = _file_cache.get(path)
        if cached and cached[0] == st.st_mtime and cached[1] == st.st_size:
            return cached[2]
        records = []
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
                records.append((dt, inp, out, cw, cr))
        _file_cache[path] = (st.st_mtime, st.st_size, records)
        return records
    except (OSError, PermissionError):
        return []


def _find_session_start(events: list, now: datetime) -> datetime:
    """Simulate 5h session windows through sorted events to find current session start."""
    if not events:
        return now
    SESSION = timedelta(hours=5)
    if (now - events[-1][0]) >= SESSION:
        return now
    window_start = events[0][0]
    for evt in events[1:]:
        if evt[0] > window_start + SESSION:
            window_start = evt[0]
    if now - window_start >= SESSION:
        return now
    return window_start


def collect():
    now         = datetime.now(timezone.utc)
    cutoff_week = week_start_utc()
    cutoff_scan = now - timedelta(hours=12)

    all_records: list = []
    for path in glob.glob(os.path.join(PROJECTS_DIR, "**", "*.jsonl"), recursive=True):
        all_records.extend(_read_file_records(path))
    all_records.sort(key=lambda e: e[0])

    recent = [r for r in all_records if r[0] >= cutoff_scan]
    sess_start = _find_session_start(recent, now)

    sess = defaultdict(int)
    week = defaultdict(int)

    for dt, inp, out, cw, cr in all_records:
        if dt < cutoff_week:
            continue
        week["input"]  += inp; week["output"] += out
        week["cw"]     += cw;  week["cr"]     += cr
        week["msgs"]   += 1
        if dt >= sess_start:
            sess["input"]  += inp; sess["output"] += out
            sess["cw"]     += cw;  sess["cr"]     += cr
            sess["msgs"]   += 1

    sess_reset = (sess_start + timedelta(hours=5)).astimezone()
    return sess, week, sess_reset

W = 40

def line(s=""):
    pad = " " * max(0, W - vlen(s))
    print(f"│ {s}{pad} │", flush=True)

def render(sess, week, sess_reset):
    wend       = (week_start_utc() + timedelta(days=7)).astimezone()
    now_local  = datetime.now()
    BAR_W      = W - 2

    sess_remaining = sess_reset - datetime.now().astimezone()
    sess_rem_secs  = max(0, int(sess_remaining.total_seconds()))
    if sess["msgs"] == 0:
        sess_sublabel = "no active session"
    else:
        sess_rem_h    = sess_rem_secs // 3600
        sess_rem_m    = (sess_rem_secs % 3600) // 60
        sess_sublabel = f"resets in {sess_rem_h}h {sess_rem_m:02d}m"

    def section(label, sublabel, data, limit, col, cr_weight=0.0):
        inp, out, cw, cr = data["input"], data["output"], data["cw"], data["cr"]
        total = inp + out + cw + round(cr * cr_weight)
        usd   = calc_cost(inp, out, cw, cr)
        msgs  = data["msgs"]

        line(c(f"  {label}", B + col) + c(f"  {sublabel}", D))
        line(f"  {pbar(total, limit, BAR_W, col)}")
        used_s = c(fmt(total), B)
        if limit > 0:
            rem     = max(limit - total, 0)
            pct     = min(total / limit * 100, 100)
            if WARN_COLORS:
                rem_col = GR if rem > limit * 0.25 else (YE if rem > limit * 0.10 else RE)
            else:
                rem_col = col
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
    section("Session", sess_sublabel, sess, limits["session"], CY, cr_weight=WEIGHT_CACHE_READ_SESSION)
    line()
    section("Week", f"resets {wend.strftime('%a %m/%d %H:%M')}", week, limits["weekly"], MA, cr_weight=WEIGHT_CACHE_READ_WEEKLY)
    line()
    print(f"╰{'─' * (W + 2)}╯", flush=True)

    hint = c(f"  refresh {REFRESH_SECS}s · q quit · r refresh · c calibrate · t colors", D)
    if limits["session"] == 0 or limits["weekly"] == 0:
        hint += c("  |  set CLAUDE_SESSION_LIMIT / CLAUDE_WEEKLY_LIMIT", D)
    print(hint, flush=True)

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
                        global WEIGHT_CACHE_READ_SESSION
                        limits["session"], limits["weekly"] = result
                        WEIGHT_CACHE_READ_SESSION = float(os.environ.get("CLAUDE_WEIGHT_CACHE_READ_SESSION", "0.1"))
                    try:
                        fd, old_tty = setup_terminal()
                    except Exception:
                        pass
                    sys.stdout.write(HIDE_CUR)
                    sys.stdout.flush()
                    force = True
                if ch in (b't', b'T'):
                    restore_terminal(fd, old_tty)
                    sys.stdout.write(SHOW_CUR)
                    sys.stdout.flush()
                    from claude_tokens.colors import run as colors_run, _ansi
                    result = colors_run()
                    if result:
                        global CY, MA, GR, YE, RE, WARN_COLORS
                        CY = _ansi(result.get("CLAUDE_COLOR_SESSION", "cyan"))
                        MA = _ansi(result.get("CLAUDE_COLOR_WEEK",    "magenta"))
                        GR = _ansi(result.get("CLAUDE_COLOR_OK",      "green"))
                        YE = _ansi(result.get("CLAUDE_COLOR_WARN",    "yellow"))
                        RE = _ansi(result.get("CLAUDE_COLOR_CRIT",    "red"))
                        WARN_COLORS = result.get("CLAUDE_WARN_COLORS", "1") not in ("0",)
                    try:
                        fd, old_tty = setup_terminal()
                    except Exception:
                        pass
                    sys.stdout.write(HIDE_CUR)
                    sys.stdout.flush()
                    force = True

            if force:
                sess, week, sess_reset = collect()
                sys.stdout.write(CLEAR_HOME)
                sys.stdout.flush()
                render(sess, week, sess_reset)
                last_refresh = time.monotonic()

            time.sleep(0.1)
    finally:
        if interactive and old_tty is not None:
            restore_terminal(fd, old_tty)
        sys.stdout.write(SHOW_CUR)
        sys.stdout.flush()

if __name__ == "__main__":
    main()
