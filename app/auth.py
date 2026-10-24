"""Optional password gate. Active only when an APP_PASSWORD secret exists, so the app can be public (and kept awake) without being open."""
from __future__ import annotations

import hmac
import time

import streamlit as st
from secrets_util import secret

LOGIN_HEADING = "Sign in to Freshroots"      # the keep-alive job looks for this text
MAX_TRIES = 5


def require_password() -> None:
    expected = secret("APP_PASSWORD")
    if not expected or st.session_state.get("authed"):
        return
    tries = st.session_state.setdefault("login_tries", 0)
    st.markdown(f'<h1 class="fr-title">{LOGIN_HEADING}</h1><p class="fr-sub">This app is protected. Enter the password to continue.</p>', unsafe_allow_html=True)
    if tries >= MAX_TRIES:
        st.error("Too many wrong attempts. Reload the page to try again.")
        st.stop()
    with st.form("login"):
        given = st.text_input("Password", type="password", key="login_password")
        submitted = st.form_submit_button("Sign in", type="primary", width="stretch")
    if submitted:
        if hmac.compare_digest(given.encode(), expected.encode()):
            st.session_state.authed = True
            st.rerun()
        st.session_state.login_tries = tries + 1
        time.sleep(1)                         # slows guessing
        st.error("Wrong password.")
    st.stop()
