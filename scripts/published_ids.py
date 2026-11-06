#!/usr/bin/env python3
"""Write build/have.csv: the "portal,id" of every questionnaire already published, read from Hugging Face.

Falls back to the 2025 release list in the repository if the dataset does not exist yet.
"""
import shutil
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from usajq import config  # noqa: E402


def main():
    from huggingface_hub import HfApi
    from huggingface_hub.utils import RepositoryNotFoundError

    out = config.BUILD_DIR / "have.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        files = [f for f in HfApi().list_repo_files(config.HF_DATASET, repo_type="dataset") if f.startswith("data/questionnaires/")]
    except RepositoryNotFoundError:
        files = []
    if not files:
        shutil.copy(config.DATA_DIR / "collected_ids_2025_release.csv", out)
        print("dataset not published yet: using data/collected_ids_2025_release.csv")
        return
    c = duckdb.connect()
    c.execute("install httpfs; load httpfs")
    urls = ", ".join(f"'hf://datasets/{config.HF_DATASET}/{f}'" for f in files)
    c.execute(f"copy (select portal || ',' || questionnaire_id from read_parquet([{urls}])) to '{out}' (format csv, header false, quote '')")
    print("wrote", out)


if __name__ == "__main__":
    main()
