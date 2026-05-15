"""Shared session-state helpers for Streamlit."""
import sqlite3
import streamlit as st
from pathlib import Path
from database.schema import init_db, get_db_path

DATA_DIR = Path(__file__).parent.parent / "data"


def get_conn() -> sqlite3.Connection | None:
    if "db_conn" not in st.session_state or st.session_state.db_conn is None:
        return None
    return st.session_state.db_conn


def get_gmbh() -> str:
    return st.session_state.get("gmbh_name", "")


def open_db(gmbh_name: str):
    path = get_db_path(gmbh_name, str(DATA_DIR))
    conn = init_db(path)
    st.session_state.db_conn = conn
    st.session_state.gmbh_name = gmbh_name
    st.session_state.db_path = str(path)


def require_db():
    """Show a warning and stop if no database is selected."""
    if not get_conn():
        st.warning("Bitte zuerst eine GmbH-Datenbank öffnen oder anlegen (Startseite).")
        st.stop()
