#!/usr/bin/env python3
"""Claude Code live token tracker — q to quit, r to refresh now."""

import json, os, re, glob, sys, time, signal
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from claude_tokens.config import load as _load_config, is_first_run, mark_onboarded

_load_config()  # populate os.environ from config file before reading constants

PROJECTS_DIR  = os.path.expanduser("~/.claude/projects")
REFRESH_SECS  = int(os.environ.get("CLAUDE_REFRESH", "15"))

limits = {
    "session": int(os.environ.get("CLAUDE_SESSION_LIMIT", "0")),
    "weekly":  int(os.environ.get("CLAUDE_WEEKLY_LIMIT",  "0")),
}

# Bumped when the quota math changes in a way that invalidates saved limits/weights.
# Calibration writes the current marker; a mismatch nudges the user to recalibrate.
PRICING_MODEL = "v2-cost"

def _needs_recalibration() -> bool:
    """True for users whose saved limits/weights predate the cost-weighted model."""
    if is_first_run():                                  # onboarding handles new users
        return False
    if os.environ.get("CLAUDE_PRICING_MODEL") == PRICING_MODEL:
        return False
    return bool(limits["session"] or limits["weekly"]
                or "CLAUDE_WEIGHT_CACHE_READ_SESSION" in os.environ)

LEGACY_CALIBRATION = _needs_recalibration()

def _envf(name, default):
    try:    return float(os.environ.get(name, default))
    except (TypeError, ValueError): return float(default)

# ---------------------------------------------------------------------------
# Pricing & quota weighting
# ---------------------------------------------------------------------------
# Claude Code logs the real model and the cache-TTL split per message, so usage
# is priced per model and per cache tier instead of one flat rate.
#
#   input  $/Mtok, output $/Mtok   (current published rates)
PRICING = {
    "opus":   (5.00, 25.00),
    "sonnet": (3.00, 15.00),
    "haiku":  (1.00,  5.00),
    "fable":  (10.00, 50.00),
    "mythos": (10.00, 50.00),
}
PRICING_DEFAULT = "sonnet"   # fallback when a record's model is unrecognised

def _model_key(model: str) -> str:
    m = (model or "").lower()
    for k in ("opus", "haiku", "fable", "mythos", "sonnet"):
        if k in m:
            return k
    return PRICING_DEFAULT

# Cache pricing is a fixed multiple of a model's input price (same ratio every model):
#   5-minute cache write = 1.25x,  1-hour cache write = 2x,  cache read = 0.1x.
CACHE_WRITE_5M_MULT = _envf("CLAUDE_CACHE_WRITE_5M_MULT", "1.25")
CACHE_WRITE_1H_MULT = _envf("CLAUDE_CACHE_WRITE_1H_MULT", "2.00")
CACHE_READ_MULT     = _envf("CLAUDE_CACHE_READ_MULT",     "0.10")

# Quota is an opaque weighted token count, not raw tokens. The non-cache-read
# portion is weighted by true cost (output ~5x input, 1h cache-write 2x input,
# per model), expressed in BASE_PRICE-normalised "input-equivalent tokens" so the
# displayed magnitude stays token-like. Cache reads are the one component the
# quota discounts below cost — and by different amounts for session vs weekly —
# so their weight stays calibratable.
BASE_PRICE = _envf("CLAUDE_BASE_PRICE", "3.00")  # $/Mtok used to normalise weighted tokens

# Dimensionless cache-read weight (1.0 = counts at full cost, 0.0 = ignored).
# Defaults are principled starting points; calibration learns the real values.
WEIGHT_CACHE_READ_SESSION = _envf("CLAUDE_WEIGHT_CACHE_READ_SESSION", "1.0")
WEIGHT_CACHE_READ_WEEKLY  = _envf("CLAUDE_WEIGHT_CACHE_READ_WEEKLY",  "0.0")


def _rec_units(mk, inp, out, cw5, cw1, cr):
    """Return (x, y): cost-equivalent tokens for the non-cache-read part (x) and
    the cache-read part (y), normalised to BASE_PRICE input tokens. Quota total
    is then x + w*y; total cost ($) is (x + y) * BASE_PRICE / 1e6."""
    pin, pout = PRICING.get(mk, PRICING[PRICING_DEFAULT])
    x = (inp * pin + out * pout
         + cw5 * pin * CACHE_WRITE_5M_MULT
         + cw1 * pin * CACHE_WRITE_1H_MULT) / BASE_PRICE
    y = (cr * pin * CACHE_READ_MULT) / BASE_PRICE
    return x, y
WEEK_RESET_UTC_HOUR = 15  # Tuesday 15:00 UTC = noon US Eastern (Anthropic's observed reset time)
# Offset applied to computed session start (positive = session started earlier than JSONL shows).
# Useful when sessions are started via claude.ai web before switching to CLI.
SESSION_OFFSET_SECS = int(os.environ.get("CLAUDE_SESSION_OFFSET_SECS", "0"))

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

def cost_usd(x, y):
    """Total cost in USD from cost-equivalent token sums (see _rec_units)."""
    return (x + y) * BASE_PRICE / 1_000_000

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
    """Return cached (dt, msg_id, model_key, inp, out, cw5, cw1, cr) tuples;
    re-reads only if the file changed. Raw token counts are cached (not weighted
    values) so price/weight changes take effect without rescanning."""
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
                # Split cache writes into 5m / 1h tiers (different prices). When the
                # breakdown is absent, fall back to 1h (Claude Code's default tier).
                cc = usage.get("cache_creation")
                if isinstance(cc, dict):
                    cw5 = cc.get("ephemeral_5m_input_tokens", 0)
                    cw1 = cc.get("ephemeral_1h_input_tokens", 0)
                    if cw5 + cw1 == 0 and cw:
                        cw1 = cw
                else:
                    cw5, cw1 = 0, cw
                if inp == out == cw == cr == 0:
                    continue  # synthetic / no-op records carry no usage
                mk = _model_key(msg.get("model"))
                records.append((dt, msg.get("id"), mk, inp, out, cw5, cw1, cr))
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

    # Deduplicate across the whole scan: Claude Code writes the same API response
    # 2-3x, and resumed/branched sessions copy prior records into a new file.
    seen_ids: set = set()
    deduped = []
    for r in all_records:
        mid = r[1]
        if mid is not None:
            if mid in seen_ids:
                continue
            seen_ids.add(mid)
        deduped.append(r)
    all_records = deduped

    recent = [r for r in all_records if r[0] >= cutoff_scan]
    sess_start = _find_session_start(recent, now)
    if SESSION_OFFSET_SECS and sess_start < now:
        sess_start -= timedelta(seconds=SESSION_OFFSET_SECS)

    sess = defaultdict(float)
    week = defaultdict(float)

    def add(bucket, x, y):
        bucket["x"] += x; bucket["y"] += y; bucket["msgs"] += 1

    for dt, _mid, mk, inp, out, cw5, cw1, cr in all_records:
        if dt < cutoff_week:
            continue
        x, y = _rec_units(mk, inp, out, cw5, cw1, cr)
        add(week, x, y)
        if dt >= sess_start:
            add(sess, x, y)

    sess_reset = (sess_start + timedelta(hours=5)).astimezone()
    return sess, week, sess_reset

W = 40
MARGIN = " " * int(os.environ.get("CLAUDE_MARGIN", "2"))

def line(s=""):
    pad = " " * max(0, W - vlen(s))
    print(f"{MARGIN}│ {s}{pad} │", flush=True)

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
        x, y  = data["x"], data["y"]
        total = round(x + cr_weight * y)
        usd   = cost_usd(x, y)
        msgs  = int(data["msgs"])

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
    print(f"{MARGIN}{c('  ~ estimates only · Anthropic usage API is private', D)}", flush=True)
    print(f"{MARGIN}╭{'─' * (W + 2)}╮", flush=True)
    line(c(f"  {now_local.strftime('%a %Y-%m-%d  %H:%M:%S')} Claude Tokens", D))
    line()
    section("Session", sess_sublabel, sess, limits["session"], CY, cr_weight=WEIGHT_CACHE_READ_SESSION)
    line()
    section("Week", f"resets {wend.strftime('%a %m/%d %H:%M')}", week, limits["weekly"], MA, cr_weight=WEIGHT_CACHE_READ_WEEKLY)
    line()
    print(f"{MARGIN}╰{'─' * (W + 2)}╯", flush=True)

    hint = c(f"  refresh {REFRESH_SECS}s · q quit · r refresh · c calibrate · t colors", D)
    if LEGACY_CALIBRATION:
        hint += c("  |  ", D) + c("⚠ pricing model updated — press c to recalibrate", YE)
    elif limits["session"] == 0 or limits["weekly"] == 0:
        hint += c("  |  set CLAUDE_SESSION_LIMIT / CLAUDE_WEEKLY_LIMIT", D)
    print(f"{MARGIN}{hint}", flush=True)

if sys.platform == "win32":
    import msvcrt as _msvcrt

    def setup_terminal():
        return None, None

    def restore_terminal(fd, old):
        pass

    def key_available(fd):
        return _msvcrt.kbhit()

    def _read_key(fd):
        return _msvcrt.getch()

    def _enable_vt():
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            handle = k32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_ulong()
            if k32.GetConsoleMode(handle, ctypes.byref(mode)):
                k32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except Exception:
            pass

else:
    import tty as _tty, termios as _termios, select as _select

    def setup_terminal():
        fd = sys.stdin.fileno()
        old = _termios.tcgetattr(fd)
        _tty.setcbreak(fd)
        return fd, old

    def restore_terminal(fd, old):
        _termios.tcsetattr(fd, _termios.TCSADRAIN, old)

    def key_available(fd):
        r, _, _ = _select.select([fd], [], [], 0)
        return bool(r)

    def _read_key(fd):
        return os.read(fd, 1)

    def _enable_vt():
        pass

def show_onboarding():
    OW = 54  # inner width
    M  = MARGIN

    def row(s=""):
        pad = " " * max(0, OW - vlen(s))
        print(f"{M}│ {s}{pad} │", flush=True)

    def rule():
        row(c("─" * OW, D))

    sys.stdout.write(CLEAR_HOME)
    sys.stdout.flush()

    print(f"{M}╭{'─' * (OW + 2)}╮", flush=True)
    row()
    row(c("  claude-tokens", B) + c("  v1.1.0", D))
    row()
    rule()
    row()
    row(c("  ⚠  Estimates only", B + YE))
    row(c("     Anthropic doesn't expose real quota data.", D))
    row(c("     Numbers come from your local JSONL logs", D))
    row(c("     and may drift from claude.ai by ±5–15%.", D))
    row()
    rule()
    row()
    row(c("  Calibrate for better accuracy", B))
    row()
    row(f"  Press {c(' c ', B)} in the TUI, then enter the")
    row(f"  percentages shown on claude.ai:")
    row()
    row(c("     Settings → Usage  (session % and week %)", D))
    row()
    row("  The tool computes your limits automatically.")
    row(c("  Recalibrate anytime — accuracy improves", D))
    row(c("  after each calibration.", D))
    row()
    rule()
    row()
    row(c("  Press any key to start", D))
    row()
    print(f"{M}╰{'─' * (OW + 2)}╯", flush=True)

    # wait for keypress
    try:
        fd, old = setup_terminal()
        if fd is not None:
            _read_key(fd)
            restore_terminal(fd, old)
        else:
            input()
    except Exception:
        pass

    mark_onboarded()


def main():
    _enable_vt()

    def bye(*_):
        sys.stdout.write(SHOW_CUR)
        sys.stdout.flush()
        sys.exit(0)
    signal.signal(signal.SIGINT, bye)
    try:
        signal.signal(signal.SIGTERM, bye)
    except (OSError, ValueError):
        pass  # SIGTERM not available on all Windows configurations

    sys.stdout.write(HIDE_CUR)
    sys.stdout.flush()
    if is_first_run():
        show_onboarding()

    try:
        fd, old_tty = setup_terminal()
        interactive = True
    except Exception:
        interactive = False
        fd = old_tty = None

    try:
        last_refresh = 0.0
        while True:
            now = time.monotonic()
            force = (now - last_refresh) >= REFRESH_SECS

            if interactive and key_available(fd):
                ch = _read_key(fd)
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
                        global WEIGHT_CACHE_READ_SESSION, LEGACY_CALIBRATION
                        limits["session"], limits["weekly"] = result
                        WEIGHT_CACHE_READ_SESSION = _envf("CLAUDE_WEIGHT_CACHE_READ_SESSION", "1.0")
                        LEGACY_CALIBRATION = False
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
