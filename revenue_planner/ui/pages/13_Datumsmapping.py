"""Datumsmapping — zeigt und generiert das Mapping Budgettag → Basistag."""
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
    "Das Datumsmapping ordnet jedem Budgettag im Planjahr einen korrekten Basistag "
    "im Basiszeitraum zu — wochentagsbasiert, mit Feiertags- und Feriensonderbehandlung. "
    "Es muss neu generiert werden, wenn Feiertage oder Ferien geändert wurden."
)

planjahr = get_budgetjahr()

MAPPING_ART_LABELS = {
    "feiertag":    "Feiertag",
    "ferien":      "Ferien",
    "sondertag":   "Sondertag",
    "iso_kw":      "KW-Vergleich",
}

TYP_LABELS = {
    "feiertag":    "Feiertag",
    "feiertagstag": "Feiertagstag (Vor-/Nachtag)",
    "sondertag":   "Sondertag",
    "ferien":      "Ferien",
    "normal":      "Normaltag",
}

col1, col2 = st.columns([2, 1])
with col1:
    st.subheader(f"Mapping für Budgetjahr {planjahr}")
with col2:
    if st.button("🔄 Mapping generieren", type="primary", use_container_width=True):
        with st.spinner("Generiere Datumsmapping…"):
            try:
                from planning.engine import PlanningEngine, PlanParams
                from planning.datumsmapping import generate_datumsmapping

                par_row = conn.execute(
                    "SELECT * FROM parameter WHERE planjahr = ?", (planjahr,)
                ).fetchone()
                params = PlanParams(
                    planjahr=planjahr,
                    preiserhoehung_pct=float(par_row["preiserhoehung_pct"] or 0) if par_row else 0,
                    ferien_puffer_wochen=int(par_row["ferien_puffer_wochen"] or 2) if par_row else 2,
                )
                engine = PlanningEngine(conn, params)
                n = generate_datumsmapping(conn, planjahr, engine)
                st.success(f"{n:,} Mapping-Zeilen generiert.")
                st.rerun()
            except Exception as ex:
                st.error(f"Fehler: {ex}")

# ── Daten laden ──────────────────────────────────────────────────────────────
df = pd.read_sql(
    "SELECT plan_datum, base_datum, plan_typ, bundesland, mapping_art, "
    "bezeichnung, base_bezeichnung "
    "FROM datumsmapping "
    "WHERE CAST(strftime('%Y', plan_datum) AS INTEGER) = ? "
    "ORDER BY bundesland, plan_datum",
    conn, params=(planjahr,)
)

if df.empty:
    st.warning(
        f"Kein Mapping für Budgetjahr **{planjahr}** vorhanden. "
        "Bitte über den Button oben generieren."
    )
    st.stop()

# ── Aufbereitungen ───────────────────────────────────────────────────────────
WOCHENTAGE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

df["plan_datum_dt"]     = pd.to_datetime(df["plan_datum"])
df["plan_datum_de"]     = df["plan_datum_dt"].dt.strftime("%d.%m.%Y")
df["plan_wt"]           = df["plan_datum_dt"].dt.weekday.map(lambda x: WOCHENTAGE[x])
df["base_datum_dt"]     = pd.to_datetime(df["base_datum"])
df["base_datum_de"]     = df["base_datum_dt"].dt.strftime("%d.%m.%Y")
df["base_wt"]           = df["base_datum_dt"].dt.weekday.map(lambda x: WOCHENTAGE[x])
df["monat"]             = df["plan_datum_dt"].dt.month
df["mapping_art_label"] = df["mapping_art"].map(MAPPING_ART_LABELS).fillna(df["mapping_art"])

MONATE_DE = ["Januar", "Februar", "März", "April", "Mai", "Juni",
             "Juli", "August", "September", "Oktober", "November", "Dezember"]

# ── Filter ───────────────────────────────────────────────────────────────────
fc1, fc2, fc3 = st.columns(3)
with fc1:
    monat_opts = sorted(df["monat"].unique().tolist())
    monat_sel = st.multiselect(
        "Monat",
        options=monat_opts,
        format_func=lambda m: MONATE_DE[m - 1],
        placeholder="Alle Monate",
        key="datumsmapping_monat",
    )
with fc2:
    bl_opts = sorted(df["bundesland"].unique().tolist())
    bl_sel = st.multiselect(
        "Bundesland",
        options=bl_opts,
        placeholder="Alle Bundesländer",
        key="datumsmapping_bl",
    )
with fc3:
    typ_raw_opts = sorted(df["plan_typ"].unique().tolist())
    typ_sel = st.multiselect(
        "Typ",
        options=typ_raw_opts,
        format_func=lambda t: TYP_LABELS.get(t, t),
        placeholder="Alle Typen",
        key="datumsmapping_typ",
    )

view = df.copy()
if monat_sel:
    view = view[view["monat"].isin(monat_sel)]
if bl_sel:
    view = view[view["bundesland"].isin(bl_sel)]
if typ_sel:
    view = view[view["plan_typ"].isin(typ_sel)]

# ── Anzeigetabelle ───────────────────────────────────────────────────────────
display = view[[
    "bundesland",
    "plan_datum_de", "plan_wt", "bezeichnung",
    "base_datum_de",  "base_wt", "base_bezeichnung",
    "mapping_art_label",
]].copy()
display.columns = [
    "Bundesland",
    "Budgettag", "Wochentag", "Beschreibung Budget",
    "Basistag",  "Wochentag ", "Beschreibung Basistag",
    "Mapping-Art",
]

st.dataframe(display, use_container_width=True, hide_index=True, height=500)
st.caption(
    f"{len(display):,} Zeilen angezeigt von {len(df):,} gesamt. &nbsp;"
    "**Mapping-Art:** "
    "*Feiertag* = gleichnamiger Feiertag im Basiszeitraum; "
    "*Ferien* = gleiche Ferienwoche im Basiszeitraum (wochentagsbasiert); "
    "*KW-Vergleich* = gleicher Wochentag in derselben Kalenderwoche des Basiszeitraums."
)
