"""Send approved POs to Zoho Inventory as DRAFT purchase orders.

Dry run is the default and never touches the network: it shows exactly what would be sent. Live sending needs
`zoho.dry_run_only: false` in config.yaml AND credentials, and has only been exercised against a fake Zoho in tests
(no Zoho organisation was available when this was written), so check the first real draft by hand.

Matching: each supplier is looked up in Zoho by name and each product by SKU. Anything that does not match is reported
and its PO is skipped; nothing is guessed or created on the fly.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from planner.common import PlannerError

Http = Callable[..., dict]
PREVIEW_FILE = "zoho_preview.json"


@dataclass(frozen=True)
class ZohoSettings:
    client_id: str
    client_secret: str
    refresh_token: str
    dc: str = "in"
    org_id: str = ""


def settings_from(values: Mapping[str, str]) -> ZohoSettings | None:
    """Build settings from secrets/env (ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN, ZOHO_DC, ZOHO_ORG_ID)."""
    get = lambda k, d="": str(values.get(k, d) or d).strip()  # noqa: E731
    cid, secret, refresh = get("ZOHO_CLIENT_ID"), get("ZOHO_CLIENT_SECRET"), get("ZOHO_REFRESH_TOKEN")
    if not (cid and secret and refresh):
        return None
    return ZohoSettings(cid, secret, refresh, get("ZOHO_DC", "in") or "in", get("ZOHO_ORG_ID"))


def credentials_status(values: Mapping[str, str]) -> dict[str, bool]:
    """Which settings are present (never the values), for showing in the app."""
    return {k: bool(str(values.get(k, "") or "").strip())
            for k in ("ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN", "ZOHO_ORG_ID")}


# ---- drafts (pure) ---------------------------------------------------------------------------
def build_drafts(zoho_csv: str | Path, cfg: dict) -> list[dict]:
    """One draft per PO, read from the run's Zoho import CSV (so it always matches what was generated)."""
    zc = cfg["po"]["zoho_columns"]
    df = pd.read_csv(zoho_csv, keep_default_na=False, dtype=str)
    drafts = []
    for po, g in df.groupby(zc["po_number"], sort=True):
        first = g.iloc[0]
        drafts.append({
            "po_number": po,
            "date": first[zc["po_date"]],
            "vendor_name": first[zc["vendor_name"]],
            "vendor_ref": first[zc["vendor_id"]],
            "lines": [{"sku": r[zc["sku"]], "item_name": r[zc["item_name"]], "quantity": int(r[zc["quantity"]]),
                       "unit_price": float(r[zc["unit_price"]]) if r[zc["unit_price"]] else None, "notes": r[zc["notes"]]}
                      for _, r in g.iterrows()],
        })
    return drafts


def check_drafts(drafts: list[dict]) -> list[str]:
    """Things to know before sending (empty list = nothing to flag)."""
    issues = []
    for d in drafts:
        for ln in d["lines"]:
            if ln["unit_price"] is None:
                issues.append(f"{d['po_number']} · {ln['sku']}: no unit price in our data, so no rate is sent (Zoho will use the item's purchase rate, or reject the line).")
        if not d["vendor_name"].strip():
            issues.append(f"{d['po_number']}: no supplier name, so it cannot be matched in Zoho.")
    return issues


def to_zoho_payload(draft: dict, vendor_id: str, item_ids: Mapping[str, str]) -> dict:
    items = []
    for ln in draft["lines"]:
        item = {"item_id": item_ids[ln["sku"]], "quantity": ln["quantity"]}
        if ln["unit_price"] is not None:
            item["rate"] = ln["unit_price"]
        if ln["notes"]:
            item["description"] = ln["notes"]
        items.append(item)
    return {"vendor_id": vendor_id, "date": draft["date"], "reference_number": draft["po_number"],
            "notes": f"Created by the Freshroots demand planner ({draft['po_number']}). Draft: review before release.",
            "line_items": items}


# ---- HTTP ------------------------------------------------------------------------------------
def default_http(method: str, url: str, *, params: dict | None = None, json_body: dict | None = None,
                 data: dict | None = None, headers: dict | None = None) -> dict:
    if params:
        url += "?" + urllib.parse.urlencode(params)
    hdrs, body = dict(headers or {}), None
    if json_body is not None:
        body, hdrs["Content-Type"] = json.dumps(json_body).encode(), "application/json"
    elif data is not None:
        body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("message", "")
        except Exception:
            msg = ""
        raise PlannerError(f"Zoho returned HTTP {e.code}" + (f": {msg}" if msg else "")) from e
    except urllib.error.URLError as e:
        raise PlannerError(f"Could not reach Zoho: {e.reason}") from e


class ZohoClient:
    def __init__(self, settings: ZohoSettings, http: Http = default_http):
        self.s, self.http, self._token, self._org = settings, http, None, settings.org_id or None

    @property
    def _api(self) -> str:
        return f"https://www.zohoapis.{self.s.dc}/inventory/v1"

    def token(self) -> str:
        if not self._token:
            out = self.http("POST", f"https://accounts.zoho.{self.s.dc}/oauth/v2/token",
                            data={"refresh_token": self.s.refresh_token, "client_id": self.s.client_id,
                                  "client_secret": self.s.client_secret, "grant_type": "refresh_token"})
            if "access_token" not in out:
                raise PlannerError(f"Zoho did not give an access token: {out.get('error', 'unknown error')}")
            self._token = out["access_token"]
        return self._token

    def _call(self, method: str, path: str, params: dict | None = None, json_body: dict | None = None, org: bool = True) -> dict:
        params = dict(params or {})
        if org:
            params["organization_id"] = self.org_id()
        out = self.http(method, f"{self._api}{path}", params=params, json_body=json_body,
                        headers={"Authorization": f"Zoho-oauthtoken {self.token()}"})
        if out.get("code", 0) != 0:
            raise PlannerError(f"Zoho error {out.get('code')}: {out.get('message', '')}")
        return out

    def org_id(self) -> str:
        if not self._org:
            orgs = self._call("GET", "/organizations", org=False).get("organizations", [])
            if len(orgs) != 1:
                raise PlannerError(f"Zoho account has {len(orgs)} organisations; set ZOHO_ORG_ID to pick one")
            self._org = str(orgs[0]["organization_id"])
        return self._org

    def find_vendor(self, name: str) -> str | None:
        out = self._call("GET", "/contacts", {"contact_type": "vendor", "contact_name_contains": name})
        hits = [c for c in out.get("contacts", []) if c.get("contact_name", "").strip().casefold() == name.strip().casefold()]
        return str(hits[0]["contact_id"]) if len(hits) == 1 else None

    def find_item(self, sku: str) -> str | None:
        out = self._call("GET", "/items", {"sku": sku})
        hits = [i for i in out.get("items", []) if i.get("sku", "").strip().casefold() == sku.strip().casefold()]
        return str(hits[0]["item_id"]) if len(hits) == 1 else None

    def create_po(self, payload: dict) -> dict:
        return self._call("POST", "/purchaseorders", json_body=payload).get("purchaseorder", {})


# ---- send ------------------------------------------------------------------------------------
def send(drafts: list[dict], *, dry_run: bool = True, client: ZohoClient | None = None) -> list[dict]:
    """Dry run: no network, returns what would be sent. Live: match, then create drafts; unmatched POs are skipped."""
    results = []
    for d in drafts:
        base = {"po_number": d["po_number"], "vendor": d["vendor_name"], "lines": len(d["lines"]),
                "units": sum(ln["quantity"] for ln in d["lines"])}
        if dry_run:
            payload = {"vendor": f"(look up '{d['vendor_name']}' in Zoho)", "date": d["date"], "reference_number": d["po_number"],
                       "line_items": [{"item": f"(look up SKU {ln['sku']})", "quantity": ln["quantity"],
                                       **({"rate": ln["unit_price"]} if ln["unit_price"] is not None else {})} for ln in d["lines"]]}
            results.append({**base, "status": "dry-run", "detail": "Not sent. This is a preview.", "payload": payload})
            continue
        assert client is not None, "live send needs a client"
        try:
            vendor_id = client.find_vendor(d["vendor_name"])
            item_ids = {ln["sku"]: client.find_item(ln["sku"]) for ln in d["lines"]}
            missing = [f"vendor '{d['vendor_name']}'"] * (vendor_id is None) + [f"item {s}" for s, i in item_ids.items() if i is None]
            if missing:
                results.append({**base, "status": "skipped", "detail": "Not found in Zoho: " + ", ".join(missing)})
                continue
            made = client.create_po(to_zoho_payload(d, vendor_id, item_ids))
            results.append({**base, "status": "created", "detail": f"Draft {made.get('purchaseorder_number', '')} created in Zoho".strip(),
                            "zoho_id": made.get("purchaseorder_id", "")})
        except PlannerError as e:
            results.append({**base, "status": "error", "detail": str(e)})
    return results


def write_preview(run_dir: str | Path, results: list[dict], issues: list[str]) -> Path:
    path = Path(run_dir) / PREVIEW_FILE
    path.write_text(json.dumps({"mode": "dry-run", "sent_to_zoho": False, "issues": issues, "purchase_orders": results}, indent=2))
    return path
