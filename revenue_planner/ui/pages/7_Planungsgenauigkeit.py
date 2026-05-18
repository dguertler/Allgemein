"""Plan accuracy page: compare budget vs prior-year actuals and current-year actuals per day."""
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

# ── Load planung data ──────────────────────────────────────────────────────
if ansicht == "Einzelne Filiale" and selected_fil:
    plan_rows = conn.execute(
        "SELECT * FROM planung WHERE CAST(strftime('%Y', datum) AS INTEGER)=? AND fil_nr=? ORDER BY fil_nr, datum",
        (planjahr, selected_fil)
    ).fetchall()
    ist_rows = conn.execute(
        "SELECT fil_nr, datum, umsatz FROM ist_umsatz WHERE fil_nr=? AND datum LIKE ?",
        (selected_fil, f"{planjahr}-%")
    ).fetchall()
else:
    plan_rows = conn.execute(
        "SELECT * FROM planung WHERE CAST(strftime('%Y', datum) AS INTEGER)=? ORDER BY fil_nr, datum",
        (planjahr,)
    ).fetchall()
    ist_rows = conn.execute(
        "SELECT fil_nr, datum, umsatz FROM ist_umsatz WHERE datum LIKE ?",
        (f"{planjahr}-%",)
    ).fetchall()

if not plan_rows:
    st.warning("Keine Daten für die gewählte Auswahl.")
    st.stop()

# IST current year lookup: (fil_nr, datum) → umsatz
ist_lookup = {(r["fil_nr"], r["datum"]): r["umsatz"] for r in ist_rows}
has_ist_current = len(ist_lookup) > 0

WOCHENTAGE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

df = pd.DataFrame([{
    "Filiale":   r["fil_nr"],
    "Datum":     r["datum"],
    "Wochentag": WOCHENTAGE[r["wochentag"]] if r["wochentag"] is not None else "",
    "Tagestyp":  r["tagestyp"] or "normal",
    "Info":      " / ".join(filter(None, [r["feiertag_name"] or "", r["ferien_art"] or ""])),
    "IST VJ €":  r["ist_vj"] or 0.0,
    "Budget €":  r["tagesumsatz_plan"] or 0.0,
    "IST €":     ist_lookup.get((r["fil_nr"], r["datum"])),
} for r in plan_rows])

# ── Aggregate if "Gesamt aggregiert" ──────────────────────────────────────
if ansicht == "Gesamt aggregiert":
    df = (df.groupby("Datum", as_index=False)
            .agg({
                "Wochentag": "first",
                "Tagestyp":  "first",
                "Info":      lambda x: " / ".join(filter(None, x.unique())),
                "IST VJ €":  "sum",
                "Budget €":  "sum",
                "IST €":     lambda x: x.sum() if x.notna().any() else None,
            }))

# Abweichung IST vs Budget (only where current IST exists)
df["Abw. €"] = df.apply(
    lambda x: round(x["IST €"] - x["Budget €"], 2) if pd.notna(x["IST €"]) else None,
    axis=1,
)
df["Abw. %"] = df.apply(
    lambda x: round((x["Abw. €"] / x["Budget €"] * 100), 1)
    if pd.notna(x.get("Abw. €")) and x["Budget €"] != 0 else None,
    axis=1,
)

# ── Summary metrics ────────────────────────────────────────────────────────
total_ist_vj  = df["IST VJ €"].sum()
total_budget  = df["Budget €"].sum()
total_ist_cur = df["IST €"].sum() if has_ist_current else None

m_cols = st.columns(4)
m_cols[0].metric("IST Vorjahr", f"{total_ist_vj:,.0f} €")
m_cols[1].metric("Budget",      f"{total_budget:,.0f} €")
if has_ist_current and total_ist_cur is not None:
    abw_eur = total_ist_cur - total_budget
    abw_pct = (abw_eur / total_budget * 100) if total_budget != 0 else 0.0
    m_cols[2].metric("IST aktuell",     f"{total_ist_cur:,.0f} €")
    m_cols[3].metric("Abw. IST/Budget", f"{abw_eur:+,.0f} € ({abw_pct:+.1f} %)")
else:
    m_cols[2].metric("IST aktuell",     "– (noch kein Import)")
    m_cols[3].metric("Abw. IST/Budget", "–")

st.divider()

# ── Table ──────────────────────────────────────────────────────────────────
euro_fmt = st.column_config.NumberColumn(format="%.0f €")
pct_fmt  = st.column_config.NumberColumn(format="%.1f %%")

if ansicht == "Gesamt aggregiert":
    display_cols = ["Datum", "Wochentag", "Tagestyp", "Info",
                    "IST VJ €", "Budget €", "IST €", "Abw. €", "Abw. %"]
else:
    display_cols = ["Filiale", "Datum", "Wochentag", "Tagestyp", "Info",
                    "IST VJ €", "Budget €", "IST €", "Abw. €", "Abw. %"]

st.dataframe(
    df[display_cols],
    use_container_width=True,
    hide_index=True,
    column_config={
        "IST VJ €": euro_fmt,
        "Budget €": euro_fmt,
        "IST €":    euro_fmt,
        "Abw. €":   euro_fmt,
        "Abw. %":   pct_fmt,
    },
    height=500,
)

# ── Excel export ───────────────────────────────────────────────────────────
st.divider()
with st.spinner("Excel wird erstellt…"):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df[display_cols].to_excel(writer, index=False, sheet_name="Planungsgenauigkeit")
        ws = writer.sheets["Planungsgenauigkeit"]
        from openpyxl.styles import Font
        for cell in ws[1]:
            cell.font = Font(bold=True)
    excel_bytes = buf.getvalue()

suffix = f"_{selected_fil}" if selected_fil else f"_{ansicht.replace(' ', '_')}"
st.download_button(
    label="📥 Excel herunterladen",
    data=excel_bytes,
    file_name=f"Planungsgenauigkeit_{planjahr}{suffix}_{gmbh.replace(' ', '_')}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    type="primary",
)
