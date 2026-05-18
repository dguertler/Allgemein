"""Streamlit entry point with explicit page navigation."""
import streamlit as st
from pathlib import Path
import base64
import sys

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

st.set_page_config(
    page_title="Umsatzplanung",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Sidebar: company logos ─────────────────────────────────────────────────
ASSETS = BASE / "ui" / "assets"


def _logo_tag(path: Path, width: int = 88) -> str:
    if not path.exists():
        return ""
    b64 = base64.b64encode(path.read_bytes()).decode()
    ext = path.suffix.lstrip(".")
    return (
        f'<img src="data:image/{ext};base64,{b64}" '
        f'style="width:{width}px;background:#fff;padding:4px 6px;'
        f'border-radius:5px;object-fit:contain;">'
    )


with st.sidebar:
    g = _logo_tag(ASSETS / "goertz_logo.png")
    p = _logo_tag(ASSETS / "papperts_logo.png")

    if g or p:
        st.markdown(
            f'<div style="display:flex;gap:10px;align-items:center;'
            f'padding:6px 0 4px 0;">{g}{p}</div>',
            unsafe_allow_html=True,
        )
        st.divider()
    else:
        st.markdown(
            "<div style='text-align:center;padding:8px 0 12px 0;"
            "font-size:13px;color:#666;letter-spacing:.05em;'>"
            "FILIALUMSATZPLANUNG</div>",
            unsafe_allow_html=True,
        )
        st.divider()

# ── Navigation ─────────────────────────────────────────────────────────────
pages = st.navigation([
    st.Page(str(BASE / "ui/pages/1_Startseite.py"),
            title="Startseite",                   icon=":material/home:"),
    st.Page(str(BASE / "ui/pages/2_Filialen.py"),
            title="Filialen",                     icon=":material/store:"),
    st.Page(str(BASE / "ui/pages/3_Daten_Import.py"),
            title="Daten Import",                 icon=":material/upload_file:"),
    st.Page(str(BASE / "ui/pages/4_Parameter.py"),
            title="Parameter",                    icon=":material/tune:"),
    st.Page(str(BASE / "ui/pages/5_Neue_Filialen.py"),
            title="Neue Filialen & Lieferkunden", icon=":material/add_business:"),
    st.Page(str(BASE / "ui/pages/6_Planung.py"),
            title="Planung ausführen",             icon=":material/calculate:"),
])
pages.run()
