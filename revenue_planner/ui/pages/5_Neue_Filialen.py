"""New branch monthly plan input and delivery customer planning."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import get_conn, get_gmbh, require_db
import pandas as pd
from datetime import date

require_db()
conn = get_conn()
st.title("Neue Filialen & Lieferkunden")
st.caption(f"Firma: **{get_gmbh()}**")

MONTH_DE = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
            "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]

planjahr = st.number_input("Planjahr", min_value=2024, max_value=2035,
                            value=date.today().year + 1, step=1, key="pj_nf")

tab1, tab2 = st.tabs(["Neue Filialen (Monatswerte)", "Lieferkunden (Monats-IST)"])

# ── Tab 1: New branches monthly plan ──────────────────────────────────────
with tab1:
    st.subheader("Monatliche Planwerte für neue Filialen")
    st.info(
        "Neue Filialen werden automatisch erkannt: alle Filialen mit einem "
        f"Eröffnungsdatum im Jahr **{planjahr}** erscheinen hier. "
        "Der Eröffnungsmonat wird automatisch mit **50%** des eingetragenen Wertes berechnet."
    )

    # Auto-detect new branches by eroeffnung in plan year
    neue_filialen = conn.execute("""
        SELECT fil_nr, bezeichnung, eroeffnung
        FROM filialen
        WHERE eroeffnung IS NOT NULL
          AND CAST(substr(eroeffnung, 1, 4) AS INTEGER) = ?
        ORDER BY fil_nr
    """, (planjahr,)).fetchall()

    if not neue_filialen:
        st.warning(
            f"Keine Filialen mit Eröffnungsdatum in {planjahr} gefunden. "
            "Bitte unter **Filialen** ein Eröffnungsdatum eintragen."
        )
    else:
        fil_options = {
            r["fil_nr"]: f"{r['fil_nr']} – {r['bezeichnung'] or ''} (Eröffnung: {r['eroeffnung']})"
            for r in neue_filialen
        }
        selected_fil = st.selectbox("Filiale", list(fil_options.keys()),
                                    format_func=lambda x: fil_options[x])

        fil_info = next(r for r in neue_filialen if r["fil_nr"] == selected_fil)
        eroeff_iso = fil_info["eroeffnung"]
        eroeff_month = int(eroeff_iso[5:7]) if eroeff_iso else None

        existing = conn.execute(
            "SELECT monat, planwert FROM neue_filialen_plan WHERE fil_nr=? AND planjahr=?",
            (selected_fil, planjahr)
        ).fetchall()
        existing_map = {r["monat"]: r["planwert"] for r in existing}

        with st.form(f"neue_fil_plan_{selected_fil}"):
            cols = st.columns(6)
            values = {}
            for i, month_name in enumerate(MONTH_DE):
                month = i + 1
                ex_val = existing_map.get(month, 0.0)
                is_eroeff = (month == eroeff_month)
                label = f"{month_name} {'🔑' if is_eroeff else ''}"
                help_txt = "Eröffnungsmonat → wird automatisch mit 50% berechnet" if is_eroeff else ""
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
                    """, (selected_fil, planjahr, month, val, eroeff_iso))
                conn.commit()
                st.success("✅ Gespeichert.")
                st.rerun()

        if existing_map:
            st.markdown("**Aktuelle Monatswerte (Brutto, vor 50%-Kürzung Eröffnungsmonat):**")
            chart_data = {MONTH_DE[m - 1]: existing_map[m] for m in range(1, 13) if m in existing_map}
            st.bar_chart(chart_data)

# ── Tab 2: Delivery customers ──────────────────────────────────────────────
with tab2:
    st.subheader("Lieferkunden – IST-Monatsumsätze Vorjahr")
    st.info(
        "Basis für die Lieferkundenumsatz-Planung. "
        f"Plan = IST {planjahr - 1} × (1 + Preiserhöhung%)"
    )

    vj = planjahr - 1
    filialen = conn.execute("SELECT fil_nr, bezeichnung FROM filialen ORDER BY fil_nr").fetchall()
    fil_nrs_all = [r["fil_nr"] for r in filialen]
    fil_labels = {r["fil_nr"]: f"{r['fil_nr']} – {r['bezeichnung'] or ''}" for r in filialen}

    if not fil_nrs_all:
        st.warning("Keine Filialen vorhanden.")
    else:
        selected_ls = st.selectbox("Filiale", fil_nrs_all,
                                   format_func=lambda x: fil_labels[x], key="ls_select")

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
                    conn.execute("""
                        INSERT INTO lieferkunden_monat (fil_nr, jahr, monat, ist_betrag)
                        VALUES (?,?,?,?)
                        ON CONFLICT(fil_nr, jahr, monat) DO UPDATE SET ist_betrag=excluded.ist_betrag
                    """, (selected_ls, vj, month, val))
                conn.commit()
                st.success("✅ Gespeichert.")
                st.rerun()

        if ls_map:
            st.metric(f"Jahressumme Lieferkunden {vj}", f"{sum(ls_map.values()):,.2f} €")

        st.divider()
        st.markdown("**Massenimport Lieferkunden**")
        st.caption("CSV/Excel mit Spalten: Filialnummer, Monat (1–12), Betrag")
        ls_upload = st.file_uploader("Datei hochladen", type=["csv", "xlsx"], key="ls_upload")
        if ls_upload:
            ls_df = pd.read_csv(ls_upload) if ls_upload.name.endswith(".csv") else pd.read_excel(ls_upload)
            ls_df.columns = ls_df.columns.str.lower().str.strip()
            # Flexible column mapping
            col_map = {}
            for col in ls_df.columns:
                if "filial" in col or col == "fil_nr":
                    col_map["fil_nr"] = col
                elif "monat" in col or "month" in col:
                    col_map["monat"] = col
                elif "betrag" in col or "umsatz" in col or "betrag" in col:
                    col_map["ist_betrag"] = col
            ls_df = ls_df.rename(columns={v: k for k, v in col_map.items()})
            st.dataframe(ls_df.head())
            if st.button("Importieren", key="ls_import_btn"):
                for _, row in ls_df.iterrows():
                    conn.execute("""
                        INSERT INTO lieferkunden_monat (fil_nr, jahr, monat, ist_betrag)
                        VALUES (?,?,?,?)
                        ON CONFLICT(fil_nr, jahr, monat) DO UPDATE SET ist_betrag=excluded.ist_betrag
                    """, (str(row["fil_nr"]), vj, int(row["monat"]), float(row["ist_betrag"])))
                conn.commit()
                st.success(f"✅ {len(ls_df)} Einträge importiert.")
                st.rerun()
