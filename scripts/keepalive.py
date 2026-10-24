"""Visit the hosted app like a person would, so Streamlit Cloud never puts it to sleep (it hibernates after ~12 hours without visitors).

Run by .github/workflows/keep-awake.yml every few hours. Exit code 0 = the app is awake and protected. Anything else fails the job
loudly, so GitHub emails you instead of the app quietly sleeping:
  - 'private'  : Streamlit's own login is in the way, so a robot cannot visit. Make the app public AND set an APP_PASSWORD secret.
  - 'open'     : the app is public with NO password. Set the APP_PASSWORD secret now.
  - 'unknown'  : the page never settled into a known state.
"""
from __future__ import annotations

import contextlib
import os
import re
import sys
import time

LOGIN_HEADING = "Sign in to Freshroots"
APP_HEADING = "Freshroots demand planning"
WAKE_BUTTON = re.compile(r"get this app back up", re.I)


def classify(url: str, text: str) -> tuple[str, str]:
    """(status, message). status is one of: sleeping, private, protected, open, loading."""
    if "share.streamlit.io/-/auth" in url or re.search(r"sign in to (continue|your streamlit)|log in to continue", text, re.I):
        return "private", "Streamlit's own sign-in is blocking visitors. Set the app to public and set an APP_PASSWORD secret."
    if re.search(r"gone to sleep|back up", text, re.I):
        return "sleeping", "The app was asleep; waking it."
    if LOGIN_HEADING in text:
        return "protected", "The app is awake and showing its password page."
    if APP_HEADING in text:
        return "open", "The app is public with NO password. Set an APP_PASSWORD secret in Streamlit now."
    return "loading", "Still loading."


def page_text(page) -> str:
    """Text of the page and of every frame (Streamlit renders the app inside an iframe)."""
    parts = []
    for frame in page.frames:
        with contextlib.suppress(Exception):
            parts.append(frame.inner_text("body", timeout=2000))
    return "\n".join(parts)


def main(url: str, timeout_s: int = 150) -> int:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        deadline, status, msg, woke = time.time() + timeout_s, "loading", "", False
        while time.time() < deadline:
            time.sleep(3)
            status, msg = classify(page.url, page_text(page))
            if status == "sleeping" and not woke:
                try:
                    page.get_by_role("button", name=WAKE_BUTTON).click(timeout=5000)
                    woke = True
                except Exception:
                    pass
            if status in ("private", "protected", "open"):
                break
        browser.close()
    print(f"[{status}] {msg}")
    return 0 if status == "protected" else 1


if __name__ == "__main__":
    app_url = os.environ.get("APP_URL") or (sys.argv[1] if len(sys.argv) > 1 else "")
    if not app_url:
        sys.exit("Set APP_URL or pass the app URL as the first argument.")
    sys.exit(main(app_url))
