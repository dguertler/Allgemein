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


def _logo_tag(path: Path, width: int = 130) -> str:
    if not path.exists():
        return ""
    b64 = base64.b64encode(path.read_bytes()).decode()
    ext = path.suffix.lstrip(".")
    return (
        f'<img src="data:image/{ext};base64,{b64}" '
        f'style="width:{width}px;background:#fff;padding:4px 6px;'
        f'border-radius:5px;object-fit:contain;">'
    )


def _combined_logo_bytes(paths: list, height: int = 88) -> bytes | None:
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


# ── Logos: sidebar only (via st.logo, double size) ────────────────────────
_logo_bytes = _combined_logo_bytes([ASSETS / "goertz_logo.png", ASSETS / "papperts_logo.png"], height=88)
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
/* Centered pretzel loading spinner */
[data-testid="stStatusWidget"] {
    position: fixed !important;
    top: 50% !important;
    left: 50% !important;
    transform: translate(-50%, -50%) !important;
    z-index: 9999 !important;
    background: #fff !important;
    border-radius: 20px !important;
    padding: 24px 36px !important;
    box-shadow: 0 8px 40px rgba(0, 0, 0, 0.25) !important;
    display: flex !important;
    flex-direction: column !important;
    align-items: center !important;
    gap: 8px !important;
    min-width: 160px !important;
}
[data-testid="stStatusWidget"] > * {
    display: none !important;
}
[data-testid="stStatusWidget"]::before {
    content: "🥨";
    font-size: 3rem;
    display: inline-block !important;
    animation: brezel-spin 1.5s linear infinite;
    line-height: 1;
}
[data-testid="stStatusWidget"]::after {
    content: "Loading...";
    font-size: 1rem;
    font-weight: 600;
    color: #555;
    display: inline-block !important;
    letter-spacing: 0.05em;
}
@keyframes brezel-spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
}
</style>
""", unsafe_allow_html=True)
else:
    with st.sidebar:
        g = _logo_tag(ASSETS / "goertz_logo.png")
        p_tag = _logo_tag(ASSETS / "papperts_logo.png")
        if g or p_tag:
            st.markdown(
                f'<div style="display:flex;gap:10px;align-items:center;padding:6px 0 4px 0;">{g}{p_tag}</div>',
                unsafe_allow_html=True,
            )
            st.divider()

# ── Sidebar: Firma, Budgetjahr, Basiszeitraum ──────────────────────────────
from ui.session import get_gmbh, get_budgetjahr
from datetime import date, timedelta


def _base_label(planjahr: int) -> str:
    today = date.today()
    stichtag = date(today.year, 1, 1) if planjahr <= today.year else today
    last = stichtag.replace(day=1) - timedelta(days=1)
    ey, em = last.year, last.month
    m = em - 11
    y = ey
    while m <= 0:
        m += 12
        y -= 1
    de = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
          "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]
    return f"{de[m - 1]} {y} – {de[em - 1]} {ey}"


_gmbh = get_gmbh()
if _gmbh:
    _planjahr = get_budgetjahr()
    st.sidebar.markdown(
        f"<div style='padding:4px 0 12px 0;font-size:0.88rem;line-height:1.7;'>"
        f"<b>Firma:</b> {_gmbh}<br>"
        f"<b>Budgetjahr:</b> {_planjahr}<br>"
        f"<b>Basiszeitraum:</b> {_base_label(_planjahr)}"
        f"</div>",
        unsafe_allow_html=True,
    )

# ── Navigation ─────────────────────────────────────────────────────────────
pages = st.navigation({
    " ": [
        st.Page(str(BASE / "ui/pages/1_Startseite.py"),
                title="Startseite", icon=":material/home:"),
    ],
    "Input & Stammdaten": [
        st.Page(str(BASE / "ui/pages/2_Filialen.py"),
                title="Filialen",              icon=":material/store:"),
        st.Page(str(BASE / "ui/pages/3_Daten_Import.py"),
                title="Umsatz-Import",          icon=":material/upload_file:"),
        st.Page(str(BASE / "ui/pages/8_Feiertage_Import.py"),
                title="Feiertage laden",        icon=":material/event:"),
        st.Page(str(BASE / "ui/pages/9_Oeffnungstage.py"),
                title="Öffnungstage",           icon=":material/calendar_month:"),
        st.Page(str(BASE / "ui/pages/12_Schulfilialen.py"),
                title="Schulfilialen",          icon=":material/school:"),
        st.Page(str(BASE / "ui/pages/11_Preisanpassung.py"),
                title="Preisanpassung je Monat", icon=":material/trending_up:"),
    ],
    "Berechnung & Validierung": [
        st.Page(str(BASE / "ui/pages/6_Planung.py"),
                title="Planung ausführen",      icon=":material/calculate:"),
        st.Page(str(BASE / "ui/pages/10_Herleitung.py"),
                title="Herleitung",             icon=":material/account_tree:"),
        st.Page(str(BASE / "ui/pages/7_Planungsgenauigkeit.py"),
                title="Planungsgenauigkeit",    icon=":material/analytics:"),
    ],
})
pages.run()
