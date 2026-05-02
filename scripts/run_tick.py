"""Run one manual trader tick (useful for dev and smoke testing).

Loads settings, builds the full wiring, and runs ``Trader.run_tick``
once. Prints the outcome.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Allow `python scripts/run_tick.py` from the repo root to import `src.*`.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.config import load_settings  # noqa: E402
from src.scheduler import build_runtime_tick_context, build_wiring  # noqa: E402


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = load_settings()
    wiring = build_wiring(settings)
    ctx = build_runtime_tick_context(wiring)
    outcome = wiring.trader.run_tick(ctx)
    print(f"tick outcome: {outcome.kind} | {outcome.detail}")
    if outcome.llm:
        print(
            f"  llm iterations={outcome.llm.iterations} "
            f"input={outcome.llm.usage.input_tokens} "
            f"output={outcome.llm.usage.output_tokens} "
            f"cached={outcome.llm.usage.cache_read_input_tokens}"
        )


if __name__ == "__main__":
    main()
