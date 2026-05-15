"""Streamlit entry point — redirect to first page."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))

st.set_page_config(
    page_title="Filialumsatzplanung",
    page_icon="🥐",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🥐 Filialumsatzplanung")
st.markdown("""
Willkommen im Filialumsatz-Planungssystem.

**Ablauf:**
1. **Startseite** — GmbH-Datenbank öffnen oder anlegen
2. **Filialen** — Stammdaten pflegen, Flags setzen
3. **Daten Import** — IST-Umsätze hochladen (CSV/Excel)
4. **Parameter** — Preiserhöhung, Feiertage, Ferien, Ramadan, Fasching
5. **Neue Filialen & Lieferkunden** — Monatliche Planwerte eingeben
6. **Planung ausführen** — Berechnung starten & Excel herunterladen

---
Bitte links **Startseite** auswählen, um zu beginnen.
""")
