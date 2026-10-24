"""Zoho Inventory import files built from our seed data (no API needed).

Zoho's import wizard has a column-mapping step, so these headers only need to be recognisable.
Nothing is invented: Zoho wants a purchase rate and an opening-stock value, and we have no prices, so those columns are left blank.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from planner.load import load_all


def build(data_dir: str | Path, cfg: dict) -> dict[str, pd.DataFrame]:
    raw, _ = load_all(data_dir, cfg)
    dist = raw["distributors"].set_index(raw["distributors"]["Distributor_ID"].str.strip())
    master = raw["sku_master"]
    stock = raw["inventory"].groupby(raw["inventory"]["SKU_ID"].str.strip())["Units_On_Hand"].apply(lambda s: sum(int(float(v)) for v in s))

    vendors = pd.DataFrame({
        "Display Name": dist["Distributor_Name"].str.strip().values,
        "Company Name": dist["Distributor_Name"].str.strip().values,
        "Contact Type": "vendor",
        "Billing State": dist["Region"].str.strip().values,
        "Status": dist["Status"].str.strip().str.lower().values,
    })
    items = pd.DataFrame({
        "Item Name": master["SKU_Name"].str.strip().values,
        "SKU": master["SKU_ID"].str.strip().values,
        "Unit": master["Unit_of_Measure"].str.strip().str.lower().replace({"units": "pcs"}).values,
        "Product Type": "goods",
        "Item Type": "Inventory",
        "Category": master["Category"].str.strip().values,
        "Preferred Vendor": [dist.loc[d.strip(), "Distributor_Name"].strip() if d.strip() in dist.index else "" for d in master["Distributor_ID"]],
        "Opening Stock": [int(stock.get(s.strip(), 0)) for s in master["SKU_ID"]],
        "Opening Stock Value": "",
        "Purchase Rate": "",
        "Status": "active",
    })
    return {"vendors.csv": vendors, "items.csv": items}


def write(data_dir: str | Path, cfg: dict, out_dir: str | Path) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, df in build(data_dir, cfg).items():
        p = out_dir / name
        df.to_csv(p, index=False)
        paths.append(p)
    return paths
