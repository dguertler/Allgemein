"""Start page: open / create a GmbH database."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import DATA_DIR, open_db, get_gmbh

st.set_page_config(page_title="Umsatzplanung – Start", page_icon="🥐", layout="wide")

st.title("🥐 Filialumsatzplanung")
st.subheader("GmbH-Datenbank auswählen oder anlegen")

DATA_DIR.mkdir(parents=True, exist_ok=True)
existing = sorted(p.stem.replace("_", " ") for p in DATA_DIR.glob("*.db"))

col1, col2 = st.columns(2)

with col1:
    st.markdown("#### Bestehende GmbH öffnen")
    if existing:
        choice = st.selectbox("GmbH auswählen", existing)
        if st.button("Öffnen", key="open_btn"):
            open_db(choice)
            st.success(f"✅ Datenbank für **{choice}** geladen.")
            st.rerun()
    else:
        st.info("Noch keine Datenbanken vorhanden. Bitte rechts eine neue GmbH anlegen.")

with col2:
    st.markdown("#### Neue GmbH anlegen")
    new_name = st.text_input("GmbH-Name (z.B. Bäckerei RLP GmbH)")
    if st.button("Anlegen", key="new_btn") and new_name.strip():
        open_db(new_name.strip())
        st.success(f"✅ Neue Datenbank für **{new_name.strip()}** angelegt.")
        st.rerun()

if get_gmbh():
    st.divider()
    st.success(f"Aktive GmbH: **{get_gmbh()}**")
    st.caption("Weiter mit der Navigation links.")
