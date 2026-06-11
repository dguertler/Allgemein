"""Generator for the datumsmapping table.

For each day in the plan year × each bundesland from filialen, determines
the correct reference day in the rolling base year using:
  1. Feiertag → Feiertag matching via datum_vj
  2. Ferien week N → same week N in VJ period (weekday-matched)
  3. Normal → same ISO-KW + weekday in base year
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Iterator

import pandas as pd


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
    # If result lands in the wrong ISO year, use week 52 instead
    if result.isocalendar()[0] != year:
        result = week1_monday + timedelta(weeks=51, days=weekday)
    return result


def generate_datumsmapping(conn: sqlite3.Connection, planjahr: int, engine) -> int:
    """Generate and persist datumsmapping for planjahr. Returns row count."""
    py = planjahr

    # Distinct bundesländer actually in use (format from filialen: DE-RP etc.)
    bl_rows = conn.execute(
        "SELECT DISTINCT bundesland FROM filialen WHERE bundesland IS NOT NULL AND bundesland != ''"
    ).fetchall()
    bundeslaender = [r["bundesland"] for r in bl_rows]
    if not bundeslaender:
        bundeslaender = ["DE-RP"]

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
                # 1. Feiertag matching
                ft = engine._relevant_feiertag(iso, bl)
                if ft:
                    base_d = engine._feiertag_base_date(ft, month)
                    if base_d is None:
                        base_d = _safe_date(by, month, day) or plan_d
                    rows.append((
                        iso, base_d.isoformat(),
                        "feiertag", "feiertag", bl, "feiertag"
                    ))
                    continue

                # 2. Ferien matching
                fer = engine._ferien_info_for_day(iso, bl)
                if fer:
                    art, woche = fer
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
                        rows.append((
                            iso, base_d.isoformat(),
                            "ferien", "ferien", bl, "ferien"
                        ))
                        continue

                # 3. Normal: same ISO-KW + weekday in base year
                base_d = _date_from_iso_week(by, iso_week, wt)
                rows.append((
                    iso, base_d.isoformat(),
                    "normal", "normal", bl, "iso_kw"
                ))

    # Repopulate
    conn.execute(
        "DELETE FROM datumsmapping WHERE CAST(strftime('%Y', plan_datum) AS INTEGER) = ?",
        (py,)
    )
    conn.executemany(
        """INSERT OR REPLACE INTO datumsmapping
           (plan_datum, base_datum, plan_typ, base_typ, bundesland, mapping_art)
           VALUES (?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    return len(rows)
