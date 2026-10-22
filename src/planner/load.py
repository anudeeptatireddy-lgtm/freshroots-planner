"""Stage 1: load the input files, check required columns, hash them."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from planner.common import PlannerError

REQUIRED = {
    "sales": ["SKU_ID", "Week", "Units_Sold"],
    "sku_master": ["SKU_ID", "SKU_Name", "Category", "Perishability", "Standard_Reorder_Qty",
                   "Unit_of_Measure", "Distributor_ID"],
    "distributors": ["Distributor_ID", "Distributor_Name", "Region", "Status"],
    "inventory": ["SKU_ID", "Location", "Units_On_Hand", "As_Of_Date"],
    "calendar": ["Year", "Month", "Year_Month", "Is_Festival_Month"],
}
OPTIONAL_REQUIRED = {
    "open_pos": ["SKU_ID", "Open_PO_Qty"],
    "prices": ["SKU_ID", "Unit_Price"],
    "distributor_sales": ["Distributor_ID", "SKU_ID", "Week", "Units_Sold"],
}


def read_csv(path: Path, required: list[str], label: str) -> pd.DataFrame:
    """Read as text (no type guessing). Handles CRLF and a UTF-8 BOM."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig",
                     skip_blank_lines=True)
    df.columns = [str(c).strip() for c in df.columns]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise PlannerError(f"{path.name}: missing required column(s) {missing}")
    df = df.dropna(how="all")
    df["_row"] = range(2, len(df) + 2)   # spreadsheet-style row number (header = row 1)
    return df


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_all(data_dir: str | Path, cfg: dict) -> tuple[dict, dict]:
    """Returns (raw frames, file hashes). Optional frames are None when absent."""
    data_dir = Path(data_dir)
    raw, hashes = {}, {}
    for key, required in REQUIRED.items():
        path = data_dir / cfg["files"][key]
        if not path.exists():
            raise PlannerError(f"Required file not found: {path}")
        raw[key] = read_csv(path, required, key)
        hashes[path.name] = sha256(path)
    for key, required in OPTIONAL_REQUIRED.items():
        path = data_dir / cfg["optional_files"][key]
        if path.exists():
            raw[key] = read_csv(path, required, key)
            hashes[path.name] = sha256(path)
        else:
            raw[key] = None
    return raw, hashes
