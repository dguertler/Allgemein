"""Database schema creation and migration for one SQLite file per GmbH."""
import sqlite3
from pathlib import Path


DDL = """
-- ── Branch master ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS filialen (
    fil_nr          TEXT PRIMARY KEY,
    bezeichnung     TEXT,
    bundesland      TEXT NOT NULL,          -- DE-RP, DE-HE, DE-BY …
    ort             TEXT,
    eroeffnung      TEXT,                   -- ISO date; NULL = bestehend
    flag_kein_wachstum   INTEGER NOT NULL DEFAULT 0,   -- 1 = kein % Aufschlag
    flag_manuell    INTEGER NOT NULL DEFAULT 0,   -- 1 = Monatswert wird überschrieben
    flag_neue_filiale INTEGER NOT NULL DEFAULT 0, -- 1 = neue Filiale (manueller Planwert)
    flag_inaktiv    INTEGER NOT NULL DEFAULT 0,   -- 1 = ab eroeffnung_ende geschlossen
    eroeffnung_ende TEXT,                   -- Schliessungsdatum
    ramadan_sensitiv INTEGER NOT NULL DEFAULT 0,  -- 1 = Filiale von Ramadan betroffen
    notiz           TEXT
);

-- ── Daily actuals ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ist_umsatz (
    fil_nr          TEXT NOT NULL,
    datum           TEXT NOT NULL,          -- ISO date
    umsatz          REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (fil_nr, datum)
);
CREATE INDEX IF NOT EXISTS idx_ist_datum ON ist_umsatz(datum);

-- ── Planning parameters (one row per plan year) ───────────────────────────
CREATE TABLE IF NOT EXISTS parameter (
    planjahr                INTEGER PRIMARY KEY,
    preiserhoehung_pct      REAL    NOT NULL DEFAULT 0.0,  -- z.B. 3.5 für 3,5 %

    -- Ferien-Pufferzeitraum (Wochen vor/nach Ferien für Ferienfaktor-Vergleich)
    ferien_puffer_wochen    INTEGER NOT NULL DEFAULT 3,

    -- Ramadan (leer = nicht aktiv)
    ramadan_vj_start        TEXT,           -- ISO date Vorjahr
    ramadan_vj_ende         TEXT,
    ramadan_plan_start      TEXT,           -- ISO date Planjahr
    ramadan_plan_ende       TEXT,
    ramadan_umsatz_pct      REAL DEFAULT 0.0,  -- % des Monatsumsatzes betroffen

    -- Fasching
    fasching_vj_start       TEXT,
    fasching_vj_ende        TEXT,
    fasching_plan_start     TEXT,
    fasching_plan_ende      TEXT,
    fasching_wirkung_pct    REAL DEFAULT 0.0   -- % Umsatzveränderung pro Tag-Differenz
);

-- ── Public holidays ────────────────────────────────────────────────────────
-- Bundesland codes: "alle" = bundesweit, sonst ISO z.B. "DE-RP"
CREATE TABLE IF NOT EXISTS feiertage (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    datum_plan      TEXT NOT NULL,          -- ISO date im Planjahr
    datum_vj        TEXT,                   -- ISO date im Vorjahr (für 1:1 Planung)
    name            TEXT NOT NULL,
    bundesland      TEXT NOT NULL DEFAULT 'alle'
);
CREATE INDEX IF NOT EXISTS idx_feiertage_datum ON feiertage(datum_plan);

-- ── Special days (Sondertage) ──────────────────────────────────────────────
-- methode: 'samstag' = Samstags-Umsatz der Filiale; 'referenz' = datum_referenz
CREATE TABLE IF NOT EXISTS sondertage (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    datum_plan      TEXT NOT NULL,
    datum_referenz  TEXT,                   -- Vorjahres-Referenztag
    bezeichnung     TEXT NOT NULL,
    methode         TEXT NOT NULL DEFAULT 'referenz',  -- 'samstag' | 'referenz'
    bundesland      TEXT NOT NULL DEFAULT 'alle'
);

-- ── School vacation periods ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ferien (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bundesland      TEXT NOT NULL,
    art             TEXT NOT NULL,          -- Osterferien, Sommerferien …
    start_vj        TEXT NOT NULL,
    ende_vj         TEXT NOT NULL,
    start_plan      TEXT NOT NULL,
    ende_plan       TEXT NOT NULL
);

-- ── Delivery customer monthly revenue ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS lieferkunden_monat (
    fil_nr          TEXT NOT NULL,
    jahr            INTEGER NOT NULL,
    monat           INTEGER NOT NULL,       -- 1–12
    ist_betrag      REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (fil_nr, jahr, monat)
);

-- ── New branch monthly plan values ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS neue_filialen_plan (
    fil_nr          TEXT NOT NULL,          -- kann Platzhalter sein z.B. "NEU_001"
    planjahr        INTEGER NOT NULL,
    monat           INTEGER NOT NULL,
    planwert        REAL NOT NULL DEFAULT 0,
    eroeffnung_datum TEXT,                  -- NULL = bereits im Monat offen
    PRIMARY KEY (fil_nr, planjahr, monat)
);

-- ── Manual monthly override for existing branches ─────────────────────────
CREATE TABLE IF NOT EXISTS planwert_override (
    fil_nr          TEXT NOT NULL,
    planjahr        INTEGER NOT NULL,
    monat           INTEGER NOT NULL,
    planwert        REAL NOT NULL,
    PRIMARY KEY (fil_nr, planjahr, monat)
);

-- ── Monthly growth rates ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS parameter_monat (
    planjahr     INTEGER NOT NULL,
    monat        INTEGER NOT NULL,  -- 1-12
    wachstum_pct REAL    NOT NULL DEFAULT 0.0,
    PRIMARY KEY (planjahr, monat)
);

-- ── Computed plan (written after each planning run) ───────────────────────
CREATE TABLE IF NOT EXISTS planung (
    fil_nr          TEXT NOT NULL,
    datum           TEXT NOT NULL,          -- ISO date im Planjahr
    wochentag       INTEGER NOT NULL,       -- 0=Mo … 6=So
    ist_vj          REAL,                   -- Vorjahres-Ist
    monatsumsatz_ist_hoch REAL,             -- hochgerechneter Ist-Monatsumsatz
    monatsumsatz_plan REAL,                 -- Monatsplan nach Erhöhung
    tagesumsatz_plan  REAL,                 -- tagesgenaue Planung
    liefer_plan     REAL,                   -- Lieferkunden-Anteil
    gesamt_plan     REAL,                   -- tagesumsatz_plan + liefer_plan
    tagestyp        TEXT,                   -- 'normal'|'feiertag'|'sondertag'|'ferien'|'geschlossen'
    feiertag_name   TEXT,
    ferien_art      TEXT,
    normalisierung  REAL,                   -- angewendeter Normalisierungsfaktor
    PRIMARY KEY (fil_nr, datum)
);
CREATE INDEX IF NOT EXISTS idx_planung_datum ON planung(datum);
"""


def get_db_path(gmbh_name: str, data_dir: str = "data") -> Path:
    safe = gmbh_name.replace(" ", "_").replace("/", "-")
    return Path(data_dir) / f"{safe}.db"


def init_db(db_path: str | Path) -> sqlite3.Connection:
    """Create (or open) the database and ensure the schema exists."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(DDL)
    _migrate(conn)
    conn.commit()
    return conn


def _migrate(conn: sqlite3.Connection):
    """Add columns that were missing due to schema bugs in earlier versions."""
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(filialen)").fetchall()
    }
    additions = [
        ("flag_kein_wachstum", "INTEGER NOT NULL DEFAULT 0"),
    ]
    for col, definition in additions:
        if col not in existing:
            conn.execute(f"ALTER TABLE filialen ADD COLUMN {col} {definition}")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS parameter_monat (
            planjahr     INTEGER NOT NULL,
            monat        INTEGER NOT NULL,
            wachstum_pct REAL    NOT NULL DEFAULT 0.0,
            PRIMARY KEY (planjahr, monat)
        )
    """)
