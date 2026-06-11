"""Datumsmapping — zeigt und generiert das Mapping Plantag → Basisreferenztag."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import get_conn, get_gmbh, require_db, get_budgetjahr
import pandas as pd

require_db()
conn = get_conn()
st.title("Datumsmapping")
st.caption(f"Firma: **{get_gmbh()}**")

st.info(
    "Das Datumsmapping ordnet jedem Tag im Planjahr einen korrekten Referenztag "
    "im Basiszeitraum zu — wochentagsbasiert, mit Feiertags- und Feriensonderbehandlung. "
    "Es muss neu generiert werden, wenn Feiertage oder Ferien geändert wurden."
)

planjahr = get_budgetjahr()

col1, col2 = st.columns([2, 1])
with col1:
    st.subheader(f"Mapping für Planjahr {planjahr}")
with col2:
    if st.button("🔄 Mapping generieren", type="primary", use_container_width=True):
        with st.spinner("Generiere Datumsmapping…"):
            try:
                from planning.engine import PlanningEngine, PlanParams
                from planning.datumsmapping import generate_datumsmapping
                from ui.session import get_conn

                # Load params from DB
                par_row = conn.execute(
                    "SELECT * FROM parameter WHERE planjahr = ?", (planjahr,)
                ).fetchone()
                if par_row:
                    params = PlanParams(
                        planjahr=planjahr,
                        preiserhoehung_pct=float(par_row["preiserhoehung_pct"] or 0),
                        ferien_puffer_wochen=int(par_row["ferien_puffer_wochen"] or 2),
                    )
                else:
                    params = PlanParams(planjahr=planjahr)

                engine = PlanningEngine(conn, params)
                n = generate_datumsmapping(conn, planjahr, engine)
                st.success(f"{n:,} Mapping-Zeilen generiert.")
                st.rerun()
            except Exception as ex:
                st.error(f"Fehler: {ex}")

# Load existing mapping
df = pd.read_sql(
    "SELECT plan_datum, base_datum, plan_typ, bundesland, mapping_art "
    "FROM datumsmapping "
    "WHERE CAST(strftime('%Y', plan_datum) AS INTEGER) = ? "
    "ORDER BY plan_datum, bundesland",
    conn, params=(planjahr,)
)

if df.empty:
    st.warning("Kein Mapping vorhanden. Bitte zuerst generieren.")
    st.stop()

# Filters
WOCHENTAGE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
df["plan_datum_dt"] = pd.to_datetime(df["plan_datum"])
df["plan_wt"] = df["plan_datum_dt"].dt.weekday.map(lambda x: WOCHENTAGE[x])
df["base_datum_dt"] = pd.to_datetime(df["base_datum"])
df["base_wt"] = df["base_datum_dt"].dt.weekday.map(lambda x: WOCHENTAGE[x])
df["monat"] = df["plan_datum_dt"].dt.month

MONATE_DE = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
             "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]

fc1, fc2, fc3 = st.columns(3)
with fc1:
    monat_opts = sorted(df["monat"].unique().tolist())
    monat_sel = st.multiselect(
        "Monat", options=monat_opts,
        format_func=lambda m: MONATE_DE[m - 1],
        key="datumsmapping_monat"
    )
with fc2:
    bl_opts = sorted(df["bundesland"].unique().tolist())
    bl_sel = st.multiselect("Bundesland", options=bl_opts, key="datumsmapping_bl")
with fc3:
    typ_opts = sorted(df["plan_typ"].unique().tolist())
    typ_sel = st.multiselect("Typ", options=typ_opts, key="datumsmapping_typ")

view = df.copy()
if monat_sel:
    view = view[view["monat"].isin(monat_sel)]
if bl_sel:
    view = view[view["bundesland"].isin(bl_sel)]
if typ_sel:
    view = view[view["plan_typ"].isin(typ_sel)]

display = view[["plan_datum", "plan_wt", "plan_typ", "base_datum", "base_wt", "bundesland", "mapping_art"]].copy()
display.columns = ["Plantag", "WT Plan", "Typ Plan", "Referenztag", "WT Ref", "Bundesland", "Mapping-Art"]

st.dataframe(display, use_container_width=True, hide_index=True, height=500)
st.caption(f"{len(display):,} Zeilen angezeigt von {len(df):,} gesamt.")
