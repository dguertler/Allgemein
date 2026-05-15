"""Streamlit entry point with explicit page navigation."""
import streamlit as st
from pathlib import Path
import sys

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

st.set_page_config(
    page_title="Filialumsatzplanung",
    page_icon="🥐",
    layout="wide",
    initial_sidebar_state="expanded",
)

pages = st.navigation([
    st.Page(str(BASE / "ui/pages/1_Startseite.py"),     title="🏠 Startseite"),
    st.Page(str(BASE / "ui/pages/2_Filialen.py"),        title="🏪 Filialen"),
    st.Page(str(BASE / "ui/pages/3_Daten_Import.py"),    title="📥 Daten Import"),
    st.Page(str(BASE / "ui/pages/4_Parameter.py"),       title="⚙️ Parameter"),
    st.Page(str(BASE / "ui/pages/5_Neue_Filialen.py"),   title="🆕 Neue Filialen & Lieferkunden"),
    st.Page(str(BASE / "ui/pages/6_Planung.py"),         title="▶️ Planung ausführen"),
])
pages.run()
