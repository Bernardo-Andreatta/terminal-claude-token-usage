# terminal-claude-token-usage

Live terminal widget showing Claude Code token consumption for the current session and weekly period, with cost estimates and progress bars.

```
  ~ estimates only · Anthropic usage API is private
╭──────────────────────────────────────────╮
│   Tue 2026-05-20  14:32:01 Claude Tokens │
│                                          │
│   Session  resets in 2h 14m             │
│   ████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░  │
│   2.72M / 7.63M  (36%)                  │
│   4.91M remaining                        │
│   42 msgs  ≈ $1.23                       │
│                                          │
│   Week  resets Tue 05/26 12:00           │
│   ████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  │
│   6.78M / 26.23M  (26%)                 │
│   19.45M remaining                       │
│   187 msgs  ≈ $5.67                      │
│                                          │
╰──────────────────────────────────────────╯
  refresh 15s · q quit · r refresh · c calibrate · t colors
```

## Install

```bash
pipx install git+https://github.com/BernardoAndreatta/terminal-claude-token-usage.git
```

Or from a local clone:

```bash
pipx install .
```

> `pipx` isolates the install in its own virtualenv — no system Python conflicts.
> Install pipx via `brew install pipx` (macOS) or `pip install pipx`.

## Configuration

Settings are saved to `~/.claude/claude-tokens.conf` — the calibration wizard and color picker both offer to save there automatically. No shell editing required.

You can also set any value as an env var (env vars override the config file):

```bash
# ~/.claude/claude-tokens.conf  (or export in ~/.zshrc)
CLAUDE_SESSION_LIMIT=7631489
CLAUDE_WEEKLY_LIMIT=26230769
CLAUDE_REFRESH=15
```

### Manual config (env vars in `~/.zshrc`, override config file):

```bash
export CLAUDE_SESSION_LIMIT=7631489   # session window limit
export CLAUDE_WEEKLY_LIMIT=26230769   # weekly limit (resets Tue 15:00 UTC)
export CLAUDE_REFRESH=15              # refresh interval in seconds
```

### Calibrating limits

Press `c` in the TUI (or run `claude-tokens-calibrate` standalone) while claude.ai shows your current usage percentages. The tool reads your current token counts, prompts for the percentages shown on claude.ai → Settings → Usage, and calculates limits automatically.

```
  Session usage % shown on claude.ai: 36
  Weekly  usage % shown on claude.ai: 26

  Round-trip check (TUI will display these):
    Session: entered 36% → will show 36.0%
    Weekly:  entered 26% → will show 26.0%

  CLAUDE_SESSION_LIMIT = 7,550,583  (7.55M)
  CLAUDE_WEEKLY_LIMIT  = 26,076,923  (26.08M)
```

Limits apply immediately in the running TUI. The wizard then prompts to save to `~/.claude/claude-tokens.conf`.

### Colors

Press `t` in the TUI (or run `claude-tokens-colors` standalone) to open the interactive color picker:

1. Choose whether warning colors are enabled — when on, the bar and "remaining" indicator shift to yellow at 75% usage and red at 90%.
2. For each color role, a numbered swatch list is shown (16 options). Pick by name (`cyan`) or number (`1`–`16`).
3. A live preview of the full widget updates after each pick.
4. Non-default choices are offered for save to `~/.claude/claude-tokens.conf`.

Color roles can also be set directly as env vars:

```bash
export CLAUDE_COLOR_SESSION=cyan      # session section (default: cyan)
export CLAUDE_COLOR_WEEK=magenta      # week section (default: magenta)
export CLAUDE_COLOR_OK=green          # remaining indicator, low usage (default: green)
export CLAUDE_COLOR_WARN=yellow       # bar/remaining at 75%+ usage (default: yellow)
export CLAUDE_COLOR_CRIT=red          # bar/remaining at 90%+ usage (default: red)
```

Accepts color names (`cyan`, `magenta`, `green`, `yellow`, `red`, `blue`, `white`, `bright_cyan`, etc.) or raw ANSI codes (`36`, `35`, `92`, …).

### Cache read weight

Session and weekly quotas appear to use different cache-read accounting. Session counts cache reads at ~10% weight; weekly ignores them entirely:

```bash
export CLAUDE_WEIGHT_CACHE_READ_SESSION=0.1   # default
export CLAUDE_WEIGHT_CACHE_READ_WEEKLY=0.0    # default
```

If your percentage drifts, recalibrate first. If drift persists, the calibration wizard will suggest an adjusted weight after two calibrations.

### Pricing (per 1M tokens, defaults match claude-sonnet-4-6)

```bash
export CLAUDE_PRICE_INPUT=3.00
export CLAUDE_PRICE_OUTPUT=15.00
export CLAUDE_PRICE_CACHE_WRITE=3.75
export CLAUDE_PRICE_CACHE_READ=0.30
```

## Usage

```bash
claude-tokens            # interactive TUI
claude-tokens-calibrate  # standalone calibration wizard
claude-tokens-colors     # standalone color picker
python -m claude_tokens  # same as claude-tokens, via module
```

Keys: `q` quit · `r` force refresh · `c` calibrate limits · `t` pick colors interactively

## How it works

Reads `~/.claude/projects/**/*.jsonl` — the JSONL logs Claude Code writes per conversation. Aggregates `usage` fields from API response records.

**Session window:** detected by simulating 5-hour windows through the last 12 hours of activity. A new session opens whenever an event arrives after the previous 5-hour window has closed — matching claude.ai's fixed session model.

**Weekly window:** resets Tuesday 15:00 UTC (matching claude.ai's reset schedule).
