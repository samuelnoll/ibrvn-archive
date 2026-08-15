from __future__ import annotations

import html as html_lib
import re
from datetime import datetime


def extract_explicit_dates(value: str) -> list[str]:
    dates = set()
    text_value = html_lib.unescape(value or "")
    day_first_pattern = re.compile(
        r"(?<!\d)(\d{1,2})[./_-](\d{1,2})[./_-]"
        r"(\d{2}|19\d{2}|20\d{2})(?!\d)"
    )
    year_first_pattern = re.compile(
        r"(?<!\d)(19\d{2}|20\d{2})[./_-](\d{1,2})[./_-]"
        r"(\d{1,2})(?!\d)"
    )

    for day, month, year in day_first_pattern.findall(text_value):
        try:
            resolved_year = 2000 + int(year) if len(year) == 2 else int(year)
            dates.add(
                datetime(resolved_year, int(month), int(day)).date().isoformat()
            )
        except ValueError:
            continue

    for year, month, day in year_first_pattern.findall(text_value):
        try:
            dates.add(datetime(int(year), int(month), int(day)).date().isoformat())
        except ValueError:
            continue

    return sorted(dates)


def extract_content_years(value: str) -> list[str]:
    return sorted(set(
        re.findall(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", value or "")
    ))


def extract_text_date(value: str) -> str:
    explicit_dates = extract_explicit_dates(value)

    if explicit_dates:
        return explicit_dates[0]

    years = extract_content_years(value)
    return years[0] if years else ""
