"""Startseite: Firmendatenbank öffnen/anlegen und Budgetjahr wählen."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import DATA_DIR, open_db, get_gmbh, get_budgetjahr, set_budgetjahr
from datetime import date

st.title("Startseite")
st.subheader("Firmendatenbank auswählen oder anlegen")

DATA_DIR.mkdir(parents=True, exist_ok=True)
existing = sorted(p.stem.replace("_", " ") for p in DATA_DIR.glob("*.db"))

col1, col2 = st.columns(2)

with col1:
    st.markdown("#### Bestehende Firma öffnen")
    if existing:
        choice = st.selectbox("Firma auswählen", existing)
        if st.button("Öffnen", key="open_btn"):
            open_db(choice)
            st.success(f"✅ Datenbank für **{choice}** geladen.")
            st.rerun()
    else:
        st.info("Noch keine Datenbanken vorhanden. Bitte rechts eine neue Firma anlegen.")

with col2:
    st.markdown("#### Neue Firma anlegen")
    new_name = st.text_input("Firmenname", placeholder='z.B. "Bäckerei RLP GmbH"')
    if st.button("Anlegen", key="new_btn") and new_name.strip():
        open_db(new_name.strip())
        st.success(f"✅ Neue Datenbank für **{new_name.strip()}** angelegt.")
        st.rerun()

if get_gmbh():
    st.divider()
    st.success(f"Aktive Firma: **{get_gmbh()}**")

    st.subheader("Budgetjahr")
    bj = st.number_input(
        "Budgetjahr auswählen",
        min_value=2024,
        max_value=2040,
        value=get_budgetjahr(),
        step=1,
        key="budgetjahr_input",
        help="Das Budgetjahr bestimmt, für welches Jahr geplant wird. Standard: nächstes Jahr.",
    )
    if int(bj) != get_budgetjahr():
        set_budgetjahr(int(bj))
        st.rerun()

    st.info(
        f"Aktives Budgetjahr: **{get_budgetjahr()}** — alle Berechnungen, "
        "Feiertage und Exporte beziehen sich auf dieses Jahr."
    )
    st.caption("Weiter mit der Navigation links.")
