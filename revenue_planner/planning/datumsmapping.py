"""Generator for the datumsmapping table.

For each day in the plan year × each bundesland from filialen, determines
the correct reference day in the rolling base year using:
  1. Feiertag (art='feiertag') → same-named holiday in base year via datum_vj
  2. Feiertagstag (art='feiertagstag') → ISO-KW mapping (treated as normal by engine)
  3. Sondertag → datum_referenz from sondertage table
  4. Ferien week N → same week N in VJ period (weekday-matched)
  5. Normal → same ISO-KW + weekday in base year

Description priority (combined): Feiertag > Feiertagstag > Sondertag > Ferien
Feiertagstage are labelled simply "Feiertagstag" (not the full holiday name).
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Iterator

import pandas as pd

from planning.engine import _normalize_bl


def _date_range(start: date, end: date) -> Iterator[date]:
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _date_from_iso_week(year: int, week: int, weekday: int) -> date:
    """Return date for ISO year/week/weekday. Clamps if week doesn't exist in year."""
    jan4 = date(year, 1, 4)
    week1_monday = jan4 - timedelta(days=jan4.weekday())
    result = week1_monday + timedelta(weeks=week - 1, days=weekday)
    if result.isocalendar()[0] != year:
        result = week1_monday + timedelta(weeks=51, days=weekday)
    return result


def generate_datumsmapping(conn: sqlite3.Connection, planjahr: int, engine) -> int:
    """Generate and persist datumsmapping for planjahr. Returns row count."""
    py = planjahr

    bl_rows = conn.execute(
        "SELECT DISTINCT bundesland FROM filialen WHERE bundesland IS NOT NULL AND bundesland != ''"
    ).fetchall()
    bl_raw = [r["bundesland"] for r in bl_rows]
    bundeslaender = list(dict.fromkeys(_normalize_bl(b) for b in bl_raw)) if bl_raw else ["RP"]

    # Build VJ ferien dates per BL to avoid comparing normal plan days with VJ vacation days
    _vj_ferien_bl: dict[str, set[str]] = {}
    for f in engine.ferien_plan:
        bl_f = f["bundesland"]
        vs = date.fromisoformat(f["start_vj"])
        ve = date.fromisoformat(f["ende_vj"])
        s = _vj_ferien_bl.setdefault(bl_f, set())
        for d in _date_range(vs, ve):
            s.add(d.isoformat())

    rows: list[tuple] = []

    for month in range(1, 13):
        by = engine.base_year_for_month(month)
        dim = pd.Period(f"{py}-{month:02d}").days_in_month

        for day in range(1, dim + 1):
            plan_d = date(py, month, day)
            iso = plan_d.isoformat()
            wt = plan_d.weekday()
            iso_week = plan_d.isocalendar()[1]

            for bl in bundeslaender:
                bezeichnung_parts: list[str] = []
                base_bezeichnung_parts: list[str] = []
                plan_typ = "normal"
                mapping_art = "iso_kw"
                base_d: date | None = None

                # 1. Feiertag (art='feiertag')
                ft = engine._relevant_feiertag(iso, bl)
                if ft:
                    plan_typ = "feiertag"
                    mapping_art = "feiertag"
                    bezeichnung_parts.append(ft["name"])
                    base_bezeichnung_parts.append(ft["name"])
                    base_d = engine._feiertag_base_date(ft, month)
                    if base_d is None:
                        base_d = _safe_date(by, month, day) or plan_d

                # 2. Feiertagstag (art='feiertagstag') — only when no actual Feiertag
                if plan_typ == "normal":
                    ft_tag = None
                    for entry in engine.feiertage.get(iso, []):
                        if entry["bundesland"] in ("alle", bl) and entry.get("art") == "feiertagstag":
                            ft_tag = entry
                            break
                    if ft_tag:
                        plan_typ = "feiertagstag"
                        bezeichnung_parts.append("Feiertagstag")
                        base_bezeichnung_parts.append("Feiertagstag")
                        # Use stored datum_vj (parent holiday VJ + offset) as base date
                        if ft_tag.get("datum_vj"):
                            try:
                                base_d = date.fromisoformat(ft_tag["datum_vj"])
                            except (ValueError, TypeError):
                                pass

                # 3. Sondertag
                st_entry = engine._relevant_sondertag(iso, bl)
                if st_entry:
                    bezeichnung_parts.append(st_entry["bezeichnung"])
                    base_bezeichnung_parts.append(st_entry["bezeichnung"])
                    if plan_typ == "normal":
                        plan_typ = "sondertag"
                        mapping_art = "sondertag"
                        if st_entry.get("datum_referenz"):
                            try:
                                base_d = date.fromisoformat(st_entry["datum_referenz"])
                            except ValueError:
                                pass

                # 4. Ferien — update plan_typ/base_d but NOT bezeichnung (shown in separate columns)
                fer = engine._ferien_info_for_day(iso, bl)
                if fer:
                    art, woche = fer
                    if plan_typ == "normal":
                        plan_typ = "ferien"
                        mapping_art = "ferien"
                        period = next(
                            (f for f in engine.ferien_plan
                             if f["bundesland"] == bl and f["art"] == art),
                            None
                        )
                        if period:
                            vj_start = date.fromisoformat(period["start_vj"])
                            vj_ende = date.fromisoformat(period["ende_vj"])
                            wk_start = vj_start + timedelta(weeks=woche - 1)
                            delta = wt - wk_start.weekday()
                            base_d = wk_start + timedelta(days=delta)
                            base_d = max(vj_start, min(base_d, vj_ende))

                # 5. Fallback: ISO-KW
                if base_d is None:
                    base_d = _date_from_iso_week(by, iso_week, wt)

                # 6. For normal/feiertagstag days: avoid landing on a VJ holiday or vacation
                if plan_typ in ("normal", "feiertagstag") and base_d is not None:
                    base_iso = base_d.isoformat()
                    _is_vj_holiday = any(
                        fe.get("art") == "feiertag" and fe["bundesland"] in ("alle", bl)
                        for fe in engine.feiertage.get(base_iso, [])
                    )
                    _is_vj_ferien = base_iso in _vj_ferien_bl.get(bl, set())
                    if _is_vj_holiday or _is_vj_ferien:
                        for shift in range(1, 9):
                            for direction in (-1, 1):
                                alt = base_d + timedelta(weeks=shift * direction)
                                alt_iso = alt.isoformat()
                                alt_holiday = any(
                                    fe.get("art") == "feiertag" and fe["bundesland"] in ("alle", bl)
                                    for fe in engine.feiertage.get(alt_iso, [])
                                )
                                alt_ferien = alt_iso in _vj_ferien_bl.get(bl, set())
                                if not alt_holiday and not alt_ferien:
                                    base_d = alt
                                    break
                            else:
                                continue
                            break

                bezeichnung = ", ".join(bezeichnung_parts)
                base_bezeichnung = ", ".join(base_bezeichnung_parts)

                rows.append((
                    iso, base_d.isoformat(),
                    plan_typ, plan_typ, bl, mapping_art,
                    bezeichnung, base_bezeichnung,
                ))

    conn.execute(
        "DELETE FROM datumsmapping WHERE CAST(strftime('%Y', plan_datum) AS INTEGER) = ?",
        (py,)
    )
    conn.executemany(
        """INSERT OR REPLACE INTO datumsmapping
           (plan_datum, base_datum, plan_typ, base_typ, bundesland, mapping_art,
            bezeichnung, base_bezeichnung)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    return len(rows)
