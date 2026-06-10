"""Herleitung der Budgetberechnung — additive Effektzerlegung je Ebene."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import get_conn, get_gmbh, require_db, get_budgetjahr
import pandas as pd
import io

require_db()
conn = get_conn()
gmbh = get_gmbh()
planjahr = get_budgetjahr()

st.title("Herleitung der Budgetberechnung")

df_all = pd.read_sql(
    "SELECT * FROM planung WHERE CAST(strftime('%Y', datum) AS INTEGER)=?",
    conn, params=(planjahr,),
)

if df_all.empty:
    st.info(
        f"Noch keine Planungsdaten für {planjahr} vorhanden. "
        "Bitte zuerst unter **Planung ausführen** eine Berechnung starten."
    )
    st.stop()

eff_cols = ["ist_vj", "eff_oeffnung", "eff_verteilung", "eff_wochentag",
            "eff_preis", "eff_ferien", "eff_feiertag", "eff_norm", "budget"]
for col in eff_cols:
    if col not in df_all.columns:
        df_all[col] = 0.0
    df_all[col] = pd.to_numeric(df_all[col], errors="coerce").fillna(0.0)

if "budget" not in df_all.columns or df_all["budget"].sum() == 0:
    for alt in ["gesamt_plan", "tagesumsatz_plan"]:
        if alt in df_all.columns:
            df_all["budget"] = pd.to_numeric(df_all[alt], errors="coerce").fillna(0.0)
            break

df_all["datum"] = pd.to_datetime(df_all["datum"])
if "bundesland" not in df_all.columns or df_all["bundesland"].isna().all():
    bl_map = {r[0]: r[1] for r in conn.execute("SELECT fil_nr, bundesland FROM filialen").fetchall()}
    df_all["bundesland"] = df_all["fil_nr"].map(bl_map).fillna("?")

# ── Steuerung ──────────────────────────────────────────────────────────────
c1, c2 = st.columns(2)
with c1:
    zeit_ebene = st.selectbox("Zeit-Ebene", ["Tag", "Woche", "Monat", "Jahr"], index=2)
with c2:
    entity_ebene = st.selectbox("Aggregations-Ebene", ["Filiale", "Bundesland", "Gesamt"])

cf1, cf2 = st.columns(2)
with cf1:
    fil_filter = st.multiselect(
        "Filtern auf Filiale(n) (leer = alle)",
        sorted(df_all["fil_nr"].unique()),
    )
with cf2:
    bl_filter = st.multiselect(
        "Filtern auf Bundesland (leer = alle)",
        sorted(df_all["bundesland"].dropna().unique()),
    )

if fil_filter:
    df_all = df_all[df_all["fil_nr"].isin(fil_filter)]
if bl_filter:
    df_all = df_all[df_all["bundesland"].isin(bl_filter)]

# ── Zeit-Gruppierung ────────────────────────────────────────────────────────
if zeit_ebene == "Tag":
    df_all["Zeit"] = df_all["datum"].dt.strftime("%d.%m.%Y")
    df_all["_sort"] = df_all["datum"]
elif zeit_ebene == "Woche":
    iso = df_all["datum"].dt.isocalendar()
    df_all["Zeit"] = "KW " + iso["week"].astype(str).str.zfill(2) + "/" + iso["year"].astype(str)
    df_all["_sort"] = df_all["datum"].dt.to_period("W").apply(lambda p: p.start_time)
elif zeit_ebene == "Monat":
    MON = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]
    df_all["Zeit"] = df_all["datum"].dt.month.map(lambda m: MON[m - 1]) + " " + df_all["datum"].dt.year.astype(str)
    df_all["_sort"] = df_all["datum"].dt.to_period("M").apply(lambda p: p.start_time)
else:
    df_all["Zeit"] = df_all["datum"].dt.year.astype(str)
    df_all["_sort"] = df_all["datum"].dt.year

group_keys = ["Zeit", "_sort"]
if entity_ebene == "Filiale":
    group_keys = ["fil_nr"] + group_keys
elif entity_ebene == "Bundesland":
    group_keys = ["bundesland"] + group_keys

agg = (df_all.groupby([k for k in group_keys if k != "_sort"], as_index=False)
       .agg({**{c: "sum" for c in eff_cols}, "_sort": "min"})
       .sort_values([k for k in (["_sort"] if entity_ebene == "Gesamt"
                                  else [group_keys[0], "_sort"])]))

agg["Δ €"] = agg["budget"] - agg["ist_vj"]
agg["Δ %"] = agg.apply(lambda x: round(x["Δ €"] / x["ist_vj"] * 100, 1) if x["ist_vj"] else None, axis=1)

rename = {
    "fil_nr": "Filiale", "bundesland": "Bundesland",
    "ist_vj": "IST Basis", "eff_oeffnung": "+ Öffnung", "eff_verteilung": "+ Verteilung",
    "eff_wochentag": "+ Wochentag", "eff_preis": "+ Preis", "eff_ferien": "+ Ferien",
    "eff_feiertag": "+ Feiertag", "eff_norm": "+ Norm.", "budget": "= Budget",
}
disp = agg.drop(columns=["_sort"]).rename(columns=rename)

lead = [c for c in ["Filiale", "Bundesland", "Zeit"] if c in disp.columns]
ordered = lead + ["IST Basis", "+ Öffnung", "+ Verteilung", "+ Wochentag", "+ Preis",
                  "+ Ferien", "+ Feiertag", "+ Norm.", "= Budget", "Δ €", "Δ %"]
disp = disp[[c for c in ordered if c in disp.columns]]

# ── Kennzahlen ─────────────────────────────────────────────────────────────
tot_vj = agg["ist_vj"].sum()
tot_bud = agg["budget"].sum()
m1, m2, m3, m4 = st.columns(4)

def _de(val) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "–"
    return f"{float(val):,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")

m1.metric("IST Basis", f"{_de(tot_vj)} €")
m2.metric("Budget", f"{_de(tot_bud)} €")
m3.metric("Δ €", f"{'+' if tot_bud >= tot_vj else ''}{_de(tot_bud - tot_vj)} €")
m4.metric("Δ %", f"{(tot_bud - tot_vj) / tot_vj * 100:+.1f} %" if tot_vj else "–")

st.caption(
    "Lesart: **IST Basis** = Umsatz des korrespondierenden Basistags. "
    "Jede `+`-Spalte zeigt den additiven Effekt in €. Summe ergibt **= Budget**."
)
st.divider()

# ── Tabelle ─────────────────────────────────────────────────────────────────
num_cols = ["IST Basis", "+ Öffnung", "+ Verteilung", "+ Wochentag", "+ Preis",
            "+ Ferien", "+ Feiertag", "+ Norm.", "= Budget", "Δ €"]

def _fmt_de(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    return f"{float(val):,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")

styled = disp.style.format({c: _fmt_de for c in num_cols if c in disp.columns},
                            na_rep="")
st.dataframe(styled, use_container_width=True, hide_index=True, height=560)

# ── Excel-Export ────────────────────────────────────────────────────────────
st.divider()
buf = io.BytesIO()
with pd.ExcelWriter(buf, engine="openpyxl") as writer:
    disp.to_excel(writer, index=False, sheet_name="Herleitung")
    from openpyxl.styles import Font
    ws = writer.sheets["Herleitung"]
    for cell in ws[1]:
        cell.font = Font(bold=True)
st.download_button(
    "📥 Excel herunterladen",
    data=buf.getvalue(),
    file_name=f"Herleitung_{planjahr}_{zeit_ebene}_{entity_ebene}_{gmbh.replace(' ', '_')}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    type="primary",
)
