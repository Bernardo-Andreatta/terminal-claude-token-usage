#!/usr/bin/env python3
"""Select the current model and reasoning effort level.

The model choice sets CLAUDE_MODEL_DEFAULT — the pricing fallback for records
whose model string is unrecognised (synthetic records, sidechains). Records
that log a real model are always priced by that model regardless of this
setting. The effort choice sets CLAUDE_EFFORT, a prior multiplier on
output-token quota cost (see EFFORT_MULTS in __main__).
"""

import os
from claude_tokens.config import offer_save


def _ask_choice(label, options, current):
    """Numbered picker. Enter keeps current. Returns chosen value."""
    print(f"\n  {label} (current: {current})")
    for i, opt in enumerate(options, 1):
        marker = "*" if opt == current else " "
        print(f"    {i}. {opt} {marker}")
    while True:
        raw = input(f"  Choice [1-{len(options)}, Enter keeps current]: ").strip()
        if not raw:
            return current
        try:
            n = int(raw)
            if 1 <= n <= len(options):
                return options[n - 1]
        except ValueError:
            pass
        print("  Invalid choice.")


def run():
    """Interactive model/effort selection. Returns saved dict or None."""
    from claude_tokens.__main__ import PRICING, EFFORT_LEVELS, _default_model, _effort_level

    print("\nClaude Tokens — Model & Effort")
    print("Pick the model and effort level you currently use on claude.ai /")
    print("Claude Code. Model sets the pricing fallback for records that don't")
    print("log a model; effort weights output tokens in the quota estimate.")

    models = sorted(PRICING)
    try:
        model  = _ask_choice("Model",  models,        _default_model())
        effort = _ask_choice("Effort", list(EFFORT_LEVELS), _effort_level())
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        input("\nPress Enter to return...")
        return None

    saves = {
        "CLAUDE_MODEL_DEFAULT": model,
        "CLAUDE_EFFORT":        effort,
    }
    for k, v in saves.items():
        os.environ[k] = v

    print(f"\n  Model:  {model}")
    print(f"  Effort: {effort}")
    print("\n  Tip: recalibrate (c) after changing these so limits re-anchor.")

    offer_save(saves)
    input("\nPress Enter to return to monitor...")
    return saves


def main():
    run()


if __name__ == "__main__":
    main()
