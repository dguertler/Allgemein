"""Planning run page: execute, preview results, download Excel."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import get_conn, get_gmbh, require_db
from planning.engine import PlanningEngine, PlanParams
from planning.export import build_excel
import pandas as pd
from datetime import date

require_db()
conn = get_conn()
gmbh = get_gmbh()
st.title("Planung ausführen")
st.caption(f"Firma: **{gmbh}**")

planjahr = st.number_input("Planjahr", min_value=2024, max_value=2035,
                            value=date.today().year + 1, step=1, key="plan_pj")

param_row = conn.execute("SELECT * FROM parameter WHERE planjahr=?", (planjahr,)).fetchone()

if not param_row:
    st.warning("Keine Planungsparameter hinterlegt. Bitte zuerst unter **Parameter** konfigurieren.")
    st.stop()

monat_rows = conn.execute(
    "SELECT monat, wachstum_pct FROM parameter_monat WHERE planjahr=?", (planjahr,)
).fetchall()
wachstum_monat = {r["monat"]: r["wachstum_pct"] for r in monat_rows}

def _d(val):
    return date.fromisoformat(val) if val else None

params = PlanParams(
    planjahr=planjahr,
    preiserhoehung_pct=param_row["preiserhoehung_pct"] or 0.0,
    wachstum_monat=wachstum_monat,
    ferien_puffer_wochen=param_row["ferien_puffer_wochen"] or 3,
    ramadan_vj_start=_d(param_row["ramadan_vj_start"]),
    ramadan_vj_ende=_d(param_row["ramadan_vj_ende"]),
    ramadan_plan_start=_d(param_row["ramadan_plan_start"]),
    ramadan_plan_ende=_d(param_row["ramadan_plan_ende"]),
    ramadan_umsatz_pct=param_row["ramadan_umsatz_pct"] or 0.0,
    fasching_vj_start=_d(param_row["fasching_vj_start"]),
    fasching_vj_ende=_d(param_row["fasching_vj_ende"]),
    fasching_plan_start=_d(param_row["fasching_plan_start"]),
    fasching_plan_ende=_d(param_row["fasching_plan_ende"]),
    fasching_wirkung_pct=param_row["fasching_wirkung_pct"] or 0.0,
)

with st.expander("📋 Aktive Parameter", expanded=False):
    col1, col2, col3 = st.columns(3)
    col2.metric("Ferien-Puffer", f"{params.ferien_puffer_wochen} Wochen")
    col3.metric("Planjahr", planjahr)
    if wachstum_monat:
        MONATE_S = ["Jan","Feb","Mär","Apr","Mai","Jun","Jul","Aug","Sep","Okt","Nov","Dez"]
        st.dataframe(
            pd.DataFrame([{MONATE_S[m-1]: f"{wachstum_monat.get(m,0.0):.1f}%" for m in range(1,13)}]),
            use_container_width=True, hide_index=True,
        )
    else:
        col1.metric("Preiserhöhung", f"{params.preiserhoehung_pct:.1f}%")
    if params.ramadan_plan_start:
        st.write(f"**Ramadan {planjahr}:** {params.ramadan_plan_start} – {params.ramadan_plan_ende} "
                 f"| sensitiver Anteil: {params.ramadan_umsatz_pct}%")
    if params.fasching_plan_start and params.fasching_vj_start:
        diff = ((params.fasching_plan_ende - params.fasching_plan_start).days -
                (params.fasching_vj_ende - params.fasching_vj_start).days)
        st.write(f"**Fasching {planjahr}:** {params.fasching_plan_start} – {params.fasching_plan_ende} "
                 f"({'+' if diff >= 0 else ''}{diff} Tage vs. VJ) | Wirkung: {params.fasching_wirkung_pct}%/Tag")

all_filialen = [r["fil_nr"] for r in
                conn.execute("SELECT fil_nr FROM filialen ORDER BY fil_nr").fetchall()]

run_mode = st.radio("Ausführen für", ["Alle Filialen", "Auswahl"])
if run_mode == "Auswahl":
    selected_fils = st.multiselect("Filialen auswählen", all_filialen)
else:
    selected_fils = all_filialen
    st.caption(f"{len(all_filialen)} Filialen")

st.divider()

if st.button("🚀 Planung berechnen", type="primary", disabled=not selected_fils):
    with st.spinner(f"Berechne {len(selected_fils)} Filiale(n)…"):
        try:
            engine = PlanningEngine(conn, params)
            fa_info = engine.fasching_info()
            if fa_info and fa_info.get("differenz_tage", 0) != 0:
                st.info(f"📅 {fa_info['hinweis']}")
            results = engine.run(selected_fils)
            engine.save(results)
            st.success(f"✅ {len(selected_fils)} Filiale(n) — {len(results):,} Tage berechnet.")
            st.session_state["last_plan_results"] = results
            st.session_state["last_plan_jahr"] = planjahr
        except Exception as e:
            st.error(f"Fehler: {e}")
            st.exception(e)

if "last_plan_results" in st.session_state and st.session_state.get("last_plan_jahr") == planjahr:
    results = st.session_state["last_plan_results"]
    st.divider()
    st.subheader("Ergebnisvorschau")

    df = pd.DataFrame([
        {"fil_nr": r.fil_nr, "monat": r.datum.month,
         "gesamt_plan": r.gesamt_plan, "tagesumsatz_plan": r.tagesumsatz_plan,
         "liefer_plan": r.liefer_plan}
        for r in results
    ])

    tab1, tab2 = st.tabs(["Jahresübersicht", "Monatsübersicht"])
    with tab1:
        jahres = df.groupby("fil_nr").agg(
            Ladengeschäft=("tagesumsatz_plan", "sum"),
            Lieferkunden=("liefer_plan", "sum"),
            Gesamt=("gesamt_plan", "sum"),
        ).reset_index().sort_values("Gesamt", ascending=False)
        for col in ["Ladengeschäft", "Lieferkunden", "Gesamt"]:
            jahres[col] = jahres[col].map("{:,.0f} €".format)
        st.dataframe(jahres, use_container_width=True, hide_index=True)
        total = sum(r.gesamt_plan for r in results)
        c1, c2, c3 = st.columns(3)
        c1.metric("Gesamtplan", f"{total:,.0f} €")
        c2.metric("Filialen", len(set(r.fil_nr for r in results)))
        c3.metric("Tage", len(results))

    with tab2:
        monthly = df.groupby(["fil_nr", "monat"])["gesamt_plan"].sum().unstack(fill_value=0)
        monthly.columns = [f"M{m:02d}" for m in monthly.columns]
        st.dataframe(monthly.style.format("{:,.0f}"), use_container_width=True)

    st.divider()
    with st.spinner("Excel wird erstellt…"):
        excel_bytes = build_excel(results, gmbh, planjahr)
    st.download_button(
        label="📥 Excel-Planung herunterladen",
        data=excel_bytes,
        file_name=f"Umsatzplanung_{planjahr}_{gmbh.replace(' ', '_')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
    )

st.divider()
existing_plan = conn.execute(
    "SELECT COUNT(*) as n, MIN(datum) as von, MAX(datum) as bis FROM planung"
).fetchone()
if existing_plan and existing_plan["n"] > 0:
    st.caption(f"Gespeicherte Planung: {existing_plan['n']:,} Zeilen "
               f"({existing_plan['von']} – {existing_plan['bis']})")
    if st.button("📥 Gespeicherte Planung erneut exportieren"):
        rows = conn.execute(
            "SELECT * FROM planung ORDER BY fil_nr, datum"
        ).fetchall()
        from planning.engine import DayPlan
        saved = [
            DayPlan(
                fil_nr=r["fil_nr"], datum=date.fromisoformat(r["datum"]),
                wochentag=r["wochentag"], ist_vj=r["ist_vj"] or 0,
                monatsumsatz_ist_hoch=r["monatsumsatz_ist_hoch"] or 0,
                monatsumsatz_plan=r["monatsumsatz_plan"] or 0,
                tagesumsatz_plan=r["tagesumsatz_plan"] or 0,
                liefer_plan=r["liefer_plan"] or 0,
                gesamt_plan=r["gesamt_plan"] or 0,
                tagestyp=r["tagestyp"] or "normal",
                feiertag_name=r["feiertag_name"] or "",
                ferien_art=r["ferien_art"] or "",
                normalisierung=r["normalisierung"] or 1.0,
            )
            for r in rows
        ]
        excel_bytes = build_excel(saved, gmbh, planjahr)
        st.download_button(
            "📥 Herunterladen",
            data=excel_bytes,
            file_name=f"Umsatzplanung_{planjahr}_{gmbh.replace(' ', '_')}_gespeichert.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
