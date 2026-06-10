"""Filialverwaltung — inline editierbare Tabelle."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import get_conn, get_gmbh, require_db
import pandas as pd
from datetime import date

require_db()
conn = get_conn()
st.title("Filialverwaltung")

BL_ABBR_TO_NAME = {
    "BB": "Brandenburg", "BE": "Berlin", "BW": "Baden-Württemberg",
    "BY": "Bayern", "HB": "Bremen", "HE": "Hessen", "HH": "Hamburg",
    "MV": "Mecklenburg-Vorpommern", "NI": "Niedersachsen", "NW": "Nordrhein-Westfalen",
    "RP": "Rheinland-Pfalz", "SH": "Schleswig-Holstein", "SL": "Saarland",
    "SN": "Sachsen", "ST": "Sachsen-Anhalt", "TH": "Thüringen",
}
BL_NAME_TO_ABBR = {v: k for k, v in BL_ABBR_TO_NAME.items()}
BUNDESLAENDER = sorted(BL_ABBR_TO_NAME.values())


def _to_iso(v):
    if v is None:
        return None
    if isinstance(v, pd.Timestamp):
        return None if pd.isna(v) else v.strftime("%Y-%m-%d")
    return None


def _is_empty(val) -> bool:
    return str(val).strip().lower() in ("", "nan", "none", "nat")


def _truthy(val) -> bool:
    return str(val).strip().lower() in ("1", "true", "ja", "yes", "x")


def _bl_to_name(abbr_or_name: str) -> str:
    """Konvertiert BL-Kürzel → vollen Namen. Gibt vollen Namen unverändert zurück."""
    if not abbr_or_name:
        return abbr_or_name
    s = str(abbr_or_name).strip()
    return BL_ABBR_TO_NAME.get(s, s)


tab1, tab2 = st.tabs(["Filialen", "Massenimport"])

# ── Tab 1: Inline editierbare Tabelle ─────────────────────────────────────
with tab1:
    cols_needed = ["fil_nr", "bezeichnung", "bundesland", "eroeffnung_ende",
                   "flag_kein_wachstum", "eroeffnung", "geplanter_umsatz_monat"]
    existing_cols = [r[1] for r in conn.execute("PRAGMA table_info(filialen)").fetchall()]
    select_cols = [c for c in cols_needed if c in existing_cols]
    df = pd.read_sql(
        f"SELECT {', '.join(select_cols)} FROM filialen ORDER BY fil_nr",
        conn,
    )
    for c in cols_needed:
        if c not in df.columns:
            df[c] = None

    # Bundesland-Kürzel → voller Name
    df["bundesland"] = df["bundesland"].apply(
        lambda x: _bl_to_name(x) if x else x
    )

    for col in ["eroeffnung", "eroeffnung_ende"]:
        df[col] = pd.to_datetime(df[col], errors="coerce")
    df["flag_kein_wachstum"] = df["flag_kein_wachstum"].fillna(0).astype(bool)
    df["geplanter_umsatz_monat"] = pd.to_numeric(
        df["geplanter_umsatz_monat"], errors="coerce"
    ).fillna(0.0)

    # Lösch-Spalte am Anfang
    df.insert(0, "Löschen", False)

    st.markdown(
        f"**{len(df)} Filialen** in der Datenbank — "
        "Zeilen direkt bearbeiten, neue Zeile unten anhängen, dann Speichern. "
        "Zum Löschen die Checkbox in der ersten Spalte setzen."
    )

    edited = st.data_editor(
        df,
        column_config={
            "Löschen": st.column_config.CheckboxColumn("🗑️", width=45),
            "fil_nr": st.column_config.TextColumn("Fil.-Nr.", width=80),
            "bezeichnung": st.column_config.TextColumn("Bezeichnung"),
            "bundesland": st.column_config.SelectboxColumn(
                "Bundesland", options=BUNDESLAENDER, width=190
            ),
            "eroeffnung_ende": st.column_config.DateColumn(
                "Schließdatum", format="DD.MM.YYYY", width=120
            ),
            "flag_kein_wachstum": st.column_config.CheckboxColumn(
                "Kein Wachstum", width=105
            ),
            "eroeffnung": st.column_config.DateColumn(
                "Eröffnung", format="DD.MM.YYYY", width=110
            ),
            "geplanter_umsatz_monat": st.column_config.NumberColumn(
                "Geplanter Umsatz/Monat €",
                min_value=0,
                format="%.0f",
                width=180,
            ),
        },
        column_order=[
            "Löschen", "fil_nr", "bezeichnung", "bundesland", "eroeffnung_ende",
            "flag_kein_wachstum", "eroeffnung", "geplanter_umsatz_monat",
        ],
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        height=600,
        key="filialen_editor",
    )

    # Validierungs-Warnungen
    for _, row in edited.iterrows():
        fn = str(row.get("fil_nr", "")).strip()
        if not fn or _is_empty(fn):
            continue
        eroff = row.get("eroeffnung")
        gum = float(row.get("geplanter_umsatz_monat") or 0)
        has_date = isinstance(eroff, pd.Timestamp) and not pd.isna(eroff)
        if has_date and gum == 0.0:
            st.warning(
                f"Filiale {fn}: Eröffnungsdatum gesetzt, aber 'Geplanter Umsatz/Monat' ist 0. "
                "Bitte Planwert eintragen."
            )

    to_delete = edited[edited["Löschen"] == True]["fil_nr"].dropna().astype(str).str.strip().tolist()
    to_delete = [fn for fn in to_delete if fn and not _is_empty(fn)]

    # Auto-save: detect changes (excluding Löschen column)
    compare_cols = [c for c in df.columns if c != "Löschen"]
    try:
        orig_str = df[compare_cols].reset_index(drop=True).astype(str)
        edit_str = edited[compare_cols].reset_index(drop=True).astype(str)
        data_changed = not orig_str.equals(edit_str)
    except Exception:
        data_changed = True

    if data_changed:
        save_df = edited[edited["Löschen"] != True].copy()
        saved = 0
        for _, row in save_df.iterrows():
            fn = str(row.get("fil_nr", "")).strip()
            if not fn or _is_empty(fn):
                continue
            bl = str(row.get("bundesland") or "").strip()
            if not bl:
                bl = BUNDESLAENDER[0]
            bezeichnung = str(row.get("bezeichnung") or "").strip() or None
            eroeffnung_iso = _to_iso(row.get("eroeffnung"))
            eroeffnung_ende_iso = _to_iso(row.get("eroeffnung_ende"))
            kein_wachstum = int(bool(row.get("flag_kein_wachstum")))
            gum = float(row.get("geplanter_umsatz_monat") or 0)

            conn.execute("""
                INSERT OR REPLACE INTO filialen
                    (fil_nr, bezeichnung, bundesland, eroeffnung, eroeffnung_ende,
                     flag_kein_wachstum, geplanter_umsatz_monat)
                VALUES (?,?,?,?,?,?,?)
            """, (fn, bezeichnung, bl, eroeffnung_iso, eroeffnung_ende_iso,
                  kein_wachstum, gum))

            if eroeffnung_iso and gum > 0:
                try:
                    eroff_date = date.fromisoformat(eroeffnung_iso)
                    pfj = eroff_date.year
                    for monat in range(1, 13):
                        planwert = gum * 0.5 if monat == eroff_date.month else gum
                        if monat < eroff_date.month:
                            planwert = 0.0
                        conn.execute("""
                            INSERT OR REPLACE INTO neue_filialen_plan
                                (fil_nr, planjahr, monat, planwert, eroeffnung_datum)
                            VALUES (?,?,?,?,?)
                        """, (fn, pfj, monat, planwert, eroeffnung_iso))
                except Exception:
                    pass
            saved += 1

        if saved > 0:
            conn.commit()
            st.toast(f"✓ {saved} Filiale(n) gespeichert", icon="✅")

    col_del_area = st.container()
    with col_del_area:
        if to_delete:
            if st.button(
                f"🗑️ {len(to_delete)} Filiale(n) löschen",
                type="secondary",
                key="del_marked_btn",
            ):
                st.session_state["pending_delete"] = to_delete
                st.rerun()

    if st.session_state.get("pending_delete"):
        fns = st.session_state["pending_delete"]
        st.warning(
            f"Wollen Sie wirklich folgende Filiale(n) löschen? "
            f"**{', '.join(sorted(fns))}**\n\n"
            "Alle zugehörigen Planungsdaten werden ebenfalls entfernt."
        )
        c_yes, c_no, _ = st.columns([1, 1, 4])
        if c_yes.button("Ja, löschen", key="del_confirm_yes", type="primary"):
            for fn in fns:
                conn.execute("DELETE FROM filialen WHERE fil_nr=?", (fn,))
            conn.commit()
            st.session_state.pop("pending_delete", None)
            st.success(f"Gelöscht: {', '.join(sorted(fns))}")
            st.rerun()
        if c_no.button("Abbrechen", key="del_confirm_no"):
            st.session_state.pop("pending_delete", None)
            st.rerun()

# ── Tab 2: Massenimport ────────────────────────────────────────────────────
with tab2:
    st.subheader("Stammdaten aus Datei importieren")
    st.info("""
    **Pflichtfelder:** Filialnummer, Bundesland
    **Optional:** Bezeichnung, Schließdatum, Kein Wachstum, Eröffnung, Geplanter Umsatz/Monat

    Ein neuer Import **überschreibt alle bisherigen Stammdaten** vollständig.
    """)

    if "import_result" in st.session_state:
        res = st.session_state.pop("import_result")
        st.success(f"{res['imported']} Filialen importiert.")
        if res["skipped"]:
            st.warning(f"{len(res['skipped'])} Zeilen ignoriert (Pflichtfelder fehlten):")
            st.dataframe(pd.DataFrame(res["skipped"]), use_container_width=True, hide_index=True)

    uploaded = st.file_uploader(
        "CSV oder Excel hochladen", type=["csv", "xlsx"], key="stamm_upload"
    )
    if uploaded:
        try:
            if uploaded.name.endswith(".csv"):
                imp = pd.read_csv(uploaded, dtype=str)
            else:
                imp = pd.read_excel(uploaded, dtype=str)

            all_cols = imp.columns.tolist()
            NONE_OPTION = "-- nicht vorhanden --"
            options_required = all_cols
            options_optional = [NONE_OPTION] + all_cols

            auto = {}
            for col in all_cols:
                c = col.lower().strip()
                if "filial" in c or c == "fil_nr":
                    auto.setdefault("fil_nr", col)
                elif "bundesland" in c:
                    auto.setdefault("bundesland", col)
                elif "bezeichnung" in c or "name" in c:
                    auto.setdefault("bezeichnung", col)
                elif "schliess" in c or "schliessdatum" in c or "ende" in c:
                    auto.setdefault("eroeffnung_ende", col)
                elif "wachstum" in c:
                    auto.setdefault("kein_wachstum", col)
                elif "eroeffnung" in c or "eroeffnungsdatum" in c:
                    auto.setdefault("eroeffnung", col)
                elif "geplant" in c or "umsatz_monat" in c:
                    auto.setdefault("geplanter_umsatz_monat", col)

            st.markdown("**Spaltenzuordnung** *(automatisch erkannt)*")
            c1, c2, c3, c4, c5, c6, c7 = st.columns(7)

            def _idx(lst, val):
                return lst.index(val) if val in lst else 0

            with c1:
                map_fil_nr = st.selectbox("Filialnummer *(Pflicht)*", options_required,
                    index=_idx(options_required, auto.get("fil_nr", all_cols[0])), key="map_fil_nr")
            with c2:
                map_bundesland = st.selectbox("Bundesland *(Pflicht)*", options_required,
                    index=_idx(options_required, auto.get("bundesland", all_cols[0])), key="map_bl")
            with c3:
                map_bezeichnung = st.selectbox("Bezeichnung *(optional)*", options_optional,
                    index=_idx(options_optional, auto.get("bezeichnung", NONE_OPTION)), key="map_bez")
            with c4:
                map_eroeffnung_ende = st.selectbox("Schließdatum *(optional)*", options_optional,
                    index=_idx(options_optional, auto.get("eroeffnung_ende", NONE_OPTION)), key="map_ende")
            with c5:
                map_kein_wachstum = st.selectbox("Kein Wachstum *(optional)*", options_optional,
                    index=_idx(options_optional, auto.get("kein_wachstum", NONE_OPTION)), key="map_kw")
            with c6:
                map_eroeffnung = st.selectbox("Eröffnung *(optional)*", options_optional,
                    index=_idx(options_optional, auto.get("eroeffnung", NONE_OPTION)), key="map_eroff")
            with c7:
                map_gum = st.selectbox("Geplanter Umsatz/Monat *(optional)*", options_optional,
                    index=_idx(options_optional, auto.get("geplanter_umsatz_monat", NONE_OPTION)),
                    key="map_gum")

            if map_fil_nr == map_bundesland:
                st.error("Filialnummer und Bundesland dürfen nicht dieselbe Spalte sein.")
            else:
                def _parse_date_str(val) -> str | None:
                    from datetime import datetime
                    if not val or _is_empty(str(val)):
                        return None
                    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
                        try:
                            return datetime.strptime(str(val).strip(), fmt).strftime("%Y-%m-%d")
                        except ValueError:
                            pass
                    return None

                preview = pd.DataFrame()
                preview["Filialnummer"] = imp[map_fil_nr].str.strip()
                preview["Bundesland"] = imp[map_bundesland].str.strip().apply(
                    lambda x: _bl_to_name(str(x).upper().replace("DE-", ""))
                )
                if map_bezeichnung != NONE_OPTION:
                    preview["Bezeichnung"] = imp[map_bezeichnung]
                if map_eroeffnung_ende != NONE_OPTION:
                    preview["Schließdatum"] = imp[map_eroeffnung_ende].apply(
                        lambda x: _parse_date_str(x)
                    )
                if map_kein_wachstum != NONE_OPTION:
                    preview["Kein Wachstum"] = imp[map_kein_wachstum].apply(_truthy)
                if map_eroeffnung != NONE_OPTION:
                    preview["Eröffnung"] = imp[map_eroeffnung].apply(
                        lambda x: _parse_date_str(x)
                    )
                if map_gum != NONE_OPTION:
                    preview["Geplanter Umsatz/Monat"] = pd.to_numeric(
                        imp[map_gum], errors="coerce"
                    ).fillna(0.0)

                st.markdown(f"**Vorschau ({len(preview)} Zeilen):**")
                st.dataframe(preview.head(10), use_container_width=True, hide_index=True)

                if st.button("Importieren (bisherige Daten werden überschrieben)", type="primary"):
                    conn.execute("DELETE FROM filialen")
                    imported, skipped = 0, []

                    for idx, row in preview.iterrows():
                        fn = str(row.get("Filialnummer", "")).strip()
                        bl = str(row.get("Bundesland", "")).strip()

                        if _is_empty(fn):
                            skipped.append({"Zeile": idx + 2, "Grund": "Filialnummer fehlt",
                                            "Bezeichnung": row.get("Bezeichnung", "")})
                            continue
                        if _is_empty(bl):
                            skipped.append({"Zeile": idx + 2, "Grund": "Bundesland fehlt",
                                            "Filialnummer": fn})
                            continue

                        kw = int(bool(row.get("Kein Wachstum", False))) if "Kein Wachstum" in row else 0
                        gum = float(row.get("Geplanter Umsatz/Monat", 0) or 0) if "Geplanter Umsatz/Monat" in row else 0.0
                        eroeffnung = row.get("Eröffnung") if "Eröffnung" in row else None
                        eroeffnung_ende = row.get("Schließdatum") if "Schließdatum" in row else None

                        conn.execute("""
                            INSERT INTO filialen
                                (fil_nr, bundesland, bezeichnung, eroeffnung, eroeffnung_ende,
                                 flag_kein_wachstum, geplanter_umsatz_monat)
                            VALUES (?,?,?,?,?,?,?)
                        """, (
                            fn, bl,
                            str(row.get("Bezeichnung", "")) or None,
                            eroeffnung if eroeffnung and not _is_empty(str(eroeffnung)) else None,
                            eroeffnung_ende if eroeffnung_ende and not _is_empty(str(eroeffnung_ende)) else None,
                            kw, gum,
                        ))
                        imported += 1

                    conn.commit()
                    st.session_state["import_result"] = {"imported": imported, "skipped": skipped}
                    st.rerun()
        except Exception as e:
            st.error(f"Fehler beim Lesen der Datei: {e}")
