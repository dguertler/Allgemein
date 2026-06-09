"""Streamlit entry point with explicit page navigation."""
import streamlit as st
from pathlib import Path
import sys

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

st.set_page_config(
    page_title="Umsatzplanung",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

ASSETS = BASE / "ui" / "assets"


import base64


def _logo_tag(path: Path, width: int = 65) -> str:
    if not path.exists():
        return ""
    b64 = base64.b64encode(path.read_bytes()).decode()
    ext = path.suffix.lstrip(".")
    return (
        f'<img src="data:image/{ext};base64,{b64}" '
        f'style="width:{width}px;background:#fff;padding:4px 6px;'
        f'border-radius:5px;object-fit:contain;">'
    )


def _combined_logo_bytes(paths: list, height: int = 44) -> bytes | None:
    """Build a combined PNG for st.logo() – plain white background, no transparency."""
    try:
        from PIL import Image
        import io

        imgs = [Image.open(p).convert("RGBA") for p in paths if p.exists()]
        if not imgs:
            return None

        gap = 10
        resized = []
        for img in imgs:
            ratio = height / img.height
            new_w = max(1, int(img.width * ratio))
            resized.append(img.resize((new_w, height), Image.LANCZOS))

        total_w = sum(i.width for i in resized) + gap * (len(resized) - 1)
        canvas = Image.new("RGB", (total_w, height), (255, 255, 255))
        x = 0
        for img in resized:
            canvas.paste(img, (x, 0), img)
            x += img.width + gap

        buf = io.BytesIO()
        canvas.save(buf, "PNG")
        return buf.getvalue()
    except Exception:
        return None


# ── Logos: st.logo() places above nav; CSS replicates the old HTML styling ─
_logo_bytes = _combined_logo_bytes([ASSETS / "goertz_logo.png", ASSETS / "papperts_logo.png"])
if _logo_bytes:
    st.logo(_logo_bytes, size="large")
    st.markdown("""
<style>
[data-testid="stSidebarHeader"] img {
    background: #ffffff !important;
    padding: 4px 6px !important;
    border-radius: 5px !important;
    object-fit: contain !important;
}
</style>
""", unsafe_allow_html=True)
else:
    # Fallback: HTML logos in sidebar when Pillow unavailable
    with st.sidebar:
        g = _logo_tag(ASSETS / "goertz_logo.png")
        p_tag = _logo_tag(ASSETS / "papperts_logo.png")
        if g or p_tag:
            st.markdown(
                f'<div style="display:flex;gap:10px;align-items:center;padding:6px 0 4px 0;">{g}{p_tag}</div>',
                unsafe_allow_html=True,
            )
            st.divider()

# ── Navigation ─────────────────────────────────────────────────────────────
pages = st.navigation({
    " ": [
        st.Page(str(BASE / "ui/pages/1_Startseite.py"),
                title="Startseite", icon=":material/home:"),
    ],
    "Input & Stammdaten": [
        st.Page(str(BASE / "ui/pages/2_Filialen.py"),
                title="Filialen",        icon=":material/store:"),
        st.Page(str(BASE / "ui/pages/3_Daten_Import.py"),
                title="Umsatz-Import",    icon=":material/upload_file:"),
        st.Page(str(BASE / "ui/pages/9_Oeffnungstage.py"),
                title="Öffnungstage",    icon=":material/calendar_month:"),
        st.Page(str(BASE / "ui/pages/8_Feiertage_Import.py"),
                title="Feiertage laden", icon=":material/event:"),
    ],
    "Annahmen": [
        st.Page(str(BASE / "ui/pages/4_Parameter.py"),
                title="Parameter",        icon=":material/tune:"),
        st.Page(str(BASE / "ui/pages/5_Neue_Filialen.py"),
                title="Neue Filialen",    icon=":material/add_business:"),
    ],
    "Berechnung & Validierung": [
        st.Page(str(BASE / "ui/pages/6_Planung.py"),
                title="Planung ausführen",   icon=":material/calculate:"),
        st.Page(str(BASE / "ui/pages/10_Herleitung.py"),
                title="Herleitung",          icon=":material/account_tree:"),
        st.Page(str(BASE / "ui/pages/7_Planungsgenauigkeit.py"),
                title="Planungsgenauigkeit", icon=":material/analytics:"),
    ],
})
pages.run()
