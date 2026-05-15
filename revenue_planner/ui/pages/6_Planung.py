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


# ── Parameter summary ──────────────────────────────────────────────────────
with st.expander("📋 Aktive Parameter", expanded=False):
    col1, col2, col3 = st.columns(3)
    col1.metric("Preiserhöhung", f"{params.preiserhoehung_pct:.1f}%")
    col2.metric("Ferien-Puffer", f"{params.ferien_puffer_wochen} Wochen")
    col3.metric("Planjahr", planjahr)

    if params.ramadan_plan_start:
        st.write(f"**Ramadan {planjahr}:** {params.ramadan_plan_start} – {params.ramadan_plan_ende} "
                 f"| sensitiver Anteil: {params.ramadan_umsatz_pct}%")
    if params.fasching_plan_start:
        vj_days = (params.fasching_vj_ende - params.fasching_vj_start).days + 1 if params.fasching_vj_start else "?"
        plan_days = (params.fasching_plan_ende - params.fasching_plan_start).days + 1
        diff = plan_days - (vj_days if isinstance(vj_days, int) else 0)
        st.write(f"**Fasching {planjahr}:** {params.fasching_plan_start} – {params.fasching_plan_ende} "
                 f"({plan_days} Tage, {'+' if diff>=0 else ''}{diff} vs. VJ) | Wirkung: {params.fasching_wirkung_pct}%/Tag")

# ── Select branches ────────────────────────────────────────────────────────
all_filialen = [r["fil_nr"] for r in conn.execute("SELECT fil_nr FROM filialen ORDER BY fil_nr").fetchall()]
n_filialen = len(all_filialen)

run_mode = st.radio("Ausführen für", ["Alle Filialen", "Auswahl"])
if run_mode == "Auswahl":
    selected_fils = st.multiselect("Filialen auswählen", all_filialen)
else:
    selected_fils = all_filialen
    st.caption(f"{n_filialen} Filialen")

# ── Run button ─────────────────────────────────────────────────────────────
st.divider()

if st.button("🚀 Planung berechnen", type="primary", disabled=not selected_fils):
    with st.spinner(f"Berechne {len(selected_fils)} Filiale(n)…"):
        try:
            engine = PlanningEngine(conn, params)

            # Show Fasching info
            fa_info = engine.fasching_info()
            if fa_info:
                st.info(f"📅 {fa_info['hinweis']}")

            results = engine.run(selected_fils)
            engine.save(results)
            st.success(f"✅ Planung für {len(selected_fils)} Filiale(n) abgeschlossen — {len(results):,} Tage berechnet.")
            st.session_state["last_plan_results"] = results
            st.session_state["last_plan_jahr"] = planjahr
        except Exception as e:
            st.error(f"Fehler bei der Berechnung: {e}")
            st.exception(e)

# ── Results preview ────────────────────────────────────────────────────────
if "last_plan_results" in st.session_state and st.session_state.get("last_plan_jahr") == planjahr:
    results = st.session_state["last_plan_results"]
    st.divider()
    st.subheader("Ergebnisvorschau")

    df = pd.DataFrame([
        {"fil_nr": r.fil_nr, "monat": r.datum.month, "gesamt_plan": r.gesamt_plan,
         "tagesumsatz_plan": r.tagesumsatz_plan, "liefer_plan": r.liefer_plan,
         "tagestyp": r.tagestyp}
        for r in results
    ])

    tab1, tab2 = st.tabs(["Jahresübersicht", "Monatsübersicht"])

    with tab1:
        jahres = df.groupby("fil_nr").agg(
            Plan_Gesamt=("gesamt_plan", "sum"),
            Lieferkunden=("liefer_plan", "sum"),
            Ladengeschaeft=("tagesumsatz_plan", "sum"),
        ).reset_index().sort_values("Plan_Gesamt", ascending=False)
        jahres["Plan_Gesamt"] = jahres["Plan_Gesamt"].map("{:,.0f} €".format)
        jahres["Lieferkunden"] = jahres["Lieferkunden"].map("{:,.0f} €".format)
        jahres["Ladengeschaeft"] = jahres["Ladengeschaeft"].map("{:,.0f} €".format)
        st.dataframe(jahres, use_container_width=True, hide_index=True)

        total = sum(r.gesamt_plan for r in results)
        col1, col2, col3 = st.columns(3)
        col1.metric("Gesamtplan", f"{total:,.0f} €")
        col2.metric("Filialen", len(set(r.fil_nr for r in results)))
        col3.metric("Tage berechnet", len(results))

    with tab2:
        monthly = df.groupby(["fil_nr", "monat"])["gesamt_plan"].sum().unstack(fill_value=0)
        monthly.columns = [f"M{m:02d}" for m in monthly.columns]
        st.dataframe(monthly.style.format("{:,.0f}"), use_container_width=True)

    # ── Excel download ─────────────────────────────────────────────────────
    st.divider()
    with st.spinner("Erstelle Excel-Datei…"):
        excel_bytes = build_excel(results, gmbh, planjahr)

    st.download_button(
        label="📥 Excel-Planung herunterladen",
        data=excel_bytes,
        file_name=f"Umsatzplanung_{planjahr}_{gmbh.replace(' ', '_')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
    )

# ── Previous results from DB ───────────────────────────────────────────────
st.divider()
existing_plan = conn.execute(
    "SELECT COUNT(*) as n, MIN(datum) as von, MAX(datum) as bis FROM planung"
).fetchone()
if existing_plan and existing_plan["n"] > 0:
    st.caption(
        f"In der Datenbank gespeicherte Planung: {existing_plan['n']:,} Zeilen "
        f"({existing_plan['von']} – {existing_plan['bis']})"
    )
    if st.button("📥 Gespeicherte Planung erneut exportieren"):
        rows = conn.execute("""
            SELECT p.*, f.bundesland
            FROM planung p
            LEFT JOIN filialen f ON p.fil_nr = f.fil_nr
            ORDER BY p.fil_nr, p.datum
        """).fetchall()
        from planning.engine import DayPlan
        saved_results = [
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
        excel_bytes = build_excel(saved_results, gmbh, planjahr)
        st.download_button(
            "📥 Herunterladen",
            data=excel_bytes,
            file_name=f"Umsatzplanung_{planjahr}_{gmbh.replace(' ', '_')}_gespeichert.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
