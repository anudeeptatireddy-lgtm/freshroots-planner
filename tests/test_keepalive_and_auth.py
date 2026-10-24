import sys

import pytest
from streamlit.testing.v1 import AppTest

from planner.cli import main
from tests.conftest import ROOT

sys.path.insert(0, str(ROOT / "scripts"))
import keepalive  # noqa: E402

APP = str(ROOT / "app" / "review_app.py")


@pytest.mark.parametrize("url,text,status", [
    ("https://share.streamlit.io/-/auth/app?redirect_uri=x", "", "private"),
    ("https://x.streamlit.app/", "Sign in to continue", "private"),
    ("https://x.streamlit.app/", "This app has gone to sleep due to inactivity\nYes, get this app back up!", "sleeping"),
    ("https://x.streamlit.app/", "Sign in to Freshroots\nThis app is protected.", "protected"),
    ("https://x.streamlit.app/", "Freshroots demand planning\nRun 2026-10-19", "open"),
    ("https://x.streamlit.app/", "Please wait...", "loading"),
])
def test_keepalive_classifies_every_state(url, text, status):
    assert keepalive.classify(url, text)[0] == status


def test_keepalive_only_succeeds_when_the_app_is_awake_and_protected():
    # the exit code rule: protected -> 0, everything else fails the job so you get an email
    assert keepalive.classify("u", "Sign in to Freshroots")[0] == "protected"
    assert keepalive.classify("u", "Freshroots demand planning")[0] != "protected"


@pytest.fixture()
def protected_app(tmp_path, monkeypatch):
    monkeypatch.setenv("FRESHROOTS_OUTPUTS", str(tmp_path))
    monkeypatch.setenv("APP_PASSWORD", "open-sesame")
    assert main(["run", "--data", str(ROOT / "data/raw"), "--run-date", "2026-10-19",
                 "--config", str(ROOT / "config.yaml"), "--outputs", str(tmp_path)]) == 0


def sign_in(at, password):
    at.text_input(key="login_password").set_value(password)
    [b for b in at.button if b.label == "Sign in"][0].click().run()


def test_password_gate_hides_the_app_until_the_right_password(protected_app):
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception
    assert any("Sign in to Freshroots" in m.value for m in at.markdown)
    assert len(at.metric) == 0 and not [b for b in at.button if b.key == "generate"]        # no app content, no data

    sign_in(at, "wrong")
    assert any("Wrong password" in e.value for e in at.error) and len(at.metric) == 0

    sign_in(at, "open-sesame")
    assert not at.exception and [m.value for m in at.metric][:4] == ["15", "4", "2", "9"]


def test_password_gate_locks_after_too_many_wrong_guesses(protected_app):
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    for _ in range(5):
        sign_in(at, "nope")
    at.run()
    assert any("Too many wrong attempts" in e.value for e in at.error)
    assert len(at.metric) == 0


def test_no_password_secret_means_no_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("FRESHROOTS_OUTPUTS", str(tmp_path))
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception and not any("Sign in to Freshroots" in m.value for m in at.markdown)
