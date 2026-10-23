"""Round-trip against a real Postgres (a Neon test branch). Skipped unless TEST_DATABASE_URL is set."""
import os
import uuid

import pandas as pd
import pytest

from planner import outputs, review
from planner.cli import main
from planner.common import load_config
from planner.store import Store
from tests.conftest import ROOT

env_file = ROOT / ".env.local"
if env_file.exists() and "TEST_DATABASE_URL" not in os.environ:
    for line in env_file.read_text().splitlines():
        if line.startswith("TEST_DATABASE_URL="):
            os.environ["TEST_DATABASE_URL"] = line.split("=", 1)[1].strip()

pytestmark = pytest.mark.skipif("TEST_DATABASE_URL" not in os.environ, reason="no TEST_DATABASE_URL")


@pytest.fixture()
def store():
    s = Store(os.environ["TEST_DATABASE_URL"], schema="t_" + uuid.uuid4().hex[:10])
    s.ensure_schema()
    yield s
    with s._connect() as conn:
        conn.execute(f"DROP SCHEMA {s.s} CASCADE")


@pytest.fixture()
def cfg():
    return load_config(ROOT / "config.yaml")


@pytest.fixture()
def run_dir(tmp_path):
    assert main(["run", "--data", str(ROOT / "data/raw"), "--run-date", "2026-10-19",
                 "--config", str(ROOT / "config.yaml"), "--outputs", str(tmp_path)]) == 0
    return tmp_path / "2026-10-19"


def count(store, table, run_id="2026-10-19"):
    with store._connect() as conn:
        return conn.execute(f"SELECT count(*) FROM {store.s}.{table} WHERE run_id = %s", (run_id,)).fetchone()[0]


def test_ensure_schema_is_idempotent(store):
    store.ensure_schema()
    assert store.list_runs() == []


def test_save_and_materialize_roundtrip(store, cfg, run_dir, tmp_path):
    store.save_run(run_dir, cfg)
    assert store.list_runs() == ["2026-10-19"]
    assert count(store, "planning_lines") == 15 and count(store, "data_issues") == 2 and count(store, "decisions") == 0

    other = tmp_path / "rebuilt"
    store.materialize(["2026-10-19"], other)
    for name in ("planning_table.csv", "exceptions.csv", "data_quality_report.csv", "run_log.json"):
        assert (other / "2026-10-19" / name).read_bytes() == (run_dir / name).read_bytes()
    assert not (other / "2026-10-19" / "review_log.csv").exists()


def test_decisions_and_pos_survive_a_wiped_disk(store, cfg, run_dir, tmp_path):
    t = outputs.load_planning_table(run_dir)
    ex = t[t.status == "NEEDS_REVIEW"]
    review.append_log(run_dir / "review_log.csv",
                      [review.make_decision(r.sku_id, r.order_qty, "approve", "Raghav", note="ok") for r in ex.itertuples()])
    outputs.generate_pos(run_dir, cfg)
    store.save_run(run_dir, cfg)
    assert count(store, "decisions") == 6 and count(store, "purchase_order_lines") == 5   # 4 exceptions + 2 auto approvals; 5 PO lines

    wiped = tmp_path / "fresh_server"
    store.materialize(store.list_runs(), wiped)                                           # new container, empty disk
    d = wiped / "2026-10-19"
    log = review.read_log(d / "review_log.csv")
    assert sorted(log.sku_id) == sorted(["SKU001", "SKU003", "SKU004", "SKU007", "SKU011", "SKU013"])
    assert (d / "purchase_orders_zoho_import.csv").exists() and len(list(d.glob("PO_*.pdf"))) == 3
    assert not review.pending_review(outputs.load_planning_table(d), review.latest_decisions(log))
    assert pd.read_csv(d / "purchase_orders_zoho_import.csv").shape[0] == 5


def test_save_again_replaces_not_duplicates(store, cfg, run_dir):
    store.save_run(run_dir, cfg)
    review.append_log(run_dir / "review_log.csv", [review.make_decision("SKU001", 750, "approve", "A")])
    store.save_run(run_dir, cfg)
    review.append_log(run_dir / "review_log.csv", [review.make_decision("SKU001", 750, "edit", "A", final_qty=700)])
    store.save_run(run_dir, cfg)
    assert count(store, "decisions") == 2 and count(store, "planning_lines") == 15
    with store._connect() as conn:
        assert conn.execute(f"SELECT count(*) FROM {store.s}.runs").fetchone()[0] == 1
        assert conn.execute(f"SELECT final_qty FROM {store.s}.decisions WHERE sku_id='SKU001' ORDER BY id DESC LIMIT 1").fetchone()[0] == 700


def test_reserve_blocks_run_id_reuse(store, tmp_path):
    store.reserve(["2026-10-19", "2026-10-12"], tmp_path)
    assert outputs.new_run_dir(tmp_path, __import__("datetime").date(2026, 10, 19)).name == "2026-10-19_r2"


def test_invalid_schema_name_rejected():
    with pytest.raises(ValueError):
        Store("postgresql://x", schema="bad; DROP")


def test_app_saves_to_and_reloads_from_the_database(store, cfg, tmp_path, monkeypatch):
    """Whole app flow in DB mode: run planning, decide, then a brand-new server (empty disk) still sees it all."""
    from streamlit.testing.v1 import AppTest
    monkeypatch.delenv("FRESHROOTS_DISABLE_DB")
    monkeypatch.setenv("DATABASE_URL", store.dsn)
    monkeypatch.setenv("FRESHROOTS_DB_SCHEMA", store.s)
    monkeypatch.setenv("FRESHROOTS_OUTPUTS", str(tmp_path / "unused"))
    app = str(ROOT / "app" / "review_app.py")

    at = AppTest.from_file(app, default_timeout=120)
    at.run()
    assert not at.exception
    [b for b in at.button if b.key == "run_now"][0].click().run()
    assert not at.exception and store.list_runs() == ["2026-10-19"]
    at.text_input(key="reviewer").set_value("Raghav").run()
    [b for b in at.button if b.key == "btn-SKU003-0"][0].click().run()       # Use suggested · 309
    assert not at.exception
    assert count(store, "decisions") == 1

    at2 = AppTest.from_file(app, default_timeout=120)                          # new session = new temp folder
    at2.run()
    assert not at2.exception
    assert [m.value for m in at2.metric][:4] == ["15", "4", "2", "9"]
    assert at2.get("progress")[0].proto.text == "1 of 4 exceptions decided"


def test_seed_reference_data_is_complete_and_idempotent(store, cfg):
    counts = store.seed_reference_data(ROOT / "data" / "raw", cfg)
    assert counts == {"distributors": 4, "sku_master": 15, "weekly_sales": 240, "inventory_snapshots": 15, "calendar": 24}
    store.seed_reference_data(ROOT / "data" / "raw", cfg)                      # running twice changes nothing
    with store._connect() as conn:
        n = {t: conn.execute(f"SELECT count(*) FROM {store.s}.{t}").fetchone()[0] for t in counts}
        assert n == counts
        assert conn.execute(f"SELECT units_sold FROM {store.s}.weekly_sales WHERE sku_id='SKU001' AND week='2026-W42'").fetchone()[0] == 259
        assert conn.execute(f"SELECT week_start FROM {store.s}.weekly_sales WHERE week='2026-W42' LIMIT 1").fetchone()[0].isoformat() == "2026-10-12"
        assert conn.execute(f"SELECT count(*) FROM {store.s}.calendar WHERE is_festival_month").fetchone()[0] == 6
