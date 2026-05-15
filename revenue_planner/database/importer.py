"""Import IST revenue data from Excel / CSV into the database."""
import sqlite3
import pandas as pd
from pathlib import Path


def import_ist_umsatz(conn: sqlite3.Connection, file_path: str | Path) -> tuple[int, list[str]]:
    """
    Import daily actuals from a file with columns:
        Datum | Filialnummer | Umsatz brutto
    (plus optional extra columns that are ignored)

    Returns (rows_inserted, warnings).
    """
    path = Path(file_path)
    warnings: list[str] = []

    if path.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(path, dtype=str)
    else:
        df = pd.read_csv(path, dtype=str, sep=None, engine="python")

    # Flexible column mapping
    col_map = _detect_columns(df.columns.tolist())
    missing = [k for k, v in col_map.items() if v is None]
    if missing:
        raise ValueError(f"Pflichtfelder nicht gefunden: {missing}. Vorhandene Spalten: {df.columns.tolist()}")

    df = df.rename(columns={col_map["datum"]: "datum",
                             col_map["fil_nr"]: "fil_nr",
                             col_map["umsatz"]: "umsatz"})

    # Normalise dates → ISO format (try ISO8601 first, fall back to dayfirst for European formats)
    df["datum"] = pd.to_datetime(df["datum"], format="ISO8601", errors="coerce")
    still_bad = df["datum"].isna()
    if still_bad.any():
        df.loc[still_bad, "datum"] = pd.to_datetime(
            df.loc[still_bad, df.columns[0]], dayfirst=True, errors="coerce"
        )
    df["datum"] = df["datum"].dt.strftime("%Y-%m-%d")
    bad_dates = df["datum"].isna().sum()
    if bad_dates:
        warnings.append(f"{bad_dates} Zeilen mit ungültigem Datum wurden übersprungen.")
    df = df.dropna(subset=["datum"])

    # Normalise branch number → strip whitespace, zero-pad to 4 digits if numeric
    df["fil_nr"] = df["fil_nr"].str.strip()

    # Normalise revenue → float, round to 2 decimal places
    df["umsatz"] = pd.to_numeric(df["umsatz"].str.replace(",", "."), errors="coerce").round(2)
    bad_rev = df["umsatz"].isna().sum()
    if bad_rev:
        warnings.append(f"{bad_rev} Zeilen mit ungültigem Umsatz wurden auf 0 gesetzt.")
    df["umsatz"] = df["umsatz"].fillna(0)

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


def ensure_filialen_from_ist(conn: sqlite3.Connection, bundesland_default: str = "DE-RP") -> int:
    """Auto-create filiale entries for any fil_nr present in ist_umsatz but missing in filialen."""
    cur = conn.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO filialen (fil_nr, bundesland)
        SELECT DISTINCT fil_nr, ? FROM ist_umsatz
    """, (bundesland_default,))
    conn.commit()
    return cur.rowcount
