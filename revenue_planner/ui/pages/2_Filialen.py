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
st.title("Filialverwaltung")
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
                                  "eroeffnung_ende", "flag_kein_wachstum"] if c in df.columns]
        display = df[show_cols].copy()
        display["eroeffnung"] = display["eroeffnung"].apply(_fmt_date)
        if "eroeffnung_ende" in display.columns:
            display["eroeffnung_ende"] = display["eroeffnung_ende"].apply(_fmt_date)
        if "flag_kein_wachstum" in display.columns:
            display["flag_kein_wachstum"] = display["flag_kein_wachstum"].apply(lambda x: "✅" if x else "")
        display = display.rename(columns={
            "fil_nr": "Fil.-Nr.", "bezeichnung": "Bezeichnung", "bundesland": "Bundesland",
            "eroeffnung": "Eröffnung", "eroeffnung_ende": "Schließdatum",
            "flag_kein_wachstum": "Kein Wachstum",
        })
        st.dataframe(display, use_container_width=True, hide_index=True,
            column_config={
                "Fil.-Nr.":      st.column_config.TextColumn(width=80),
                "Bundesland":    st.column_config.TextColumn(width=90),
                "Eröffnung":     st.column_config.TextColumn(width=100),
                "Schließdatum":  st.column_config.TextColumn(width=105),
                "Kein Wachstum": st.column_config.TextColumn(width=105),
            })

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
                eroeffnung_ende_in = st.text_input(
                    "Schließdatum",
                    value=_fmt_date(row.get("eroeffnung_ende")),
                    placeholder="TT.MM.JJJJ  (leer = dauerhaft geöffnet)",
                    help="Letzter Öffnungstag. Ab dem Folgetag wird kein Umsatz mehr geplant."
                )

            if st.form_submit_button("💾 Speichern"):
                conn.execute("""
                    UPDATE filialen
                    SET bezeichnung=?, bundesland=?, eroeffnung=?,
                        flag_kein_wachstum=?, eroeffnung_ende=?
                    WHERE fil_nr=?
                """, (
                    bezeichnung or None,
                    bundesland,
                    _parse_date(eroeffnung_in),
                    int(kein_wachstum),
                    _parse_date(eroeffnung_ende_in),
                    selected,
                ))
                conn.commit()
                st.success("✅ Gespeichert.")
                st.rerun()

        st.markdown("")
        if st.button("🗑️ Filiale löschen", key="init_delete"):
            st.session_state["delete_confirm"] = selected

        if st.session_state.get("delete_confirm") == selected:
            st.warning(f"Filiale **{selected}** wirklich löschen? Alle zugehörigen Planungsdaten werden entfernt.")
            c_yes, c_no, _ = st.columns([1, 1, 5])
            if c_yes.button("✅ Ja, löschen", key="confirm_yes"):
                conn.execute("DELETE FROM filialen WHERE fil_nr=?", (selected,))
                conn.commit()
                st.session_state.pop("delete_confirm", None)
                st.rerun()
            if c_no.button("❌ Abbrechen", key="confirm_no"):
                st.session_state.pop("delete_confirm", None)
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

    # Show import result after rerun
    if "import_result" in st.session_state:
        res = st.session_state.pop("import_result")
        st.success(f"✅ {res['imported']} Filialen importiert. Alle bisherigen Daten wurden ersetzt.")
        if res["skipped"]:
            st.warning(f"⚠️ {len(res['skipped'])} Zeilen ignoriert (Pflichtfelder fehlten):")
            st.dataframe(pd.DataFrame(res["skipped"]), use_container_width=True, hide_index=True)

    uploaded = st.file_uploader("CSV oder Excel hochladen", type=["csv", "xlsx"], key="stamm_upload")
    if uploaded:
        try:
            if uploaded.name.endswith(".csv"):
                imp = pd.read_csv(uploaded, dtype=str)
            else:
                imp = pd.read_excel(uploaded, dtype=str)

            all_cols = imp.columns.tolist()
            NONE_OPTION = "— nicht vorhanden —"
            options_required = all_cols
            options_optional = [NONE_OPTION] + all_cols

            # Auto-detect columns
            auto = {}
            for col in all_cols:
                c = col.lower().strip()
                if "filial" in c or c == "fil_nr":
                    auto.setdefault("fil_nr", col)
                elif "bundesland" in c:
                    auto.setdefault("bundesland", col)
                elif "bezeichnung" in c or "name" in c:
                    auto.setdefault("bezeichnung", col)
                elif "eröffnung" in c or "eroeffnung" in c or "datum" in c:
                    auto.setdefault("eroeffnung", col)
                elif "wachstum" in c:
                    auto.setdefault("kein_wachstum", col)

            st.markdown("**Spaltenzuordnung** *(automatisch erkannt — bei Bedarf anpassen)*")
            col1, col2, col3, col4, col5 = st.columns(5)

            def _idx(lst, val):
                return lst.index(val) if val in lst else 0

            with col1:
                map_fil_nr = st.selectbox(
                    "Filialnummer *(Pflicht)*",
                    options_required,
                    index=_idx(options_required, auto.get("fil_nr", all_cols[0])),
                    key="map_fil_nr",
                )
            with col2:
                map_bundesland = st.selectbox(
                    "Bundesland *(Pflicht)*",
                    options_required,
                    index=_idx(options_required, auto.get("bundesland", all_cols[0])),
                    key="map_bundesland",
                )
            with col3:
                map_bezeichnung = st.selectbox(
                    "Bezeichnung *(optional)*",
                    options_optional,
                    index=_idx(options_optional, auto.get("bezeichnung", NONE_OPTION)),
                    key="map_bezeichnung",
                )
            with col4:
                map_eroeffnung = st.selectbox(
                    "Eröffnungsdatum *(optional)*",
                    options_optional,
                    index=_idx(options_optional, auto.get("eroeffnung", NONE_OPTION)),
                    key="map_eroeffnung",
                )
            with col5:
                map_kein_wachstum = st.selectbox(
                    "Kein Wachstum *(optional)*",
                    options_optional,
                    index=_idx(options_optional, auto.get("kein_wachstum", NONE_OPTION)),
                    key="map_kein_wachstum",
                )

            if map_fil_nr == map_bundesland:
                st.error("Filialnummer und Bundesland dürfen nicht dieselbe Spalte sein.")
            else:
                def _is_empty(val) -> bool:
                    return str(val).strip().lower() in ("", "nan", "none", "nat")

                def _truthy(val) -> bool:
                    return str(val).strip().lower() in ("1", "true", "ja", "yes", "x", "✅")

                # Build preview with mapped columns
                preview = pd.DataFrame()
                preview["Filialnummer"] = imp[map_fil_nr].str.strip()
                preview["Bundesland"]   = imp[map_bundesland].str.strip().str.upper().str.replace("DE-", "", regex=False)
                if map_bezeichnung != NONE_OPTION:
                    preview["Bezeichnung"] = imp[map_bezeichnung]
                if map_eroeffnung != NONE_OPTION:
                    preview["Eröffnung"] = imp[map_eroeffnung].apply(
                        lambda x: _parse_date(str(x)) if pd.notna(x) and not _is_empty(x) else None
                    )
                if map_kein_wachstum != NONE_OPTION:
                    preview["Kein Wachstum"] = imp[map_kein_wachstum].apply(_truthy)

                st.markdown(f"**Vorschau ({len(preview)} Zeilen):**")
                st.dataframe(preview.head(10), use_container_width=True, hide_index=True,
                    column_config={
                        "Filialnummer":  st.column_config.TextColumn(width=100),
                        "Bundesland":    st.column_config.TextColumn(width=90),
                        "Bezeichnung":   st.column_config.TextColumn(width=180),
                        "Eröffnung":     st.column_config.TextColumn(width=100),
                        "Kein Wachstum": st.column_config.CheckboxColumn(width=110),
                    })

                if st.button("⬆️ Importieren (bisherige Daten werden überschrieben)", type="primary"):
                    conn.execute("DELETE FROM filialen")
                    imported, skipped = 0, []

                    for idx, row in preview.iterrows():
                        fil_nr = str(row.get("Filialnummer", "")).strip()
                        bl     = str(row.get("Bundesland", "")).strip().upper().replace("DE-", "")

                        if _is_empty(fil_nr):
                            skipped.append({"Zeile": idx + 2,
                                            "Grund": "Filialnummer fehlt — Zeile nicht importiert",
                                            "Bezeichnung": row.get("Bezeichnung", "")})
                            continue
                        if _is_empty(bl):
                            skipped.append({"Zeile": idx + 2,
                                            "Grund": "Bundesland fehlt — Zeile nicht importiert",
                                            "Filialnummer": fil_nr})
                            continue

                        kw = int(bool(row.get("Kein Wachstum", False))) if "Kein Wachstum" in row else 0
                        conn.execute("""
                            INSERT INTO filialen (fil_nr, bundesland, bezeichnung, eroeffnung, flag_kein_wachstum)
                            VALUES (?,?,?,?,?)
                        """, (
                            fil_nr, bl,
                            str(row.get("Bezeichnung", "")) or None,
                            row.get("Eröffnung") if "Eröffnung" in row and not _is_empty(row.get("Eröffnung", "")) else None,
                            kw,
                        ))
                        imported += 1

                    conn.commit()
                    st.session_state["import_result"] = {"imported": imported, "skipped": skipped}
                    st.rerun()
        except Exception as e:
            st.error(f"Fehler beim Lesen der Datei: {e}")
