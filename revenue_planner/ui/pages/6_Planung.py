"""Planning run page: execute, preview results, download Excel."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import get_conn, get_gmbh, require_db
from planning.engine import PlanningEngine, PlanParams, DayPlan
from planning.export import build_excel
import pandas as pd
from datetime import date

require_db()
conn = get_conn()
gmbh = get_gmbh()
st.title("Planung ausführen")
st.caption(f"Firma: **{gmbh}**")

c1, c2 = st.columns(2)
with c1:
    planjahr = st.number_input("Planjahr (Budgetjahr)", min_value=2024, max_value=2035,
                               value=date.today().year + 1, step=1, key="plan_pj")
with c2:
    stichtag = st.date_input(
        "Stichtag (Basiszeitraum = letzte 12 abgeschl. Monate davor)",
        value=date.today(),
        help="Der Basiszeitraum sind die 12 vollständig abgeschlossenen Monate vor diesem Datum.",
    )

param_row = conn.execute("SELECT * FROM parameter WHERE planjahr=?", (planjahr,)).fetchone()
pr = dict(param_row) if param_row else {}
if not param_row:
    st.info("Keine Planungsparameter hinterlegt — es wird mit Standardwerten gerechnet "
            "(kein Wachstum, kein Ferien-/Feiertagseffekt).")

monat_rows = conn.execute(
    "SELECT monat, wachstum_pct FROM parameter_monat WHERE planjahr=?", (planjahr,)
).fetchall()
wachstum_monat = {r["monat"]: r["wachstum_pct"] for r in monat_rows}


def _d(val):
    return date.fromisoformat(val) if val else None


params = PlanParams(
    planjahr=planjahr,
    stichtag=stichtag,
    preiserhoehung_pct=pr.get("preiserhoehung_pct") or 0.0,
    wachstum_monat=wachstum_monat,
    ferien_puffer_wochen=pr.get("ferien_puffer_wochen") or 2,
)

# Basiszeitraum-Anzeige
_eng_preview = PlanningEngine(conn, params)
st.success(f"📅 Basiszeitraum: **{_eng_preview.base_window_label()}**  →  Planjahr **{planjahr}**")

with st.expander("📋 Aktive Parameter", expanded=False):
    cc1, cc2 = st.columns(2)
    cc1.metric("Ferien-Puffer", f"{params.ferien_puffer_wochen} Wochen")
    cc2.metric("Planjahr", planjahr)
    if wachstum_monat:
        MONATE_S = ["Jan","Feb","Mär","Apr","Mai","Jun","Jul","Aug","Sep","Okt","Nov","Dez"]
        st.dataframe(
            pd.DataFrame([{MONATE_S[m-1]: f"{wachstum_monat.get(m,0.0):.1f}%" for m in range(1,13)}]),
            use_container_width=True, hide_index=True,
        )
    else:
        cc1.metric("Preiserhöhung", f"{params.preiserhoehung_pct:.1f}%")
    st.caption("Ramadan & Fasching sind derzeit nicht in der Berechnung berücksichtigt (offene Punkte).")

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
        {"fil_nr": r.fil_nr, "monat": r.datum.month, "budget": r.budget, "ist_vj": r.ist_vj}
        for r in results
    ])

    tab1, tab2 = st.tabs(["Jahresübersicht", "Monatsübersicht"])
    with tab1:
        jahres = df.groupby("fil_nr").agg(
            IST_VJ=("ist_vj", "sum"),
            Budget=("budget", "sum"),
        ).reset_index().sort_values("Budget", ascending=False)
        jahres["Δ €"] = jahres["Budget"] - jahres["IST_VJ"]
        for col in ["IST_VJ", "Budget", "Δ €"]:
            jahres[col] = jahres[col].map("{:,.0f} €".format)
        st.dataframe(jahres, use_container_width=True, hide_index=True)
        total = df["budget"].sum()
        d1, d2, d3 = st.columns(3)
        d1.metric("Budget gesamt", f"{total:,.0f} €")
        d2.metric("Filialen", df["fil_nr"].nunique())
        d3.metric("Tage", len(results))

    with tab2:
        monthly = df.groupby(["fil_nr", "monat"])["budget"].sum().unstack(fill_value=0)
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
        rows = conn.execute("SELECT * FROM planung ORDER BY fil_nr, datum").fetchall()

        def _g(r, k, default=0.0):
            try:
                v = r[k]
                return v if v is not None else default
            except (IndexError, KeyError):
                return default

        saved = [
            DayPlan(
                fil_nr=r["fil_nr"], datum=date.fromisoformat(r["datum"]),
                wochentag=r["wochentag"], bundesland=_g(r, "bundesland", "") or "",
                ist_vj=_g(r, "ist_vj"),
                eff_oeffnung=_g(r, "eff_oeffnung"), eff_verteilung=_g(r, "eff_verteilung"),
                eff_wochentag=_g(r, "eff_wochentag"), eff_preis=_g(r, "eff_preis"),
                eff_ferien=_g(r, "eff_ferien"), eff_feiertag=_g(r, "eff_feiertag"),
                eff_norm=_g(r, "eff_norm"),
                budget=_g(r, "budget") or _g(r, "gesamt_plan"),
                monat_basis=_g(r, "monat_basis"), monat_hoch=_g(r, "monat_hoch") or _g(r, "monatsumsatz_ist_hoch"),
                monat_plan=_g(r, "monat_plan") or _g(r, "monatsumsatz_plan"),
                tagestyp=_g(r, "tagestyp", "normal") or "normal",
                feiertag_name=_g(r, "feiertag_name", "") or "",
                ferien_art=_g(r, "ferien_art", "") or "",
                normalisierung=_g(r, "normalisierung", 1.0) or 1.0,
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
