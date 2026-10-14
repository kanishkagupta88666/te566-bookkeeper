"""Shared Streamlit helpers: database handle, flash messages, HTML tables, record forms."""
import os
import re
import tempfile
import time
import uuid
from html import escape
from pathlib import Path

import streamlit as st

from bookkeeper import db, seed
from bookkeeper.ledger import LedgerError
from bookkeeper.money import fmt, to_cents
from bookkeeper.services import BusinessError

CSS = """
<style>
.block-container {padding-top: 2.2rem; max-width: 1280px;}
[data-testid="stMetricValue"] {font-size: 1.45rem;}
table.bk {border-collapse: collapse; width: 100%; font-size: 0.92rem; margin-bottom: 0.6rem;}
table.bk th {background: #13294B; color: #fff; text-align: left; padding: 6px 10px; font-weight: 600;}
table.bk td {padding: 5px 10px; border-bottom: 1px solid #e3e7ee;}
table.bk tr:nth-child(even) td {background: #f7f9fc;}
table.bk td.num, table.bk th.num {text-align: right; font-variant-numeric: tabular-nums;}
table.bk td.warn {color: #b42318; font-weight: 700;}
table.bk td.ok {color: #067647; font-weight: 600;}
table.stmt {border-collapse: collapse; width: 100%; font-size: 0.95rem; border: 1px solid #cfd6e1;}
table.stmt caption {caption-side: top; background: #E84A27; color: #fff; font-weight: 700; font-size: 1.05rem;
                    padding: 8px 12px; text-align: left;}
table.stmt td {padding: 5px 12px; border: none;}
table.stmt td.num {text-align: right; font-variant-numeric: tabular-nums;}
table.stmt tr.section td {background: #13294B; color: #fff; font-weight: 700;}
table.stmt tr.line td:first-child {padding-left: 28px;}
table.stmt tr.subtotal td {font-weight: 700; border-top: 1px solid #98a2b3;}
table.stmt tr.total td {font-weight: 700; background: #eef2f7; border-top: 2px solid #13294B;}
</style>
"""


# --- hosted demo: one private database per visitor ---------------------------
# Locally the app keeps a single persistent database (data/bookkeeper.db). On a shared public
# deployment every visitor would otherwise post into, and reset, the same books. In isolated
# mode each browser session gets its own SQLite file, identified by a random id kept in the
# URL (?s=...) so a page refresh returns to the same workspace.
SESSION_DIR = Path(tempfile.gettempdir()) / "te566-bookkeeper-sessions"
SESSION_MAX_AGE_SECONDS = 24 * 60 * 60
_WORKSPACE_ID = re.compile(r"[0-9a-f]{32}")


def isolated_sessions() -> bool:
    """True on Streamlit Community Cloud, or when BOOKKEEPER_ISOLATE_SESSIONS is set."""
    flag = os.environ.get("BOOKKEEPER_ISOLATE_SESSIONS")
    if flag is not None:
        return flag.strip().lower() in ("1", "true", "yes", "on")
    if os.environ.get("BOOKKEEPER_DB"):
        return False
    return Path(__file__).resolve().as_posix().startswith("/mount/src/")  # Community Cloud checkout path


def workspace_id() -> str:
    """This session's workspace id: reuse a well-formed one from the URL, otherwise create one."""
    sid = st.session_state.get("_workspace")
    if not sid:
        candidate = str(st.query_params.get("s", ""))
        sid = candidate if _WORKSPACE_ID.fullmatch(candidate) else uuid.uuid4().hex
        st.session_state["_workspace"] = sid
    return sid


def _prune_old_workspaces():
    cutoff = time.time() - SESSION_MAX_AGE_SECONDS
    for path in SESSION_DIR.glob("*.db*"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass  # another session removed it first


def conn():
    """One SQLite connection per script run; the demo business is seeded on first launch."""
    if isolated_sessions():
        path = SESSION_DIR / f"{workspace_id()}.db"
        if not path.exists():
            SESSION_DIR.mkdir(parents=True, exist_ok=True)
            _prune_old_workspaces()
        connection = db.connect(path)
    else:
        connection = db.connect()
    seed.ensure_initialized(connection)
    return connection


def css():
    st.markdown(CSS, unsafe_allow_html=True)


# --- flash messages survive the rerun that follows a posted transaction -----
def plain(text: str) -> str:
    """Stop Streamlit markdown from reading a pair of dollar signs as LaTeX."""
    return text.replace("$", "\\$")


def flash(message: str, kind: str = "success"):
    st.session_state.setdefault("_flash", []).append((kind, plain(message)))


def show_flash():
    for kind, message in st.session_state.pop("_flash", []):
        getattr(st, kind)(message)


# --- idempotency: one token per rendered form, renewed only after a successful post
def form_token(name: str) -> str:
    return st.session_state.setdefault(f"_token_{name}", uuid.uuid4().hex)


def renew_token(name: str):
    st.session_state.pop(f"_token_{name}", None)


def run(action, message, token: str = None):
    """Execute a business action; show a clear error or flash success and rerun."""
    try:
        result = action()
    except (BusinessError, LedgerError, ValueError) as exc:
        st.error(plain(str(exc)))
        return None
    if token:
        renew_token(token)
    flash(message(result) if callable(message) else message)
    st.rerun()


# --- rendering ---------------------------------------------------------------
def table(headers, rows, numeric=(), classes=None, empty="No records yet."):
    """Render rows as an HTML table. `numeric` = right-aligned column indexes;
    `classes` = {(row, col): css class} for highlighting."""
    if not rows:
        st.caption(empty)
        return
    classes = classes or {}
    head = "".join(f'<th class="{"num" if i in numeric else ""}">{escape(str(h))}</th>' for i, h in enumerate(headers))
    body = []
    for r, row in enumerate(rows):
        cells = []
        for c, value in enumerate(row):
            cls = " ".join(filter(None, ["num" if c in numeric else "", classes.get((r, c), "")]))
            cells.append(f'<td class="{cls}">{escape(str(value))}</td>')
        body.append(f"<tr>{''.join(cells)}</tr>")
    st.markdown(f'<table class="bk"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>',
                unsafe_allow_html=True)


def statement(stmt: dict, subtitle: str = ""):
    rows = []
    for label, cents, kind in stmt["rows"]:
        amount = "" if cents is None else fmt(cents)
        span = ' colspan="2"' if cents is None else ""
        value_cell = "" if cents is None else f'<td class="num">{amount}</td>'
        rows.append(f'<tr class="{kind}"><td{span}>{escape(label)}</td>{value_cell}</tr>')
    caption = escape(stmt["title"]) + (f" &mdash; {escape(subtitle)}" if subtitle else "")
    st.markdown(f'<table class="stmt"><caption>{caption}</caption><tbody>{"".join(rows)}</tbody></table>',
                unsafe_allow_html=True)


def units(n) -> str:
    return f"{n:,}"


def unit_cost(cents) -> str:
    """Per-unit costs can be fractions of a cent under weighted-average costing."""
    text = f"{cents / 100:,.4f}".rstrip("0")
    whole, _, frac = text.partition(".")
    return f"${whole}.{frac.ljust(2, '0')}"


# --- generic add / edit form -------------------------------------------------
def record_form(key: str, fields, initial=None, submit_label="Save"):
    """Render a form from a field spec and return the cleaned values on submit, else None.

    fields: [(name, label, kind, options)] with kind in text / money / int / select.
    Money fields are named '<x>_cents' and are entered in dollars.
    """
    initial = initial or {}
    values = {}
    with st.form(key, clear_on_submit=initial == {}):
        cols = st.columns(2)
        for i, (name, label, kind, options) in enumerate(fields):
            col = cols[i % 2]
            current = initial.get(name)
            if kind == "text":
                values[name] = col.text_input(label, value=current or "", key=f"{key}_{name}")
            elif kind == "money":
                values[name] = col.number_input(label, min_value=0.0, step=0.01, format="%.2f",
                                                value=(current or 0) / 100, key=f"{key}_{name}")
            elif kind == "int":
                values[name] = col.number_input(label, min_value=0, step=1, value=int(current or 0),
                                                key=f"{key}_{name}")
            elif kind == "select":
                labels = list(options.keys())
                index = list(options.values()).index(current) if name in initial else 0
                values[name] = options[col.selectbox(label, labels, index=index, key=f"{key}_{name}")]
        submitted = st.form_submit_button(submit_label, type="primary")
    if not submitted:
        return None
    for name, _, kind, _ in fields:
        if kind == "money":
            values[name] = to_cents(values[name])
    return values
