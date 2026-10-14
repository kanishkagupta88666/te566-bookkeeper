"""Hosted-demo behaviour: each visitor gets private books; the default stays one shared database."""
import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ui  # noqa: E402
from bookkeeper import db, reports, services  # noqa: E402


@pytest.fixture
def hosted(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKKEEPER_ISOLATE_SESSIONS", "1")
    monkeypatch.delenv("BOOKKEEPER_DB", raising=False)
    monkeypatch.setattr(ui, "SESSION_DIR", tmp_path / "sessions")
    return tmp_path / "sessions"


def app():
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)


def books(session_dir, at):
    return db.connect(session_dir / f"{at.session_state['_workspace']}.db")


def test_sessions_do_not_share_books(hosted):
    first, second = app().run(), app().run()
    assert not first.exception and not second.exception
    assert first.session_state["_workspace"] != second.session_state["_workspace"]

    a, b = books(hosted, first), books(hosted, second)
    customer = a.execute("SELECT id FROM customers ORDER BY id").fetchone()["id"]
    services.create_invoice(a, customer, 20_000)
    assert reports.income_statement(a)["values"]["sales"] == 50_000_00
    assert reports.income_statement(b)["values"]["sales"] == 0  # the other visitor is untouched

    # Reset Demo in one workspace must not wipe the other
    services.create_invoice(b, customer, 1_000)
    from bookkeeper import seed
    seed.reset_demo(a)
    assert reports.income_statement(a)["values"]["sales"] == 0
    assert reports.income_statement(b)["values"]["sales"] == 2_500_00


def test_refresh_returns_to_same_workspace(hosted):
    first = app().run()
    sid = first.session_state["_workspace"]
    assert first.query_params["s"] in (sid, [sid])
    services.create_invoice(books(hosted, first), 1, 20_000)

    refreshed = app()
    refreshed.query_params["s"] = sid
    refreshed.run()
    assert refreshed.session_state["_workspace"] == sid
    assert reports.income_statement(books(hosted, refreshed))["values"]["sales"] == 50_000_00


def test_malformed_workspace_id_is_ignored(hosted):
    at = app()
    at.query_params["s"] = "../../etc/passwd"
    at.run()
    assert not at.exception
    assert ui._WORKSPACE_ID.fullmatch(at.session_state["_workspace"])
    assert all(p.parent == hosted for p in hosted.glob("*"))


def test_local_mode_uses_single_persistent_database(tmp_path, monkeypatch):
    monkeypatch.delenv("BOOKKEEPER_ISOLATE_SESSIONS", raising=False)
    monkeypatch.setenv("BOOKKEEPER_DB", str(tmp_path / "books.db"))
    at = app().run()
    assert not at.exception
    assert "_workspace" not in at.session_state
    assert (tmp_path / "books.db").exists()
