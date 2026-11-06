import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import duckdb  # noqa: E402
from usajq.inventory_merge import COLUMNS, inventory_files, load_inventory, new_rows, write_update  # noqa: E402


def frame(rows):
    df = pd.DataFrame(rows, columns=COLUMNS)
    df["n_announcements"] = df["n_announcements"].astype("int16")
    return df


EXISTING = frame([
    ("usastaffing", "100", "2026_09", 1, "C1", None),
    ("usastaffing", "101", "2026_10", 2, "C2", None),
    ("monster", "55", "2018_03", 1, "C3", "https://jobs.monstergovt.com/x?jnum=55"),
])


def test_only_ids_the_inventory_lacks_are_returned():
    new = frame([
        ("usastaffing", "101", "2026_10", 9, "C2", None),   # already there, different count: ignored
        ("usastaffing", "102", "2026_11", 1, "C4", None),   # new
    ])
    added = new_rows(EXISTING, new)
    assert added.questionnaire_id.tolist() == ["102"]
    assert added.iloc[0].control_number == "C4"


def test_an_existing_id_seen_in_an_earlier_month_keeps_its_existing_row():
    # the earliest sighting stays where it is: the update never rewrites an existing id
    new = frame([("usastaffing", "101", "2026_08", 1, "C9", None)])
    assert new_rows(EXISTING, new).empty


def test_a_second_run_with_the_same_data_adds_nothing():
    new = frame([("usastaffing", "102", "2026_11", 1, "C4", None)])
    added = new_rows(EXISTING, new)
    assert len(added) == 1
    both = pd.concat([EXISTING, added], ignore_index=True)
    assert new_rows(both, new).empty


def test_duplicates_in_the_new_read_are_added_once_and_order_and_types_are_kept():
    new = frame([("monster", "77", "2026_11", 1, "C5", "https://jobs.monstergovt.com/x?jnum=77"),
                 ("usastaffing", "050", "2026_11", 1, "C6", None),
                 ("usastaffing", "050", "2026_11", 1, "C6", None)])
    added = new_rows(EXISTING, new)
    assert added.questionnaire_id.tolist() == ["77", "050"]   # monster sorts before usastaffing; the duplicate is gone
    assert list(added.columns) == COLUMNS
    assert str(added["n_announcements"].dtype) == "int16"
    order = list(zip(added.portal, added.first_seen_month, added.questionnaire_id))
    assert order == sorted(order)


def test_readers_get_the_base_plus_every_update_file_in_a_fixed_order(tmp_path):
    EXISTING.to_parquet(tmp_path / "id_inventory.parquet", index=False)
    (tmp_path / "id_inventory_updates").mkdir()
    u1 = frame([("usastaffing", "102", "2026_11", 1, "C4", None)])
    u2 = frame([("usastaffing", "103", "2026_11", 1, "C5", None)])
    u2.to_parquet(tmp_path / "id_inventory_updates" / "2026-11-08T0617.parquet", index=False)
    u1.to_parquet(tmp_path / "id_inventory_updates" / "2026-11-07T0617.parquet", index=False)
    files = inventory_files(tmp_path)
    assert [f.name for f in files] == ["id_inventory.parquet", "2026-11-07T0617.parquet", "2026-11-08T0617.parquet"]
    inv = load_inventory(tmp_path)
    assert inv.questionnaire_id.tolist() == ["100", "101", "55", "102", "103"]
    # the base file was not touched by writing update files
    pd.testing.assert_frame_equal(pd.read_parquet(tmp_path / "id_inventory.parquet")[COLUMNS], EXISTING)


def test_with_no_updates_folder_only_the_base_is_read(tmp_path):
    EXISTING.to_parquet(tmp_path / "id_inventory.parquet", index=False)
    assert [f.name for f in inventory_files(tmp_path)] == ["id_inventory.parquet"]
    assert len(load_inventory(tmp_path)) == 3


def test_an_update_file_with_no_urls_still_has_the_base_schema_and_reads_with_it(tmp_path):
    # USA Staffing rows have no url, so a whole update can be url-less; the column must stay a string
    EXISTING.to_parquet(tmp_path / "id_inventory.parquet", index=False)
    (tmp_path / "id_inventory_updates").mkdir()
    added = new_rows(EXISTING, frame([("usastaffing", "102", "2026_11", 1, "C4", None)]))
    write_update(added, tmp_path / "id_inventory_updates" / "2026-11-07T0617.parquet")
    con = duckdb.connect()
    base_types = [r[1] for r in con.execute(f"describe select * from read_parquet('{tmp_path / 'id_inventory.parquet'}')").fetchall()]
    upd_types = [r[1] for r in con.execute(
        f"describe select * from read_parquet('{tmp_path / 'id_inventory_updates' / '2026-11-07T0617.parquet'}')").fetchall()]
    assert upd_types == base_types
    files = ", ".join(f"'{f}'" for f in inventory_files(tmp_path))
    assert con.execute(f"select count(*) from read_parquet([{files}])").fetchone()[0] == 4
