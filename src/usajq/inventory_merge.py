"""Keep the id inventory current without rewriting it.

`data/id_inventory.parquet` is the base: one row per questionnaire (portal, questionnaire_id), built once from
every announcement month. The daily update re-reads only the newest months and writes the ids the base does not
have into a small file of its own, `data/id_inventory_updates/<UTC date and time>.parquet`. Nothing already in
the base or in an earlier update file is rewritten, so a daily commit adds kilobytes, not the 7 MB base again.
Readers use `inventory_files()` to get the base plus every update file.
"""
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from usajq import config

COLUMNS = ["portal", "questionnaire_id", "first_seen_month", "n_announcements", "control_number", "url"]
KEY = ["portal", "questionnaire_id"]

# The base inventory's types. Update files are written with exactly these, because pandas would write an
# all-empty `url` column (USA Staffing rows only) as an integer column, which DuckDB cannot read together
# with the base file.
SCHEMA = pa.schema([
    ("portal", pa.string()), ("questionnaire_id", pa.string()), ("first_seen_month", pa.string()),
    ("n_announcements", pa.int16()), ("control_number", pa.string()), ("url", pa.string()),
])


def inventory_files(data_dir=None):
    """The base inventory plus every update file, in a fixed order."""
    data_dir = Path(data_dir or config.DATA_DIR)
    base = data_dir / "id_inventory.parquet"
    updates = sorted((data_dir / "id_inventory_updates").glob("*.parquet"))
    return [base] + updates


def load_inventory(data_dir=None) -> pd.DataFrame:
    frames = [pd.read_parquet(f)[COLUMNS] for f in inventory_files(data_dir)]
    return pd.concat(frames, ignore_index=True)


def new_rows(existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """The rows of `new` whose (portal, questionnaire_id) is not in `existing`.

    Ids already in the inventory are ignored, whatever month or count the new read shows for them: the
    earliest sighting stays on the row that already exists. Returned in the inventory's order (portal,
    first_seen_month, questionnaire_id) with the inventory's types.
    """
    seen = set(zip(existing["portal"], existing["questionnaire_id"]))
    mask = [(p, q) not in seen for p, q in zip(new["portal"], new["questionnaire_id"])]
    out = new.loc[mask, COLUMNS].drop_duplicates(KEY)
    out = out.sort_values(["portal", "first_seen_month", "questionnaire_id"]).reset_index(drop=True)
    out["n_announcements"] = out["n_announcements"].astype("int16")
    return out


def write_update(rows: pd.DataFrame, path) -> None:
    """Write update rows with the base inventory's exact schema."""
    table = pa.Table.from_pandas(rows[COLUMNS], schema=SCHEMA, preserve_index=False)
    pq.write_table(table, path, compression="zstd")
