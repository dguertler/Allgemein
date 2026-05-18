"""Plan accuracy page: compare planned vs prior-year actuals per day."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import get_conn, get_gmbh, require_db
import pandas as pd
import io

require_db()
conn = get_conn()
gmbh = get_gmbh()
st.title("Planungsgenauigkeit")
st.caption(f"Firma: **{gmbh}**")

# ── Check if any plan data exists ──────────────────────────────────────────
jahre = [r[0] for r in conn.execute(
    "SELECT DISTINCT CAST(strftime('%Y', datum) AS INTEGER) FROM planung ORDER BY 1 DESC"
).fetchall()]

if not jahre:
    st.info("Noch keine Planungsdaten vorhanden. Bitte zuerst unter **Planung ausführen** eine Planung berechnen.")
    st.stop()

# ── Controls ───────────────────────────────────────────────────────────────
col_a, col_b, col_c = st.columns([1, 2, 2])

with col_a:
    planjahr = st.selectbox("Planjahr", jahre)

with col_b:
    ansicht = st.radio(
        "Ansicht",
        ["Alle Filialen", "Einzelne Filiale", "Gesamt aggregiert"],
        horizontal=True,
    )

all_filialen = [r[0] for r in conn.execute(
    "SELECT DISTINCT fil_nr FROM planung WHERE CAST(strftime('%Y', datum) AS INTEGER)=? ORDER BY fil_nr",
    (planjahr,)
).fetchall()]

with col_c:
    if ansicht == "Einzelne Filiale":
        selected_fil = st.selectbox("Filiale", all_filialen)
    else:
        selected_fil = None

# ── Load data ──────────────────────────────────────────────────────────────
if ansicht == "Einzelne Filiale" and selected_fil:
    rows = conn.execute(
        "SELECT * FROM planung WHERE CAST(strftime('%Y', datum) AS INTEGER)=? AND fil_nr=? ORDER BY fil_nr, datum",
        (planjahr, selected_fil)
    ).fetchall()
else:
    rows = conn.execute(
        "SELECT * FROM planung WHERE CAST(strftime('%Y', datum) AS INTEGER)=? ORDER BY fil_nr, datum",
        (planjahr,)
    ).fetchall()

if not rows:
    st.warning("Keine Daten für die gewählte Auswahl.")
    st.stop()

WOCHENTAGE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

df = pd.DataFrame([{
    "Filiale":       r["fil_nr"],
    "Datum":         r["datum"],
    "Wochentag":     WOCHENTAGE[r["wochentag"]] if r["wochentag"] is not None else "",
    "Tagestyp":      r["tagestyp"] or "normal",
    "Info":          " / ".join(filter(None, [r["feiertag_name"] or "", r["ferien_art"] or ""])),
    "IST VJ €":      r["ist_vj"] or 0.0,
    "Laden Plan €":  r["tagesumsatz_plan"] or 0.0,
    "Liefer Plan €": r["liefer_plan"] or 0.0,
    "Gesamt Plan €": r["gesamt_plan"] or 0.0,
} for r in rows])

df["Abw. €"]  = df["Gesamt Plan €"] - df["IST VJ €"]
df["Abw. %"]  = df.apply(
    lambda x: (x["Abw. €"] / x["IST VJ €"] * 100) if x["IST VJ €"] != 0 else None,
    axis=1,
)

# ── Aggregate if "Gesamt aggregiert" ──────────────────────────────────────
if ansicht == "Gesamt aggregiert":
    df = (df.groupby("Datum", as_index=False)
            .agg({
                "Wochentag":     "first",
                "Tagestyp":      "first",
                "Info":          lambda x: " / ".join(filter(None, x.unique())),
                "IST VJ €":      "sum",
                "Laden Plan €":  "sum",
                "Liefer Plan €": "sum",
                "Gesamt Plan €": "sum",
            }))
    df["Abw. €"] = df["Gesamt Plan €"] - df["IST VJ €"]
    df["Abw. %"] = df.apply(
        lambda x: (x["Abw. €"] / x["IST VJ €"] * 100) if x["IST VJ €"] != 0 else None,
        axis=1,
    )
    display_cols = ["Datum", "Wochentag", "Tagestyp", "Info",
                    "IST VJ €", "Laden Plan €", "Liefer Plan €", "Gesamt Plan €",
                    "Abw. €", "Abw. %"]
else:
    display_cols = ["Filiale", "Datum", "Wochentag", "Tagestyp", "Info",
                    "IST VJ €", "Laden Plan €", "Liefer Plan €", "Gesamt Plan €",
                    "Abw. €", "Abw. %"]

# ── Summary metrics ────────────────────────────────────────────────────────
total_ist  = df["IST VJ €"].sum()
total_plan = df["Gesamt Plan €"].sum()
total_abw  = total_plan - total_ist
total_abw_pct = (total_abw / total_ist * 100) if total_ist != 0 else 0.0

m1, m2, m3, m4 = st.columns(4)
m1.metric("IST Vorjahr",   f"{total_ist:,.0f} €")
m2.metric("Plan Gesamt",   f"{total_plan:,.0f} €")
m3.metric("Abweichung €",  f"{total_abw:+,.0f} €")
m4.metric("Abweichung %",  f"{total_abw_pct:+.1f} %")

st.divider()

# ── Table display ──────────────────────────────────────────────────────────
euro_fmt   = st.column_config.NumberColumn(format="%.0f €")
pct_fmt    = st.column_config.NumberColumn(format="%.1f %%")

col_cfg = {
    "IST VJ €":      euro_fmt,
    "Laden Plan €":  euro_fmt,
    "Liefer Plan €": euro_fmt,
    "Gesamt Plan €": euro_fmt,
    "Abw. €":        euro_fmt,
    "Abw. %":        pct_fmt,
}

st.dataframe(
    df[display_cols],
    use_container_width=True,
    hide_index=True,
    column_config=col_cfg,
    height=500,
)

# ── Excel export ───────────────────────────────────────────────────────────
st.divider()
with st.spinner("Excel wird erstellt…"):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df[display_cols].to_excel(writer, index=False, sheet_name="Planungsgenauigkeit")
        ws = writer.sheets["Planungsgenauigkeit"]
        for col_cells in ws.iter_cols(min_row=1, max_row=1):
            for cell in col_cells:
                cell.font = __import__("openpyxl").styles.Font(bold=True)
    excel_bytes = buf.getvalue()

suffix = f"_{selected_fil}" if selected_fil else f"_{ansicht.replace(' ', '_')}"
st.download_button(
    label="📥 Excel herunterladen",
    data=excel_bytes,
    file_name=f"Planungsgenauigkeit_{planjahr}{suffix}_{gmbh.replace(' ', '_')}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    type="primary",
)
