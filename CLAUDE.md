# CLAUDE.md — Filialumsatzplanung (Bäcker Görtz / Papperts)

> **Wichtig für Claude Code:** Diese Datei IMMER zuerst lesen, bevor Änderungen
> vorgenommen oder Fragen beantwortet werden. Sie ist die zentrale Wissensdatei.
>
> **Pflicht bei JEDER Änderung am Code:** Diese Datei mitpflegen — neue Erkenntnisse,
> geänderte Logik, neue Stolperfallen, erledigte/neue TODOs hier dokumentieren.
>
> **Pflicht am Ende jeder Sitzung:** Alle Änderungen mit Git-Hash zusammenfassen und
> Download-Link der Branch ausgeben, z. B.:
> `https://github.com/dguertler/Allgemein/archive/refs/heads/claude/branch-revenue-planning-kuVgL.zip`

---

## 1. Projektüberblick

**Ziel:** Web-App (Streamlit + SQLite) zur tagesgenauen Umsatzplanung (Budget) für
ca. 255 Filialen der Bäcker Görtz / Papperts Gruppe. Ersetzt eine manuelle
Excel-Budgetierung. **Stellenwert: sehr hoch** — das komplette Unternehmensbudget
basiert auf diesen Berechnungen. Fehlerrobustheit und Nachvollziehbarkeit jedes
Rechenschritts haben oberste Priorität.

**Stack:** Python 3.11+, Streamlit 1.35+, SQLite (eine `.db` je GmbH/Mandant),
Pandas, openpyxl, holidays, Pillow.
Start: `streamlit run revenue_planner/app.py`

---

## 2. Verzeichnisstruktur

```
revenue_planner/
├── app.py                          # Einstiegspunkt, Navigation, Logos
├── database/
│   ├── schema.py                   # DDL + Migration (_migrate) — nie Tabellen droppen
│   └── importer.py                 # IST-Import, detect_oeffnungstage
├── planning/
│   ├── engine.py                   # Kern-Planungslogik (PlanningEngine, PlanParams, DayPlan)
│   └── export.py                   # Excel-Export
└── ui/
    ├── session.py                  # get_conn(), get_gmbh(), get_budgetjahr(), require_db()
    ├── assets/                     # Logos
    └── pages/
        ├── 1_Startseite.py
        ├── 2_Filialen.py           # Stammdaten, inline data_editor
        ├── 3_Daten_Import.py       # IST-Umsatz Upload + Validierung + Sicherheitsabfrage
        ├── 4_Parameter.py
        ├── 5_Neue_Filialen.py
        ├── 6_Planung.py            # Planung ausführen (inkl. ferien_kalender→ferien Sync!)
        ├── 7_Planungsgenauigkeit.py # Plan vs. IST, Abweichung nur bis IST-Importstand
        ├── 8_Feiertage_Import.py   # "Feiertage, Ferien und Sondertage" (Titel!)
        ├── 9_Oeffnungstage.py
        ├── 10_Herleitung.py        # Wasserfall-Analyse der Effekte
        ├── 11_Preisanpassung.py    # Wachstum % je Monat → parameter_monat
        └── 12_Schulfilialen.py     # nur ERKANNTE Filialen werden angezeigt
```

---

## 3. Datenfluss (Ende-zu-Ende)

```
1. Filialen anlegen (2_Filialen)          → filialen
2. IST-Umsätze importieren (3_Daten)      → ist_umsatz (UPSERT!) + Auto-Öffnungstage
3. Feiertage/Ferien laden (8_Feiertage)   → feiertage (art: feiertag|feiertagstag|Sondertag)
                                          → ferien_kalender (Schulferien je BL/Jahr)
4. Öffnungstage prüfen (9_Oeffnungstage)  → filial_oeffnung, filial_feiertag
5. Schulfilialen erkennen (12_Schulfil.)  → filial_schulferien
6. Wachstum je Monat (11_Preisanpassung)  → parameter_monat
7. Planung ausführen (6_Planung)          → SYNC ferien_kalender→ferien, dann Engine → planung
8. Validierung: 10_Herleitung (Effekt-Wasserfall), 7_Planungsgenauigkeit (Plan vs. IST)
```

**Wichtig:** Ein IST-Import löst KEINE Neuberechnung der Planung aus und muss es
auch nicht — die Planungsgenauigkeit liest IST live aus `ist_umsatz` und vergleicht
beim Seitenaufruf. Nur eine geänderte Basis (neue Historie) erfordert bewusst eine
neue Planung.

---

## 4. Datenbankschema (Kerntabellen)

```sql
filialen        (fil_nr PK, bezeichnung, bundesland, ort, eroeffnung,
                 flag_kein_wachstum, flag_inaktiv, eroeffnung_ende, ...)
ist_umsatz      (fil_nr, datum ISO, umsatz)         PK(fil_nr, datum) — UPSERT beim Import
feiertage       (id, datum_plan, datum_vj, name, bundesland, art)
                 -- art: 'feiertag' | 'feiertagstag' | 'Sondertag'
                 -- bundesland: Abkürzung 'BW','BY',… oder 'alle'
sondertage      (datum_plan, datum_referenz, bezeichnung, methode, bundesland)  -- LEGACY
ferien_kalender (bundesland, art, jahr, start, ende)  -- UI-Eingabe/Anzeige
ferien          (bundesland, art, start_vj, ende_vj, start_plan, ende_plan)
                 -- ENGINE-Quelle! Wird in 6_Planung aus ferien_kalender synchronisiert
filial_oeffnung (fil_nr, wochentag 0-6, offen)
filial_feiertag (fil_nr, feiertag_name, offen)       -- Default geschlossen
filial_schulferien (fil_nr, ferien_art, bundesland, geschlossen)
parameter_monat (planjahr, monat, wachstum_pct)
planwert_override (fil_nr, planjahr, monat, planwert)
neue_filialen_plan (fil_nr, planjahr, monat, planwert, eroeffnung_datum)
planung         (fil_nr, datum, wochentag, bundesland, ist_vj,
                 eff_oeffnung, eff_verteilung, eff_wochentag, eff_preis,
                 eff_ferien, eff_feiertag, eff_norm, budget,
                 monat_basis, monat_hoch, monat_plan,
                 tagestyp, feiertag_name, ferien_art, normalisierung, ...)
```

---

## 5. Planungslogik (engine.py)

### 5.1 Basiszeitraum (Rolling 12 Monate)
- Stichtag (6_Planung): `date(today.year,1,1)` wenn planjahr ≤ aktuelles Jahr, sonst heute
- Basiszeitraum = letzte 12 abgeschlossene Kalendermonate vor Stichtag
- `base_year_for_month(m)` ordnet jeden Kalendermonat einem Jahr im Fenster zu

### 5.2 Additive Effektzerlegung (exakte Identität — NIE brechen!)
```
budget = ist_vj + eff_oeffnung + eff_verteilung + eff_wochentag
       + eff_preis + eff_ferien + eff_feiertag + eff_norm
```
Jeder Effekt ist additiv in € und summiert sich exakt über alle Ebenen
(Tag/Woche/Monat/Jahr × Filiale/BL/Gesamt). Änderungen an dieser Identität nur
mit Regressionstest (Summe der Effekte == budget je Tag, 0 Toleranzverletzungen).

### 5.3 Rechenschritte je Monat/Filiale (Reihenfolge)
1. `monat_basis` = IST-Monatsumsatz im Basisfenster (Fallback: Wochentags-Ø-Extrapolation)
2. `monat_hoch` = Hochrechnung auf Planjahr-Wochentagsmix
3. `monat_plan` = monat_hoch × (1 + wachstum_pct/100) aus parameter_monat
4. Tagesverteilung über Wochentags-Anteile (`_weekday_pct`), share je offenem Wochentag
5. Feiertag: raw = IST am Basis-Referenzdatum × growth; Sondertag: Referenztag oder Samstags-Ø
6. Ferien: raw = tag_plan × Ferienfaktor (Ø Ferienwoche / Ø Pufferwoche, wochentagsgematcht)
7. Normierung aller offenen Tage auf monat_plan (`eff_norm` = Rundungs-/Rebalancingrest)

### 5.4 Öffnungslogik
- `_is_open_weekday`: Default offen, wenn kein Eintrag
- `_is_open_feiertag`: Default GESCHLOSSEN, wenn kein Eintrag
- Geschlossener Tag: budget=0, `eff_oeffnung = -ist_vj`, `feiertag_name` bleibt gesetzt
  (für Tagesinfo "Geschlossen (Heilige Drei Könige)" in der Herleitung)

### 5.5 Bundesland-Normalisierung
Es kursieren DREI Formate: `"BW"`, `"Baden-Württemberg"`, `"DE-BW"`.
`engine._normalize_bl()` normalisiert auf 2-Buchstaben-Abkürzung. Die
`feiertage`-Tabelle speichert Abkürzungen (oder `'alle'`). Beim Anfassen von
Bundesland-Vergleichen IMMER normalisieren.

### 5.6 Sondertage — Doppelstruktur (Achtung!)
Die UI (8_Feiertage) speichert Sondertage in `feiertage` mit `art='Sondertag'`.
Die Engine lädt Sondertage aus BEIDEN Quellen: Legacy-Tabelle `sondertage` UND
`feiertage WHERE LOWER(art)='sondertag'` (gemerged in `_load_reference_data`,
feiertage-Einträge mit methode='referenz'). Langfristig: Legacy-Tabelle abschaffen.

### 5.7 Ferien — Doppelstruktur (Achtung!)
`ferien_kalender` (UI) ≠ `ferien` (Engine). `6_Planung._sync_ferien_kalender_to_ferien()`
synchronisiert vor jedem Lauf: Planjahr-Perioden + zugehörige Vorjahres-Perioden
(gematcht über bundesland+art). **Ohne Vorjahres-Eintrag in ferien_kalender wird die
Periode übersprungen** → Ferien immer für Planjahr UND Vorjahr laden!

---

## 6. Planungsgenauigkeit (7_Planungsgenauigkeit.py)

- Liest `planung` (Budgetjahr) + `ist_umsatz` live beim Seitenaufruf — kein Re-Plan nötig.
- **Abweichung € / % vergleicht IST nur mit dem Budget der Tage, an denen IST bereits
  importiert ist** (`_budget_ist = Budget.where(IST aktuell notna)`). Angebrochene
  Wochen/Monate werden anteilig gerechnet; Caption zeigt "IST importiert bis TT.MM.JJJJ".
- Die Spalte "Budget" zeigt weiterhin das volle Periodenbudget.

---

## 7. Import (3_Daten_Import.py / importer.py)

- Spalten-Fuzzy-Matching (`_detect_columns`): Datum, Filialnummer, Umsatz
- **Deutsches Zahlenformat:** `_parse_num` unterscheidet "3.000"=3000 (Tausenderpunkt),
  "3,5"=3.5, "1.234,56"=1234.56. NIE einfaches `replace(",", ".")` verwenden!
- Validierung: unbekannte fil_nr → kompletter Abbruch (keine Teilimporte)
- **Sicherheitsabfrage:** Wenn bereits Daten in `ist_umsatz` → Bestätigungsdialog
- Technisch ist der Import ein UPSERT (`INSERT OR REPLACE` je fil_nr+datum) —
  es wird nichts gelöscht, was nicht in der Datei steht.
- Nach Import: `detect_oeffnungstage(force=False)` (nur Filialen ohne Einträge)

---

## 8. Feiertage/Ferien-Seite (8_Feiertage_Import.py)

- Titel: "Feiertage, Ferien und Sondertage"
- Lädt via `holidays`-Lib alle 16 BL für das Budgetjahr; bundesweit = in allen 16 BL
- Feiertagstage: Tag vor+nach Feiertag (So→keine; Mo→ -2,-1,+1) — art='feiertagstag',
  werden von der Engine als NORMALE Tage behandelt (kein eigener Effekt, bewusst)
- Sondertage: Muttertag (2. So im Mai), Fasching (6 Tage ab Ostern−52), Ramadan (Dict 2023–2036)
- Anzeige: NUR Budgetjahr (kein Jahresfilter), Datum im Format DD.MM.YYYY,
  Spalte "Beschreibung" (nicht "Name"), Art großgeschrieben, BL ausgeschrieben
- Auto-Save mit normalisiertem Datums-Vergleich (`_norm_cmp`) — sonst Toast-Flackern
  durch Timestamp-vs-date-Stringdifferenzen
- Schulferien: holidays-Lib unterstützt SCHOOL für DE NICHT zuverlässig → ggf. manuell

---

## 9. Systemanalyse — Inkonsistenzen & Optimierungsempfehlungen (Stand 06/2026)

Aus Sicht Senior Controlling / Beratung. Priorisiert:

### 9.1 Behoben
- ✅ Deutsche Zahlformate beim Import (3.000 ≠ 3,0)
- ✅ Sicherheitsabfrage vor Neuimport
- ✅ BL-Normalisierung in der Engine (Heilige Drei Könige etc. greifen jetzt)
- ✅ ferien_kalender→ferien Sync vor Planung
- ✅ Sondertage aus feiertage-Tabelle werden von der Engine gelesen
- ✅ Planungsgenauigkeit: Abweichung nur bis IST-Importstand
- ✅ feiertag_name bei geschlossenen Feiertagen in der Herleitung sichtbar

### 9.2 Offen — hohe Priorität
| # | Thema | Risiko/Nutzen |
|---|-------|---------------|
| 1 | **Regressionstest-Suite** (pytest): additive Identität je Tag, Monatsnormierung (Σ Tage == monat_plan), BL-Normalisierung, Importer-Zahlparser. Aktuell gibt es KEINE Tests. | Höchstes Risiko: stille Rechenfehler im Budget |
| 2 | **Datenmodell konsolidieren**: `sondertage`-Legacy-Tabelle und `ferien`/`ferien_kalender`-Dualität abbauen (eine Quelle der Wahrheit, Engine liest direkt). Sync-Schritte sind Fehlerquellen. | Mittelfristig Pflicht |
| 3 | **BL-Normalisierung an der Quelle**: beim Anlegen/Editieren von Filialen normalisieren statt (nur) in der Engine. | Konsistenz |
| 4 | **Engine-Performance**: `_ist_on()` filtert pro Tag das gesamte IST-DataFrame (O(Tage×Zeilen)). Bei 255 Filialen × 365 Tagen langsam. Lösung: Lookup-Dict `{(fil_nr, iso): umsatz}` einmalig bauen. | Laufzeit |
| 5 | **Validierungs-/Plausibilitätsseite**: automatische Checks vor Planung (Filialen ohne BL, Ferien ohne VJ-Periode, Feiertage ohne datum_vj, Monate ohne Basisumsatz, IST-Lücken im Basisfenster) mit Ampel-Anzeige. | Fehlerprävention |

### 9.3 Offen — mittlere Priorität
| # | Thema |
|---|-------|
| 6 | Effekt-Berechnung modularisieren: jeder Effekt (Öffnung, Verteilung, Wochentag, Preis, Ferien, Feiertag) als eigene, unabhängig testbare Funktion/Modul mit einheitlicher Signatur, damit neue Rechenschritte die bestehenden nicht verändern (Pipeline-Muster). `plan_branch()` ist aktuell ein Monolith. |
| 7 | Feiertagsreferenz-Algorithmus: Vergleich mit umliegenden Sonntagen (nicht gleiche Woche, nicht in Ferien, mit Umsatz) statt einfachem datum_vj |
| 8 | Ramadan-/Fasching-Effekt: Parameter vorhanden, Berechnung fehlt |
| 9 | Tooltip Herleitung: verwendete Vergleichstage bei Feiertagseffekten anzeigen |
| 10 | `ensure_filialen_from_ist` nutzt Default "DE-RP" (Alt-Format) — auf "RP" umstellen |
| 11 | Schulferien Auto-Load (holidays-Lib kann SCHOOL für DE nicht) — externe Quelle/API prüfen |

### 9.4 Architektur-Leitplanken (bei jeder Änderung beachten)
1. Additive Identität ist heilig — jeder neue Effekt muss additiv in € sein und
   in die Normierung integriert werden.
2. Neue Rechenschritte als NEUE eff_*-Spalte + eigenes Modul, bestehende Effekte
   nicht umdefinieren (sonst sind historische Planungen nicht mehr vergleichbar).
3. SQLite-Migrationen nur additiv in `schema.py::_migrate()` (nie droppen).
4. Jede Zahl im UI muss bis zum Tagesbeleg nachvollziehbar sein (Herleitung).
5. Defaults: Wochentag offen, Feiertag geschlossen.

---

## 10. Entwicklungsregeln für Claude Code

1. Diese Datei zuerst lesen, bei JEDER Änderung mitpflegen (Abschnitte 5–9 aktuell halten).
2. Branch: `claude/branch-revenue-planning-kuVgL` entwickeln; auf Wunsch des Users auf `master` mergen/pushen.
3. Aussagekräftige englische Commit-Messages.
4. Am Sitzungsende: Git-Hashes zusammenfassen + Download-Link der Branch.
5. Keine halben Implementierungen — zu Großes als TODO in Abschnitt 9 erfassen.
6. Keine Breaking Changes an der additiven Identität ohne Regressionstest.

---

## 11. Änderungshistorie

| Git-Hash | Beschreibung |
|----------|-------------|
| (aktuell) | Planungsgenauigkeit: Abw. nur bis IST-Importstand; Engine liest Sondertage aus feiertage-Tabelle; CLAUDE.md komplett überarbeitet (Systemanalyse, Stolperfallen, Leitplanken) |
| `1bce35d` | BL-Normalisierung in Engine, feiertag_name bei Schließung, ferien_kalender→ferien-Sync, Schulfilialen nur erkannte |
| `49edbb2` | Deutscher Zahlparser im Import, Import-Sicherheitsabfrage, Feiertage-Seite (Titel/Beschreibung/kein Jahresfilter/Flicker-Fix) |
| `5588984` | Navigation-Reorder |
| `4c3623f` | UX-Überarbeitung: Logos, Sidebar, Auto-Speichern, Planung-Bestätigungsdialog |
| `93ce825` | Rolling base period, Öffnungstage, Ferienfaktoren je Woche, Herleitung-Wasserfall |
| `d036d04` | Auto holiday loader (16 BL + Fasching + Muttertag) |
| `594f7cb` | Filialen inline edit, Feiertage multi-Jahr, Schulfilialen-/Preisanpassungs-Seite |
| `e107e37` | CLAUDE.md erstellt |
