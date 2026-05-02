"""CLI entry point for seeding the virtual depot.

Usage:
    python scripts/seed_depot.py [--db PATH] [--cash-eur AMOUNT]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow `python scripts/seed_depot.py` from the repo root to import `src.*`.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.depot.repository import SQLiteDepotRepository  # noqa: E402
from src.depot.seed import DEFAULT_CASH_EUR, DEFAULT_WATCHLIST, seed_depot  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the virtual depot.")
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/depot.sqlite"),
        help="SQLite database path (default: data/depot.sqlite)",
    )
    parser.add_argument(
        "--cash-eur",
        type=int,
        default=DEFAULT_CASH_EUR,
        help=f"Starting cash in EUR (default: {DEFAULT_CASH_EUR})",
    )
    args = parser.parse_args()

    args.db.parent.mkdir(parents=True, exist_ok=True)
    with SQLiteDepotRepository(args.db) as repo:
        seed_depot(repo, cash_eur=args.cash_eur)

    print(
        f"Seeded {args.db} with EUR {args.cash_eur:,} cash "
        f"and {len(DEFAULT_WATCHLIST)} watchlist symbols."
    )


if __name__ == "__main__":
    main()
