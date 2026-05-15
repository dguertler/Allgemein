"""New branch monthly plan input and delivery customer planning."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import get_conn, get_gmbh, require_db
import pandas as pd
from datetime import date

st.set_page_config(page_title="Neue Filialen & Lieferkunden", page_icon="🆕", layout="wide")
st.title("🆕 Neue Filialen & Lieferkunden")
require_db()

conn = get_conn()
st.caption(f"GmbH: **{get_gmbh()}**")

MONTH_DE = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
            "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]

planjahr = st.number_input("Planjahr", min_value=2024, max_value=2035,
                            value=date.today().year + 1, step=1, key="pj_nf")

tab1, tab2 = st.tabs(["Neue Filialen (Monatswerte)", "Lieferkunden (Monats-IST)"])

# ── Tab 1: New branches monthly plan ──────────────────────────────────────
with tab1:
    st.subheader("Monatliche Planwerte für neue Filialen")
    st.info(
        "Tragen Sie für jede neue Filiale die erwarteten Monatsumsätze ein. "
        "Der **Eröffnungsmonat** wird automatisch mit 50% angesetzt "
        "(überschreibbar durch manuellen Wert)."
    )

    # Load new branches
    neue_filialen = conn.execute(
        "SELECT fil_nr FROM filialen WHERE flag_neue_filiale=1 ORDER BY fil_nr"
    ).fetchall()

    if not neue_filialen:
        st.warning("Keine Filialen als 'Neue Filiale' markiert. Bitte zuerst unter Filialen das Flag setzen.")
    else:
        fil_nrs = [r["fil_nr"] for r in neue_filialen]
        selected_fil = st.selectbox("Filiale", fil_nrs, key="nf_select")

        # Load existing values
        existing = conn.execute(
            "SELECT monat, planwert, eroeffnung_datum FROM neue_filialen_plan WHERE fil_nr=? AND planjahr=?",
            (selected_fil, planjahr)
        ).fetchall()
        existing_map = {r["monat"]: {"planwert": r["planwert"], "eroeff": r["eroeffnung_datum"]}
                       for r in existing}

        fil_info = conn.execute("SELECT eroeffnung FROM filialen WHERE fil_nr=?", (selected_fil,)).fetchone()
        eroeff_str = fil_info["eroeffnung"] if fil_info else None

        st.markdown(f"**Eröffnungsdatum:** {eroeff_str or 'nicht hinterlegt'}")

        with st.form(f"neue_fil_plan_{selected_fil}"):
            cols = st.columns(6)
            values = {}
            for i, month_name in enumerate(MONTH_DE):
                month = i + 1
                ex_val = existing_map.get(month, {}).get("planwert", 0.0)
                # Mark opening month
                is_eroeff_month = False
                if eroeff_str:
                    eroeff_date = date.fromisoformat(eroeff_str)
                    is_eroeff_month = (eroeff_date.month == month and eroeff_date.year == planjahr)
                label = f"{month_name} {'🔑' if is_eroeff_month else ''}"
                help_txt = "Eröffnungsmonat: wird mit 50% berechnet (außer manuell überschrieben)" if is_eroeff_month else ""
                with cols[i % 6]:
                    values[month] = st.number_input(
                        label, min_value=0.0, value=float(ex_val),
                        step=1000.0, format="%.0f", help=help_txt, key=f"nf_{month}"
                    )

            if st.form_submit_button("💾 Speichern"):
                for month, val in values.items():
                    conn.execute("""
                        INSERT INTO neue_filialen_plan (fil_nr, planjahr, monat, planwert, eroeffnung_datum)
                        VALUES (?,?,?,?,?)
                        ON CONFLICT(fil_nr, planjahr, monat) DO UPDATE SET
                          planwert=excluded.planwert,
                          eroeffnung_datum=excluded.eroeffnung_datum
                    """, (selected_fil, planjahr, month, val, eroeff_str))
                conn.commit()
                st.success("✅ Gespeichert.")
                st.rerun()

        # Preview
        if existing_map:
            st.markdown("**Aktuelle Werte (vor 50%-Korrektur des Eröffnungsmonats):**")
            prev_data = {MONTH_DE[m-1]: existing_map[m]["planwert"] for m in range(1, 13) if m in existing_map}
            st.bar_chart(prev_data)

# ── Tab 2: Delivery customers ──────────────────────────────────────────────
with tab2:
    st.subheader("Lieferkunden – IST-Monatsumsätze Vorjahr")
    st.info(
        "Diese Werte sind die Basis für die Lieferkundenumsatz-Planung. "
        "Die Planung ergibt sich automatisch als: **IST × (1 + Preiserhöhung%)**"
    )

    vj = planjahr - 1
    filialen = conn.execute("SELECT fil_nr FROM filialen ORDER BY fil_nr").fetchall()
    fil_nrs_all = [r["fil_nr"] for r in filialen]

    if not fil_nrs_all:
        st.warning("Keine Filialen vorhanden.")
    else:
        selected_ls = st.selectbox("Filiale", fil_nrs_all, key="ls_select")

        existing_ls = conn.execute(
            "SELECT monat, ist_betrag FROM lieferkunden_monat WHERE fil_nr=? AND jahr=?",
            (selected_ls, vj)
        ).fetchall()
        ls_map = {r["monat"]: r["ist_betrag"] for r in existing_ls}

        with st.form(f"ls_plan_{selected_ls}"):
            cols = st.columns(6)
            ls_values = {}
            for i, month_name in enumerate(MONTH_DE):
                month = i + 1
                with cols[i % 6]:
                    ls_values[month] = st.number_input(
                        f"{month_name} {vj}", min_value=0.0,
                        value=float(ls_map.get(month, 0.0)),
                        step=100.0, format="%.2f", key=f"ls_{month}"
                    )

            if st.form_submit_button("💾 Speichern"):
                for month, val in ls_values.items():
                    if val > 0:
                        conn.execute("""
                            INSERT INTO lieferkunden_monat (fil_nr, jahr, monat, ist_betrag)
                            VALUES (?,?,?,?)
                            ON CONFLICT(fil_nr, jahr, monat) DO UPDATE SET ist_betrag=excluded.ist_betrag
                        """, (selected_ls, vj, month, val))
                conn.commit()
                st.success("✅ Gespeichert.")
                st.rerun()

        if ls_map:
            jahressumme = sum(ls_map.values())
            st.metric(f"Jahressumme Lieferkunden {vj}", f"{jahressumme:,.2f} €")

        # Bulk import for delivery customers
        st.divider()
        st.markdown("**Massenimport Lieferkunden** (CSV/Excel: fil_nr, monat, ist_betrag)")
        ls_upload = st.file_uploader("Datei hochladen", type=["csv", "xlsx"], key="ls_upload")
        if ls_upload:
            if ls_upload.name.endswith(".csv"):
                ls_df = pd.read_csv(ls_upload)
            else:
                ls_df = pd.read_excel(ls_upload)
            ls_df.columns = ls_df.columns.str.lower().str.strip()
            st.dataframe(ls_df.head())
            if st.button("Importieren", key="ls_import_btn"):
                for _, row in ls_df.iterrows():
                    conn.execute("""
                        INSERT INTO lieferkunden_monat (fil_nr, jahr, monat, ist_betrag)
                        VALUES (?,?,?,?)
                        ON CONFLICT(fil_nr, jahr, monat) DO UPDATE SET ist_betrag=excluded.ist_betrag
                    """, (str(row["fil_nr"]), int(row.get("jahr", vj)),
                          int(row["monat"]), float(row["ist_betrag"])))
                conn.commit()
                st.success(f"✅ {len(ls_df)} Einträge importiert.")
                st.rerun()
