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


def _combined_logo(paths: list, height: int = 48) -> bytes | None:
    try:
        from PIL import Image, ImageDraw
        import io

        imgs = [Image.open(p).convert("RGBA") for p in paths if p.exists()]
        if not imgs:
            return None

        pad_x, pad_y, gap, radius = 6, 4, 12, 6
        inner_h = height - 2 * pad_y

        resized = []
        for img in imgs:
            ratio = inner_h / img.height
            new_w = max(1, int(img.width * ratio))
            resized.append(img.resize((new_w, inner_h), Image.LANCZOS))

        total_inner_w = sum(i.width for i in resized) + gap * (len(resized) - 1)
        total_w = total_inner_w + 2 * pad_x

        canvas = Image.new("RGBA", (total_w, height), (0, 0, 0, 0))

        # Rounded white background
        bg = Image.new("RGBA", (total_w, height), (255, 255, 255, 255))
        mask = Image.new("L", (total_w, height), 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle([0, 0, total_w - 1, height - 1], radius=radius, fill=255)
        canvas.paste(bg, mask=mask)

        # Paste logos
        x = pad_x
        for img in resized:
            canvas.paste(img, (x, pad_y), img)
            x += img.width + gap

        buf = io.BytesIO()
        canvas.save(buf, "PNG")
        return buf.getvalue()
    except Exception:
        return None


logo_bytes = _combined_logo([ASSETS / "goertz_logo.png", ASSETS / "papperts_logo.png"])
if logo_bytes:
    st.logo(logo_bytes, size="large")

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
    st.Page(str(BASE / "ui/pages/7_Planungsgenauigkeit.py"),
            title="Planungsgenauigkeit",           icon=":material/analytics:"),
])
pages.run()
