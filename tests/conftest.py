import copy
import datetime as dt
from pathlib import Path

import pytest

from planner.common import load_config

ROOT = Path(__file__).resolve().parents[1]
RUN_DATE = dt.date(2026, 10, 19)


@pytest.fixture(autouse=True)
def _never_touch_the_real_database(monkeypatch):
    """The app reads DATABASE_URL from .streamlit/secrets.toml; tests must never write to that database."""
    monkeypatch.setenv("FRESHROOTS_DISABLE_DB", "1")
    monkeypatch.delenv("DATABASE_URL", raising=False)


@pytest.fixture(scope="session")
def root():
    return ROOT


@pytest.fixture()
def cfg():
    return copy.deepcopy(load_config(ROOT / "config.yaml"))


@pytest.fixture()
def data_dir():
    return ROOT / "data" / "raw"


@pytest.fixture()
def dirty_dir(tmp_path):
    """Deliberately dirty copies of the five inputs."""
    import shutil
    for f in ROOT.joinpath("data/raw").glob("*.csv"):
        shutil.copy(f, tmp_path / f.name)
    sales = (tmp_path / "weekly_sales.csv").read_text().replace("\n", "\r\n")
    lines = sales.split("\r\n")
    out = []
    for ln in lines:
        if ln.startswith("SKU005,2026-W35,"):          # missing week for SKU005
            continue
        if ln.startswith("SKU006,2026-W36,"):          # negative
            ln = "SKU006,2026-W36,-5"
        if ln.startswith("SKU007,2026-W37,"):          # blank
            ln = "SKU007,2026-W37,"
        if ln.startswith("SKU009,2026-W40,"):          # lowercase + whitespace id
            ln = " sku009 ,2026-W40,32"
        out.append(ln)
    out += ["SKU010,2026-W41,25",                      # identical duplicate
            "SKU011,2026-W42,999",                     # conflicting duplicate
            "SKU099,2026-W42,40",                      # unknown SKU
            "SKU012,2026-W43,70",                      # incomplete current week
            "SKU013,2026-W38,0",                       # zero
            ""]
    (tmp_path / "weekly_sales.csv").write_text("\r\n".join(out))
    inv = (tmp_path / "current_inventory.csv").read_text()
    inv = "\n".join(ln for ln in inv.split("\n") if not ln.startswith("SKU015,"))   # master SKU w/o inventory
    (tmp_path / "current_inventory.csv").write_text(inv + "\n")
    master = (tmp_path / "sku_master.csv").read_text()
    master = master.replace("SKU003,Freshroots Brown Rice 1kg,Staple,Low", "SKU003,Freshroots Brown Rice 1kg,Staple,Medium")
    master = master.replace("SKU002,Freshroots Oats Cookies 150g,Snack,Low,200,Units,DIST001", "SKU002,Freshroots Oats Cookies 150g,Snack,low,200,Units,dist009")
    (tmp_path / "sku_master.csv").write_text(master)
    return tmp_path
