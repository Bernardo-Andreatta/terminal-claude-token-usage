# claude-tokens

Live terminal TUI tracking Claude Code token consumption — session and weekly windows, cost estimates, progress bars, calibration wizard, and color picker. Cross-platform: Mac, Linux, Windows.

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

### Mac — Homebrew

```bash
brew tap Bernardo-Andreatta/tap
brew install claude-tokens
```

### Windows — Scoop

```bash
scoop bucket add bernardo https://github.com/Bernardo-Andreatta/scoop-bucket
scoop install claude-tokens
```

> Requires [Scoop](https://scoop.sh) and Python installed (`scoop install python`).
>
> Or use **pipx** (cross-platform, needs Python): `pipx install stradiz-claude-tokens` — install pipx with `py -m pip install --user pipx`.

### Linux — pipx

```bash
pipx install stradiz-claude-tokens
```

> `pipx` isolates the install and ensures `claude-tokens` lands in your PATH automatically.
> Install pipx: `sudo apt install pipx` · `sudo pacman -S python-pipx` · `pip install pipx`
> Unreleased `main`: `pipx install git+https://github.com/Bernardo-Andreatta/terminal-claude-token-usage.git`

### Any platform — from source

```bash
git clone https://github.com/Bernardo-Andreatta/terminal-claude-token-usage.git
cd terminal-claude-token-usage
pipx install .
```

## Usage

```bash
claude-tokens            # interactive TUI
claude-tokens-calibrate  # standalone calibration wizard
claude-tokens-colors     # standalone color picker
claude-tokens-models     # standalone model/effort selector
python -m claude_tokens  # same as claude-tokens, via module
```

Keys: `q` quit · `r` force refresh · `c` calibrate limits · `m` model & effort · `t` pick colors

## Configuration

Settings are saved to `~/.claude/claude-tokens.conf` — the calibration wizard and color picker both offer to save there automatically. No shell editing required.

You can also set any value as an env var (env vars override the config file):

```bash
# ~/.claude/claude-tokens.conf  (or export in ~/.zshrc / $PROFILE)
CLAUDE_SESSION_LIMIT=7631489
CLAUDE_WEEKLY_LIMIT=26230769
CLAUDE_REFRESH=15
```

### Calibrating limits

Press `c` in the TUI (or run `claude-tokens-calibrate` standalone) while claude.ai shows your current usage percentages. The tool reads your current token counts, prompts for the percentages shown on claude.ai → Settings → Usage, and calculates limits automatically.

```
  Session usage % shown on claude.ai: 36
  Weekly  usage % shown on claude.ai: 26

  CLAUDE_SESSION_LIMIT = 7,550,583  (7.55M)
  CLAUDE_WEEKLY_LIMIT  = 26,076,923  (26.08M)
```

Limits apply immediately in the running TUI. The wizard then prompts to save to `~/.claude/claude-tokens.conf`.

### Model & effort

Press `m` in the TUI (or run `claude-tokens-models` standalone) to select the model and reasoning effort level you currently use.

- **Model** sets the pricing fallback for records that don't log a recognizable model (synthetic records, sidechains). Records that log a real model are always priced by that model — this only fixes the unknowns, which otherwise default to Sonnet pricing (a 3.3× underestimate if you actually use Fable).
- **Effort** applies a prior multiplier to output-token quota cost (`low` 0.85× · `medium` 1.0× · `high` 1.15×). Anthropic doesn't publish per-effort quota weighting, so these are tunable starting points (`CLAUDE_EFFORT_MULT_*`); recalibrate after changing them so limits re-anchor.

### Colors

Press `t` in the TUI (or run `claude-tokens-colors` standalone) to open the interactive color picker. Choose warning color behavior, pick a color per role from 16 swatches, and preview the full widget live.

Color roles can also be set directly as env vars:

```bash
CLAUDE_COLOR_SESSION=cyan      # session section (default: cyan)
CLAUDE_COLOR_WEEK=magenta      # week section (default: magenta)
CLAUDE_COLOR_OK=green          # remaining indicator, low usage (default: green)
CLAUDE_COLOR_WARN=yellow       # bar/remaining at 75%+ usage (default: yellow)
CLAUDE_COLOR_CRIT=red          # bar/remaining at 90%+ usage (default: red)
```

Accepts color names (`cyan`, `bright_cyan`, `magenta`, …) or raw ANSI codes (`36`, `35`, `92`, …).

### All env vars

| Variable | Default | Description |
|---|---|---|
| `CLAUDE_SESSION_LIMIT` | `0` | Session token limit (0 = no bar cap) |
| `CLAUDE_WEEKLY_LIMIT` | `0` | Weekly token limit (0 = no bar cap) |
| `CLAUDE_REFRESH` | `15` | Refresh interval in seconds |
| `CLAUDE_SESSION_OFFSET_SECS` | `0` | Shift session start earlier (useful when starting on claude.ai web) |
| `CLAUDE_WEIGHT_CACHE_READ_SESSION` | `1.0` | Cache-read quota weight, session (1.0 = full cost, 0 = ignored; calibration learns it) |
| `CLAUDE_WEIGHT_CACHE_READ_WEEKLY` | `0.0` | Cache-read quota weight, weekly |
| `CLAUDE_BASE_PRICE` | `3.00` | $/1M input price used to normalize weighted tokens |
| `CLAUDE_CACHE_WRITE_5M_MULT` | `1.25` | 5-min cache-write price as a multiple of input |
| `CLAUDE_CACHE_WRITE_1H_MULT` | `2.00` | 1-hour cache-write price as a multiple of input |
| `CLAUDE_CACHE_READ_MULT` | `0.10` | Cache-read price as a multiple of input |
| `CLAUDE_MODEL_DEFAULT` | `sonnet` | Pricing fallback for records without a recognizable model |
| `CLAUDE_EFFORT` | `medium` | Reasoning effort level (`low`/`medium`/`high`) |
| `CLAUDE_EFFORT_MULT_LOW` | `0.85` | Output quota multiplier at low effort |
| `CLAUDE_EFFORT_MULT_MEDIUM` | `1.00` | Output quota multiplier at medium effort |
| `CLAUDE_EFFORT_MULT_HIGH` | `1.15` | Output quota multiplier at high effort |
| `CLAUDE_MARGIN` | `2` | Left margin spaces in the TUI |
| `CLAUDE_WARN_COLORS` | `1` | Set to `0` to disable warning color shifts |

## How it works

Reads `~/.claude/projects/**/*.jsonl` — the JSONL logs Claude Code writes per conversation. Aggregates `usage` fields from API response records, deduplicating by message ID across the whole scan to avoid double-counting (Claude Code rewrites each response 2–3×, and resumed sessions copy prior records).

**Cost-weighted tokens:** quota is an opaque weighted token count, not a raw sum. Each record is weighted by its true cost using the real model (`claude-opus-*`, `claude-sonnet-*`, `claude-haiku-*`, …) and cache tier logged per message — so output (~5× input), 1-hour cache writes (2×), 5-minute writes (1.25×), and cache reads (0.1×) each count for what they actually consume. Weighted tokens are normalized to `CLAUDE_BASE_PRICE` input tokens to keep the displayed magnitude token-like. This makes a calibration done in a Sonnet-heavy week transfer to an Opus-heavy one — the flat sum it replaced did not.

**Session window:** detected by simulating 5-hour windows through the last 12 hours of activity. A new session opens whenever an event arrives after the previous 5-hour window has closed — matching claude.ai's fixed session model.

**Weekly window:** resets Tuesday 15:00 UTC (matching claude.ai's observed reset schedule).

**Cache-read accounting:** the one component the quota discounts below cost — session and weekly use different weights (session counts them; weekly ignores them), so it stays calibratable. If your percentages drift from claude.ai, run `c` to recalibrate.
