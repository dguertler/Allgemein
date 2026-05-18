"""Branch management page."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import get_conn, get_gmbh, require_db
import pandas as pd
from datetime import date, datetime

require_db()
conn = get_conn()
st.title("🏪 Filialverwaltung")
st.caption(f"GmbH: **{get_gmbh()}**")

BUNDESLAENDER = ["RP", "HE", "BY", "BW", "NW", "NI",
                 "BE", "BB", "HB", "HH", "MV", "SH", "SL", "SN", "ST", "TH"]


def _parse_date(val: str) -> str | None:
    """Accept TT.MM.JJJJ or YYYY-MM-DD, store as YYYY-MM-DD."""
    if not val or not val.strip():
        return None
    val = val.strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(val, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def _fmt_date(iso: str | None) -> str:
    """Display ISO date as TT.MM.JJJJ."""
    if not iso:
        return ""
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%d.%m.%Y")
    except ValueError:
        return iso


df = pd.read_sql("SELECT * FROM filialen ORDER BY fil_nr", conn)

tab1, tab2, tab3 = st.tabs(["Übersicht & Bearbeiten", "Neue Filiale", "Massenimport"])

# ── Tab 1: Overview & Edit ─────────────────────────────────────────────────
with tab1:
    if df.empty:
        st.info("Noch keine Filialen vorhanden. Bitte unter 'Neue Filiale' oder 'Massenimport' erfassen.")
    else:
        st.markdown(f"**{len(df)} Filialen** in der Datenbank")

        show_cols = [c for c in ["fil_nr", "bezeichnung", "bundesland", "eroeffnung",
                                  "flag_kein_wachstum", "flag_inaktiv"] if c in df.columns]
        display = df[show_cols].copy()
        display["eroeffnung"] = display["eroeffnung"].apply(_fmt_date)
        if "flag_kein_wachstum" in display.columns:
            display["flag_kein_wachstum"] = display["flag_kein_wachstum"].apply(lambda x: "✅" if x else "")
        if "flag_inaktiv" in display.columns:
            display["flag_inaktiv"] = display["flag_inaktiv"].apply(lambda x: "✅" if x else "")
        display = display.rename(columns={
            "fil_nr": "Fil.-Nr.", "bezeichnung": "Bezeichnung", "bundesland": "Bundesland",
            "eroeffnung": "Eröffnung", "flag_kein_wachstum": "Kein Wachstum", "flag_inaktiv": "Inaktiv"
        })
        st.dataframe(display, use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("Filiale bearbeiten")
        selected = st.selectbox("Filiale auswählen", df["fil_nr"].tolist())
        row = df[df["fil_nr"] == selected].iloc[0]

        with st.form("edit_filiale"):
            col1, col2 = st.columns(2)
            with col1:
                bezeichnung = st.text_input("Bezeichnung", value=row.get("bezeichnung") or "")
                bl_idx = BUNDESLAENDER.index(row["bundesland"]) if row["bundesland"] in BUNDESLAENDER else 0
                bundesland = st.selectbox("Bundesland", BUNDESLAENDER, index=bl_idx)
                eroeffnung_in = st.text_input(
                    "Eröffnungsdatum",
                    value=_fmt_date(row.get("eroeffnung")),
                    placeholder="TT.MM.JJJJ  (leer = Bestandsfiliale)",
                    help="Neue Filialen werden automatisch erkannt, wenn ein Eröffnungsdatum im Planjahr eingetragen ist."
                )
            with col2:
                kein_wachstum = st.checkbox(
                    "Kein Wachstum", value=bool(row.get("flag_kein_wachstum")),
                    help="Diese Filiale erhält keine prozentuale Umsatzsteigerung."
                )
                inaktiv = st.checkbox(
                    "Inaktiv / Geschlossen", value=bool(row.get("flag_inaktiv"))
                )
                eroeffnung_ende_in = st.text_input(
                    "Schließungsdatum",
                    value=_fmt_date(row.get("eroeffnung_ende")),
                    placeholder="TT.MM.JJJJ"
                )

            if st.form_submit_button("💾 Speichern"):
                conn.execute("""
                    UPDATE filialen
                    SET bezeichnung=?, bundesland=?, eroeffnung=?,
                        flag_kein_wachstum=?, flag_inaktiv=?, eroeffnung_ende=?
                    WHERE fil_nr=?
                """, (
                    bezeichnung or None,
                    bundesland,
                    _parse_date(eroeffnung_in),
                    int(kein_wachstum),
                    int(inaktiv),
                    _parse_date(eroeffnung_ende_in),
                    selected,
                ))
                conn.commit()
                st.success("✅ Gespeichert.")
                st.rerun()

# ── Tab 2: New branch ──────────────────────────────────────────────────────
with tab2:
    st.subheader("Neue Filiale anlegen")
    with st.form("neue_filiale"):
        col1, col2 = st.columns(2)
        with col1:
            fil_nr = st.text_input("Filialnummer", placeholder='bspw. "0002"')
            bezeichnung = st.text_input("Bezeichnung", placeholder="z.B. Fulda – Bahnhof")
            eroeffnung_in = st.text_input(
                "Eröffnungsdatum",
                placeholder="TT.MM.JJJJ  (leer = Bestandsfiliale)"
            )
        with col2:
            bundesland = st.selectbox("Bundesland", BUNDESLAENDER, key="new_bl")
            kein_wachstum = st.checkbox("Kein Wachstum", key="new_kw")

        if st.form_submit_button("➕ Anlegen"):
            if not fil_nr.strip():
                st.error("Bitte Filialnummer angeben.")
            else:
                try:
                    conn.execute("""
                        INSERT INTO filialen (fil_nr, bezeichnung, bundesland, eroeffnung, flag_kein_wachstum)
                        VALUES (?,?,?,?,?)
                    """, (
                        fil_nr.strip(),
                        bezeichnung or None,
                        bundesland,
                        _parse_date(eroeffnung_in),
                        int(kein_wachstum),
                    ))
                    conn.commit()
                    st.success(f"✅ Filiale {fil_nr.strip()} angelegt.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Fehler: {e}")

# ── Tab 3: Bulk import ─────────────────────────────────────────────────────
with tab3:
    st.subheader("Stammdaten aus Datei importieren")
    st.info("""
    **Pflichtfelder:** Filialnummer, Bundesland
    **Optional:** Bezeichnung, Eröffnungsdatum (Format: TT.MM.JJJJ oder YYYY-MM-DD)

    ⚠️ Ein neuer Import **überschreibt alle bisherigen Stammdaten** vollständig.
    """)

    uploaded = st.file_uploader("CSV oder Excel hochladen", type=["csv", "xlsx"], key="stamm_upload")
    if uploaded:
        try:
            if uploaded.name.endswith(".csv"):
                imp = pd.read_csv(uploaded, dtype=str)
            else:
                imp = pd.read_excel(uploaded, dtype=str)

            # Flexible column mapping (German and internal names)
            col_map = {}
            for col in imp.columns:
                c = col.lower().strip()
                if "filial" in c or c == "fil_nr":
                    col_map["fil_nr"] = col
                elif "bundesland" in c:
                    col_map["bundesland"] = col
                elif "bezeichnung" in c or "name" in c:
                    col_map["bezeichnung"] = col
                elif "eröffnung" in c or "eroeffnung" in c or "datum" in c:
                    col_map["eroeffnung"] = col

            if "fil_nr" not in col_map or "bundesland" not in col_map:
                st.error(f"Fehlende Pflichtfelder. Gefundene Spalten: {imp.columns.tolist()}\n"
                         f"Erwartet: 'Filialnummer' und 'Bundesland'")
            else:
                imp = imp.rename(columns={v: k for k, v in col_map.items()})
                imp["fil_nr"] = imp["fil_nr"].str.strip()
                imp["bundesland"] = imp["bundesland"].str.strip().str.upper().str.replace("DE-", "")
                if "eroeffnung" in imp.columns:
                    imp["eroeffnung"] = imp["eroeffnung"].apply(
                        lambda x: _parse_date(str(x)) if pd.notna(x) else None
                    )

                st.markdown(f"**Vorschau ({len(imp)} Zeilen):**")
                st.dataframe(imp.head(10), use_container_width=True)

                if st.button("⬆️ Importieren (bisherige Daten werden überschrieben)", type="primary"):
                    conn.execute("DELETE FROM filialen")
                    imported, skipped = 0, []

                    for idx, row in imp.iterrows():
                        fil_nr = str(row.get("fil_nr", "")).strip()
                        bl     = str(row.get("bundesland", "")).strip().upper().replace("DE-", "")

                        if not fil_nr:
                            skipped.append({"Zeile": idx + 2, "Grund": "Filialnummer fehlt",
                                            "Daten": row.get("bezeichnung", "")})
                            continue
                        if not bl:
                            skipped.append({"Zeile": idx + 2, "Grund": "Bundesland fehlt",
                                            "Filialnummer": fil_nr})
                            continue

                        conn.execute("""
                            INSERT INTO filialen (fil_nr, bundesland, bezeichnung, eroeffnung)
                            VALUES (?,?,?,?)
                        """, (
                            fil_nr, bl,
                            str(row.get("bezeichnung", "")) or None,
                            row.get("eroeffnung") if pd.notna(row.get("eroeffnung", None)) else None,
                        ))
                        imported += 1

                    conn.commit()
                    st.success(f"✅ {imported} Filialen importiert. Alle bisherigen Daten wurden ersetzt.")

                    if skipped:
                        st.warning(f"⚠️ {len(skipped)} Zeilen wurden ignoriert:")
                        st.dataframe(pd.DataFrame(skipped), use_container_width=True, hide_index=True)

                    st.rerun()
        except Exception as e:
            st.error(f"Fehler beim Lesen der Datei: {e}")
