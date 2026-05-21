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
  refresh 15s · q quit · r refresh · c calibrate
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

Set limits to match your Claude plan (env vars in `~/.zshrc`):

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

  CLAUDE_SESSION_LIMIT = 7,550,583  (7.55M)
  CLAUDE_WEEKLY_LIMIT  = 26,076,923  (26.08M)
```

Limits apply immediately in the running TUI. The command to export them permanently is printed at the end.

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
python -m claude_tokens  # same as claude-tokens, via module
```

Keys: `q` quit · `r` force refresh · `c` calibrate limits interactively

## How it works

Reads `~/.claude/projects/**/*.jsonl` — the JSONL logs Claude Code writes per conversation. Aggregates `usage` fields from API response records.

**Session window:** detected from the largest gap (>30 min) between consecutive API calls in the last 12 hours, falling back to a rolling 5-hour window if no gap is found.

**Weekly window:** resets Tuesday 15:00 UTC (matching claude.ai's reset schedule).
