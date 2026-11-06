#!/usr/bin/env python3
"""Check the daily update against the full inventory (needs the network; run by hand).

Takes the committed base inventory, deletes every row first seen in the newest N months, runs the update path
over those months, and compares the base plus the new update file with the original. Everything the full build
had for those months must come back with the same values; extra ids were announced after the full build.
It works on copies: the inventory files are restored at the end.

    python3 scripts/verify_inventory_update.py [--months 2]
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from usajq.inventory_merge import COLUMNS, load_inventory  # noqa: E402

DATA = ROOT / "data"
BASE = DATA / "id_inventory.parquet"
UPDATES = DATA / "id_inventory_updates"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=2)
    args = ap.parse_args()
    backup = BASE.with_suffix(".verify-backup")
    upd_backup = DATA / "id_inventory_updates.verify-backup"
    shutil.copy(BASE, backup)
    if UPDATES.exists():
        shutil.move(str(UPDATES), str(upd_backup))
    try:
        full = pd.read_parquet(BASE)
        months = sorted(full.first_seen_month.unique())[-args.months:]
        cut = months[0]
        simulated = full[full.first_seen_month < cut].reset_index(drop=True)
        simulated.to_parquet(BASE, index=False)
        print(f"full inventory {len(full):,} rows; simulated one without months {months}: {len(simulated):,} rows")
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "inventory.py"), "--update", "--months", str(args.months)],
                           capture_output=True, text=True)
        print(r.stdout.strip())
        if r.returncode:
            print("update exit code", r.returncode, r.stderr[-300:])
            return 1
        base_after = pd.read_parquet(BASE)
        updates_files = sorted(UPDATES.glob("*.parquet")) if UPDATES.exists() else []
        updated = load_inventory(DATA)
        print(f"update files written: {[f.name for f in updates_files]}")
        print("base file untouched by the update:", base_after[COLUMNS].equals(simulated[COLUMNS]))
    finally:
        shutil.copy(backup, BASE)
        backup.unlink()
        shutil.rmtree(UPDATES, ignore_errors=True)
        if upd_backup.exists():
            shutil.move(str(upd_backup), str(UPDATES))
    key = ["portal", "questionnaire_id"]
    old_slice = full[full.first_seen_month >= cut]
    got = updated.merge(old_slice, on=key, how="right", suffixes=("_new", "_old"), indicator=True)
    missing = (got["_merge"] != "both").sum()
    print(f"\nrows the full build had for {months}: {len(old_slice):,}; missing after the update: {missing}")
    both = got[got["_merge"] == "both"]
    for col in ["first_seen_month", "control_number", "url", "n_announcements"]:
        a, b = both[f"{col}_new"], both[f"{col}_old"]
        mask = ~((a == b) | (a.isna() & b.isna()))
        print(f"  {col}: {int(mask.sum())} differ")
        if col == "control_number" and mask.any():
            print("    those ids have n_announcements:", sorted(both.loc[mask, "n_announcements_old"].tolist()),
                  "(an id in several announcements in one month gets an arbitrary one of them in any build)")
    extra = updated.merge(full[key], on=key, how="left", indicator=True)
    extra = extra[extra["_merge"] == "left_only"]
    print(f"ids not in the full inventory (announced since it was built): {len(extra):,}",
          extra.groupby("first_seen_month").size().to_dict())
    print("duplicate ids after the update:", int(updated.duplicated(key).sum()))
    print("schema identical:", list(updated.dtypes.astype(str)) == list(full.dtypes.astype(str)))
    return 0 if missing == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
