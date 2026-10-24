"""The Zoho step against a FAKE Zoho. No real network call is made anywhere in this file."""
import json

import pytest

from planner import outputs, review, zoho
from planner.cli import main
from planner.common import PlannerError, load_config
from tests.conftest import ROOT


@pytest.fixture()
def cfg():
    return load_config(ROOT / "config.yaml")


@pytest.fixture()
def run_dir(tmp_path):
    assert main(["run", "--data", str(ROOT / "data/raw"), "--run-date", "2026-10-19",
                 "--config", str(ROOT / "config.yaml"), "--outputs", str(tmp_path)]) == 0
    d = tmp_path / "2026-10-19"
    t = outputs.load_planning_table(d)
    review.append_log(d / "review_log.csv", [review.make_decision(r.sku_id, r.order_qty, "approve", "Raghav") for r in t[t.status != "NO_ORDER"].itertuples()])
    outputs.generate_pos(d, load_config(ROOT / "config.yaml"))
    return d


@pytest.fixture()
def drafts(run_dir, cfg):
    return zoho.build_drafts(run_dir / "purchase_orders_zoho_import.csv", cfg)


class FakeZoho:
    """Answers like Zoho's API for the 4 vendors and 15 items we would import."""

    def __init__(self, vendors=None, items=None, org_count=1):
        self.calls, self.created = [], []
        self.vendors = vendors if vendors is not None else {"NutriFlow Distributors": "V1", "GrainPath Logistics": "V2", "Meridian Trade Co.": "V4"}
        self.items = items if items is not None else {f"SKU{n:03d}": f"I{n}" for n in range(1, 16)}
        self.org_count = org_count

    def __call__(self, method, url, *, params=None, json_body=None, data=None, headers=None):
        self.calls.append((method, url, dict(params or {}), json_body, headers))
        if "oauth/v2/token" in url:
            assert data["grant_type"] == "refresh_token" and data["client_id"] == "cid"
            return {"access_token": "tok"}
        assert headers and headers["Authorization"] == "Zoho-oauthtoken tok"
        if url.endswith("/organizations"):
            return {"code": 0, "organizations": [{"organization_id": str(100 + i)} for i in range(self.org_count)]}
        assert params["organization_id"] == "100"
        if url.endswith("/contacts"):
            n = params["contact_name_contains"]
            return {"code": 0, "contacts": [{"contact_name": k, "contact_id": v} for k, v in self.vendors.items() if n.lower() in k.lower()]}
        if url.endswith("/items"):
            return {"code": 0, "items": [{"sku": k, "item_id": v} for k, v in self.items.items() if k == params["sku"]]}
        if url.endswith("/purchaseorders") and method == "POST":
            self.created.append(json_body)
            return {"code": 0, "purchaseorder": {"purchaseorder_id": f"PO{len(self.created)}", "purchaseorder_number": f"PO-0000{len(self.created)}"}}
        raise AssertionError(f"unexpected call {method} {url}")


def client(fake):
    return zoho.ZohoClient(zoho.ZohoSettings("cid", "secret", "refresh", "in", ""), http=fake)


def test_drafts_match_the_generated_pos(drafts):
    assert [d["po_number"] for d in drafts] == ["FR-PO-20261019-01", "FR-PO-20261019-02", "FR-PO-20261019-03"]
    by = {d["vendor_name"]: {ln["sku"]: ln["quantity"] for ln in d["lines"]} for d in drafts}
    assert by == {"NutriFlow Distributors": {"SKU001": 750, "SKU013": 120}, "GrainPath Logistics": {"SKU003": 300, "SKU004": 150},
                  "Meridian Trade Co.": {"SKU011": 500}}
    assert all(d["date"] == "2026-10-19" for d in drafts)


def test_check_flags_missing_prices(drafts):
    issues = zoho.check_drafts(drafts)
    assert len(issues) == 5 and all("no unit price" in i for i in issues)


def test_dry_run_makes_no_network_call_and_sends_nothing(drafts, monkeypatch):
    import urllib.request

    def boom(*a, **k):
        raise AssertionError("dry run must not touch the network")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    monkeypatch.setattr(zoho, "default_http", boom)
    res = zoho.send(drafts, dry_run=True)
    assert [r["status"] for r in res] == ["dry-run"] * 3 and all("payload" in r for r in res)
    assert res[0]["payload"]["line_items"][0]["quantity"] == 750 and res[0]["payload"]["reference_number"] == "FR-PO-20261019-01"


def test_preview_file_says_nothing_was_sent(drafts, run_dir):
    p = zoho.write_preview(run_dir, zoho.send(drafts), zoho.check_drafts(drafts))
    data = json.loads(p.read_text())
    assert data["sent_to_zoho"] is False and data["mode"] == "dry-run" and len(data["purchase_orders"]) == 3


def test_live_send_matches_by_name_and_sku_and_creates_drafts(drafts):
    fake = FakeZoho(vendors={"NutriFlow Distributors": "V1", "GrainPath Logistics": "V2", "Meridian Trade Co.": "V4"})
    res = zoho.send(drafts, dry_run=False, client=client(fake))
    assert [r["status"] for r in res] == ["created"] * 3
    first = fake.created[0]
    assert first["vendor_id"] == "V1" and first["reference_number"] == "FR-PO-20261019-01" and first["date"] == "2026-10-19"
    assert [(i["item_id"], i["quantity"]) for i in first["line_items"]] == [("I1", 750), ("I13", 120)]
    assert all("rate" not in i for i in first["line_items"])                      # no price in the data, none invented
    assert sum(1 for c in fake.calls if "oauth" in c[1]) == 1                    # one token for the whole run
    assert fake.calls[1][1].endswith("/organizations")                           # org id discovered, not configured


def test_unmatched_vendor_or_item_is_skipped_not_guessed(drafts):
    fake = FakeZoho(vendors={"NutriFlow Distributors": "V1"}, items={f"SKU{n:03d}": f"I{n}" for n in range(1, 16) if n != 4})
    res = {r["po_number"]: r for r in zoho.send(drafts, dry_run=False, client=client(fake))}
    assert res["FR-PO-20261019-01"]["status"] == "created"
    assert res["FR-PO-20261019-02"]["status"] == "skipped" and "GrainPath Logistics" in res["FR-PO-20261019-02"]["detail"] and "SKU004" in res["FR-PO-20261019-02"]["detail"]
    assert res["FR-PO-20261019-03"]["status"] == "skipped"
    assert len(fake.created) == 1


def test_price_is_sent_as_rate_when_known(drafts):
    for ln in drafts[0]["lines"]:
        ln["unit_price"] = 12.5
    fake = FakeZoho()
    zoho.send(drafts[:1], dry_run=False, client=client(fake))
    assert [i["rate"] for i in fake.created[0]["line_items"]] == [12.5, 12.5]


def test_ambiguous_organisation_needs_an_explicit_id(drafts):
    res = zoho.send(drafts[:1], dry_run=False, client=client(FakeZoho(org_count=2)))
    assert res[0]["status"] == "error" and "ZOHO_ORG_ID" in res[0]["detail"]


def test_settings_and_status_never_expose_values():
    env = {"ZOHO_CLIENT_ID": "id", "ZOHO_CLIENT_SECRET": "sec", "ZOHO_REFRESH_TOKEN": "", "ZOHO_DC": "in"}
    assert zoho.settings_from(env) is None                                       # refresh token missing
    assert zoho.credentials_status(env) == {"ZOHO_CLIENT_ID": True, "ZOHO_CLIENT_SECRET": True, "ZOHO_REFRESH_TOKEN": False, "ZOHO_ORG_ID": False}
    s = zoho.settings_from({**env, "ZOHO_REFRESH_TOKEN": "r"})
    assert (s.client_id, s.dc, s.org_id) == ("id", "in", "")
    with pytest.raises(PlannerError):
        zoho.ZohoClient(s, http=lambda *a, **k: {"error": "invalid_code"}).token()


def test_exchange_code_returns_refresh_token_and_never_needs_the_network():
    seen = {}

    def fake(method, url, *, data=None, **k):
        seen.update(url=url, data=data)
        return {"refresh_token": "r-token", "access_token": "a"}

    values = {"ZOHO_CLIENT_ID": "cid", "ZOHO_CLIENT_SECRET": "sec", "ZOHO_DC": "in"}
    assert zoho.exchange_code(values, " the-code ", http=fake) == "r-token"
    assert seen["url"] == "https://accounts.zoho.in/oauth/v2/token" and seen["data"]["code"] == "the-code" and seen["data"]["grant_type"] == "authorization_code"


def test_exchange_code_explains_a_bad_or_expired_code():
    values = {"ZOHO_CLIENT_ID": "cid", "ZOHO_CLIENT_SECRET": "sec"}
    with pytest.raises(PlannerError, match="invalid_code.*fresh one"):
        zoho.exchange_code(values, "bad", http=lambda *a, **k: {"error": "invalid_code"})
    with pytest.raises(PlannerError, match="must be set first"):
        zoho.exchange_code({}, "x", http=lambda *a, **k: {})


def test_save_secret_replaces_or_appends_without_touching_other_lines(tmp_path):
    f = tmp_path / "secrets.toml"
    f.write_text('DATABASE_URL = "keep-me"\nZOHO_REFRESH_TOKEN = ""\n')
    zoho.save_secret(f, "ZOHO_REFRESH_TOKEN", "new")
    assert f.read_text() == 'DATABASE_URL = "keep-me"\nZOHO_REFRESH_TOKEN = "new"\n'
    zoho.save_secret(f, "ZOHO_ORG_ID", "123")
    assert f.read_text().splitlines() == ['DATABASE_URL = "keep-me"', 'ZOHO_REFRESH_TOKEN = "new"', 'ZOHO_ORG_ID = "123"']


def test_zoho_token_command_writes_the_secret_and_does_not_print_it(tmp_path, monkeypatch, capsys):
    f = tmp_path / "secrets.toml"
    f.write_text('ZOHO_CLIENT_ID = "cid"\nZOHO_CLIENT_SECRET = "sec"\nZOHO_DC = "in"\n')
    monkeypatch.setattr(zoho, "default_http", lambda *a, **k: {"refresh_token": "SUPER-SECRET-TOKEN"})
    assert main(["zoho-token", "--code", "abc", "--secrets", str(f)]) == 0
    assert 'ZOHO_REFRESH_TOKEN = "SUPER-SECRET-TOKEN"' in f.read_text()
    assert "SUPER-SECRET-TOKEN" not in capsys.readouterr().out
