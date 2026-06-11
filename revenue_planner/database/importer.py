"""Import IST revenue data from Excel / CSV into the database."""
import io
import sqlite3
import pandas as pd
from pathlib import Path


def import_ist_umsatz(
    conn: sqlite3.Connection,
    file_path,
    file_name: str = "",
) -> tuple[int, list[str]]:
    """
    Import daily actuals from a file with columns:
        Datum | Filialnummer | Umsatz brutto
    (plus optional extra columns that are ignored)

    Accepts either a path (str/Path) or a file-like object (BytesIO/UploadedFile).

    Returns (rows_inserted, warnings).
    """
    warnings: list[str] = []

    # Determine file extension for format detection
    if hasattr(file_path, "read"):
        # File-like object — read into BytesIO
        data = io.BytesIO(file_path.read())
        suffix = Path(file_name).suffix.lower() if file_name else ""
    else:
        path = Path(file_path)
        data = path
        suffix = path.suffix.lower()

    if suffix in (".xlsx", ".xls"):
        df = pd.read_excel(data, dtype=str)
    else:
        if hasattr(data, "read"):
            df = pd.read_csv(data, dtype=str, sep=None, engine="python")
        else:
            df = pd.read_csv(str(data), dtype=str, sep=None, engine="python")

    # Flexible column mapping
    col_map = _detect_columns(df.columns.tolist())
    missing = [k for k, v in col_map.items() if v is None]
    if missing:
        raise ValueError(f"Pflichtfelder nicht gefunden: {missing}. Vorhandene Spalten: {df.columns.tolist()}")

    df = df.rename(columns={col_map["datum"]: "datum",
                             col_map["fil_nr"]: "fil_nr",
                             col_map["umsatz"]: "umsatz"})

    # Normalise dates → ISO format (try ISO8601 first, fall back to dayfirst for European formats)
    raw_datum = df["datum"].copy()
    parsed = pd.to_datetime(raw_datum, format="ISO8601", errors="coerce")
    still_bad = parsed.isna()
    if still_bad.any():
        # Fall back to European day-first parsing on the ORIGINAL strings.
        # (Bug fixed 06/2026: previously re-parsed the already-coerced NaT
        # column, silently dropping all German DD.MM.YYYY rows.)
        parsed.loc[still_bad] = pd.to_datetime(
            raw_datum.loc[still_bad], dayfirst=True, errors="coerce"
        )
    df["datum"] = parsed.dt.strftime("%Y-%m-%d")
    bad_dates = df["datum"].isna().sum()
    if bad_dates:
        warnings.append(f"{bad_dates} Zeilen mit ungültigem Datum wurden übersprungen.")
    df = df.dropna(subset=["datum"])

    # Normalise branch number → strip whitespace
    df["fil_nr"] = df["fil_nr"].astype(str).str.strip()

    # Skip rows where fil_nr is empty/nan/none
    empty_fil = df["fil_nr"].isin(["", "nan", "none", "NaN", "None"]) | df["fil_nr"].isna()
    n_empty_fil = int(empty_fil.sum())
    if n_empty_fil:
        warnings.append(f"{n_empty_fil} Zeilen ohne Filialnummer wurden übersprungen.")
    df = df[~empty_fil]

    # Normalise revenue → float, round to 2 decimal places
    def _parse_num(s: str) -> float:
        s = str(s).strip().replace('\xa0', '').replace(' ', '')
        if ',' in s and '.' in s:
            return pd.to_numeric(s.replace('.', '').replace(',', '.'), errors='coerce')
        elif ',' in s:
            return pd.to_numeric(s.replace(',', '.'), errors='coerce')
        elif '.' in s:
            parts = s.split('.')
            if len(parts) > 1 and all(len(p) == 3 for p in parts[1:]):
                return pd.to_numeric(s.replace('.', ''), errors='coerce')
            return pd.to_numeric(s, errors='coerce')
        return pd.to_numeric(s, errors='coerce')

    df["umsatz"] = df["umsatz"].apply(_parse_num).round(2)
    bad_rev = df["umsatz"].isna().sum()
    if bad_rev:
        warnings.append(f"{bad_rev} Zeilen mit ungültigem Umsatz wurden übersprungen.")
    df = df.dropna(subset=["umsatz"])

    rows = [{"fil_nr": r.fil_nr, "datum": r.datum, "umsatz": r.umsatz}
            for r in df[["fil_nr", "datum", "umsatz"]].itertuples()]

    cur = conn.cursor()
    cur.executemany(
        "INSERT OR REPLACE INTO ist_umsatz (fil_nr, datum, umsatz) VALUES (:fil_nr, :datum, :umsatz)",
        rows,
    )
    conn.commit()
    return len(rows), warnings


def _detect_columns(columns: list[str]) -> dict[str, str | None]:
    """Fuzzy-match the three required columns regardless of exact naming."""
    lower = {c.lower().strip(): c for c in columns}

    def find(candidates):
        for c in candidates:
            for k, original in lower.items():
                if c in k:
                    return original
        return None

    return {
        "datum":  find(["datum", "date", "tag"]),
        "fil_nr": find(["filialnummer", "filnr", "fil_nr", "filiale", "fg", "fachgeschäft"]),
        "umsatz": find(["umsatz", "revenue", "erlös", "betrag", "umsatz brutto"]),
    }


def detect_oeffnungstage(conn: sqlite3.Connection, force: bool = False) -> dict:
    """
    Erkenne aus den IST-Daten je Filiale:
      - an welchen Wochentagen geöffnet (Umsatz > 0 in >=30% der Vorkommen)
      - an welchen Feiertagen historisch geöffnet (Umsatz > 0 am Feiertags-Vorjahrestag)

    force=False  → nur Filialen ohne bestehende Einträge befüllen (manuelle Edits bleiben).
    force=True   → alles neu erkennen (überschreibt).

    Returns dict mit Zählern.
    """
    df = pd.read_sql("SELECT fil_nr, datum, umsatz FROM ist_umsatz", conn)
    if df.empty:
        return {"weekday_branches": 0, "holiday_entries": 0}
    df["datum"] = pd.to_datetime(df["datum"])
    df["wt"] = df["datum"].dt.weekday

    cur = conn.cursor()
    existing_wd = {r[0] for r in cur.execute("SELECT DISTINCT fil_nr FROM filial_oeffnung").fetchall()}

    wd_branches = 0
    for fil_nr, g in df.groupby("fil_nr"):
        if not force and fil_nr in existing_wd:
            continue
        for wt in range(7):
            sub = g[g["wt"] == wt]
            total = len(sub)
            with_rev = int((sub["umsatz"] > 0).sum())
            offen = 1 if (total > 0 and with_rev / total >= 0.30) else 0
            cur.execute(
                "INSERT OR REPLACE INTO filial_oeffnung (fil_nr, wochentag, offen) VALUES (?,?,?)",
                (fil_nr, wt, offen),
            )
        wd_branches += 1

    # Feiertags-Öffnung: je Filiale × Feiertag prüfen, ob am datum_vj Umsatz vorlag
    feiertage = cur.execute(
        "SELECT DISTINCT name, datum_vj FROM feiertage WHERE datum_vj IS NOT NULL"
    ).fetchall()
    existing_ft = {(r[0], r[1]) for r in cur.execute(
        "SELECT fil_nr, feiertag_name FROM filial_feiertag").fetchall()}

    rev_lookup = {(r.fil_nr, r.datum.strftime("%Y-%m-%d")): r.umsatz
                  for r in df.itertuples()}
    # Zusätzlich: max. Umsatz je (Filiale, Monat-Tag) über alle Jahre (für feste Feiertage)
    df_md = df.assign(md=df["datum"].dt.strftime("%m-%d"))
    md_series = df_md.groupby(["fil_nr", "md"])["umsatz"].max()
    md_lookup: dict[tuple, float] = {idx: float(v) for idx, v in md_series.items()}

    ft_entries = 0
    all_fils = [r[0] for r in cur.execute("SELECT fil_nr FROM filialen").fetchall()]
    for fil_nr in all_fils:
        for ft in feiertage:
            name, datum_vj = ft["name"], ft["datum_vj"]
            if not force and (fil_nr, name) in existing_ft:
                continue
            umsatz = rev_lookup.get((fil_nr, datum_vj), 0.0)
            if not (umsatz and umsatz > 0) and datum_vj:
                umsatz = md_lookup.get((fil_nr, datum_vj[5:]), 0.0)  # 'YYYY-MM-DD' → 'MM-DD'
            offen = 1 if (umsatz and umsatz > 0) else 0
            cur.execute(
                "INSERT OR REPLACE INTO filial_feiertag (fil_nr, feiertag_name, offen) VALUES (?,?,?)",
                (fil_nr, name, offen),
            )
            ft_entries += 1

    conn.commit()
    return {"weekday_branches": wd_branches, "holiday_entries": ft_entries}


def ensure_filialen_from_ist(conn: sqlite3.Connection, bundesland_default: str = "DE-RP") -> int:
    """Auto-create filiale entries for any fil_nr present in ist_umsatz but missing in filialen."""
    cur = conn.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO filialen (fil_nr, bundesland)
        SELECT DISTINCT fil_nr, ? FROM ist_umsatz
    """, (bundesland_default,))
    conn.commit()
    return cur.rowcount
