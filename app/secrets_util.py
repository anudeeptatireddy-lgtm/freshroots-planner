"""One place to read a secret: environment first, then Streamlit Secrets (skipped when external services are disabled, e.g. in tests)."""
from __future__ import annotations

import os

import streamlit as st


def secret(name: str) -> str:
    v = os.environ.get(name, "")
    if not v and not os.environ.get("FRESHROOTS_DISABLE_DB"):
        try:
            v = st.secrets[name]
        except Exception:     # no secrets file / key
            v = ""
    return str(v or "")
