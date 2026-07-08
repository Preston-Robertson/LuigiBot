"""One-shot: full-replace the `tasks` table from a correct pandas pickle.

Uses LuigiBot's own db.save path so column mapping / 0-1 bools / ISO dates / uuid
minting all match normal bot writes. Run with the bot's Postgres env set
(DB_Backend=postgres, PG_*, LUIGI_PG_PASSWORD).

    python scripts/reload_tasks_from_pickle.py --pkl to_do_list.pkl --dry-run
    python scripts/reload_tasks_from_pickle.py --pkl to_do_list.pkl        # do it
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Bootstrap so `bot_modules` imports work regardless of cwd.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pandas as pd  # noqa: E402

from bot_modules import db  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pkl", required=True, help="Path to the correct to_do_list pickle.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Inspect the pickle and STOP. No writes.")
    args = ap.parse_args()

    pkl_path = Path(args.pkl)
    if not pkl_path.is_file():
        print(f"ERROR: pickle not found: {pkl_path}", file=sys.stderr)
        return 2

    df = pd.read_pickle(pkl_path)
    print(f"[pickle] path={pkl_path}")
    print(f"[pickle] shape={df.shape}")
    print(f"[pickle] columns={list(df.columns)}")
    print("[pickle] dtypes:")
    print(df.dtypes)
    print("[pickle] head:")
    print(df.head(10).to_string())

    if args.dry_run:
        print("\n[dry-run] Not writing. "
              "Reconcile columns above vs db._TASKS_DF_TO_SQL before real run.")
        return 0

    db.init_db()          # idempotent; ensures v2 schema present (no DDL beyond existing)
    db.save_tasks_df(df)  # whole-table DELETE+INSERT via the bot's own path

    back = db.load_tasks_df()
    null_uuid = int(back["UUID"].isna().sum()) if "UUID" in back.columns else -1
    print(f"\n[reloaded] tasks now = {len(back)} rows")
    print(f"[reloaded] null uuids = {null_uuid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
