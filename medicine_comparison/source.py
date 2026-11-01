from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from openpyxl import load_workbook

from medicine_comparison.config import ATC_GROUPS

LANDING_URL = "https://www.health.gov.sk/?kategorizacia-a-ceny"
ATC_PATTERN = re.compile(r"[A-Z]\d{2}[A-Z]{2}\d{2}")
ARTICLE_DATE_PATTERN = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
WORKBOOK_PATTERN = re.compile(r"/zkl/\d{6}/.+\.xlsx(?:$|\?)", re.IGNORECASE)
REQUEST_HEADERS = {"User-Agent": "ATC-B01AB05-price-comparison/1.0"}
PERIOD_PATTERN = re.compile(r"\d{4}(0[1-9]|1[0-2])")


class SourceError(RuntimeError):
    """Raised when the ministry's current spreadsheets cannot be read."""


@dataclass(frozen=True)
class SpreadsheetSnapshot:
    title: str
    url: str
    medicines: list[dict[str, Any]]


def _get(url: str) -> requests.Response:
    try:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=25)
        response.raise_for_status()
        return response
    except requests.RequestException as error:
        raise SourceError("Zoznam liekov sa momentálne nepodarilo načítať.") from error


def _article_candidates(html: str, base_url: str) -> list[tuple[date, str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: dict[str, tuple[date, str, str]] = {}
    for anchor in soup.select("a[href]"):
        title = " ".join(anchor.stripped_strings)
        if "zoznam kategorizovaných liekov" not in title.casefold():
            continue
        match = ARTICLE_DATE_PATTERN.search(title)
        if not match:
            continue
        day, month, year = (int(part) for part in match.groups())
        article_date = date(year, month, day)
        href = anchor.get("href")
        if not isinstance(href, str):
            continue
        url = urljoin(base_url, href)
        if urlparse(url).netloc.casefold() != urlparse(LANDING_URL).netloc.casefold():
            continue
        candidates[url] = (article_date, title, url)
    return sorted(candidates.values(), reverse=True)


def _spreadsheet_link(html: str, base_url: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.select("a[href]"):
        href = anchor.get("href")
        if not isinstance(href, str):
            continue
        url = urljoin(base_url, href)
        if not WORKBOOK_PATTERN.search(url):
            continue
        if urlparse(url).netloc.casefold() != urlparse(LANDING_URL).netloc.casefold():
            continue
        label = " ".join(anchor.stripped_strings).casefold()
        if "zoznam liekov" in label:
            return url
    return None


def parse_amount(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    text = str(value).replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def parse_workbook(content: bytes, atc_code: str) -> list[dict[str, Any]]:
    if atc_code not in ATC_GROUPS:
        raise ValueError(f"Nepodporovaná ATC skupina: {atc_code}")
    try:
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
        worksheet = workbook.active
        if worksheet is None:
            raise ValueError("Excel zoznam liekov neobsahuje aktívny hárok.")
        medicines: list[dict[str, Any]] = []
        active_atc: str | None = None
        for row in worksheet.iter_rows(min_row=3, values_only=True):
            first_cell = str(row[0]).strip() if row and row[0] is not None else ""
            if ATC_PATTERN.fullmatch(first_cell):
                active_atc = first_cell
                continue
            if active_atc != atc_code or len(row) <= 13 or not row[0] or not row[5]:
                continue
            medicines.append(
                {
                    "code": str(row[0]).strip(),
                    "name": str(row[5]).strip(),
                    "package": str(row[6] or "").strip(),
                    "price": parse_amount(row[10]),
                    "reimbursement": parse_amount(row[11]),
                    "copay": parse_amount(row[13]),
                }
            )
        workbook.close()
        return medicines
    except (OSError, ValueError, IndexError) as error:
        raise SourceError("Excel zoznam liekov má neočakávaný formát.") from error


def _load_snapshot(
    title: str, article_url: str, atc_code: str
) -> SpreadsheetSnapshot | None:
    try:
        article = _get(article_url)
        workbook_url = _spreadsheet_link(article.text, article.url)
        if workbook_url is None:
            return None
        workbook_response = _get(workbook_url)
        medicines = parse_workbook(workbook_response.content, atc_code)
        return SpreadsheetSnapshot(title, workbook_url, medicines)
    except SourceError:
        return None


def fetch_latest_spreadsheets(
    count: int = 2,
    atc_code: str = "B01AB05",
    previous_period: str | None = None,
) -> list[SpreadsheetSnapshot]:
    if atc_code not in ATC_GROUPS:
        raise ValueError(f"Nepodporovaná ATC skupina: {atc_code}")
    if previous_period is not None and not PERIOD_PATTERN.fullmatch(previous_period):
        raise ValueError("Obdobie musí mať formát YYYYMM.")
    landing = _get(LANDING_URL)
    candidates = _article_candidates(landing.text, landing.url)

    if previous_period is not None:
        target_candidates = [
            candidate
            for candidate in candidates
            if candidate[0].strftime("%Y%m") == previous_period
        ]
        if not target_candidates:
            raise SourceError(
                "Zoznam kategorizovaných liekov za obdobie "
                f"{previous_period} sa nenašiel."
            )

        latest_snapshot = None
        latest_date = None
        for candidate_date, title, article_url in candidates:
            latest_snapshot = _load_snapshot(title, article_url, atc_code)
            if latest_snapshot is not None:
                latest_date = candidate_date
                break
        if latest_snapshot is None or latest_date is None:
            raise SourceError("Najnovší zoznam liekov sa nepodarilo načítať.")

        selected_candidate = next(
            (
                candidate
                for candidate in target_candidates
                if candidate[2] != latest_snapshot.url
            ),
            target_candidates[0],
        )
        if selected_candidate[0] >= latest_date:
            raise SourceError(
                "Porovnávacie obdobie musí byť staršie než najnovší zoznam."
            )
        previous_snapshot = _load_snapshot(
            selected_candidate[1], selected_candidate[2], atc_code
        )
        if previous_snapshot is None:
            raise SourceError(
                f"Zoznam liekov za obdobie {previous_period} sa nepodarilo načítať."
            )
        return [latest_snapshot, previous_snapshot]

    snapshots: list[SpreadsheetSnapshot] = []

    for _, title, article_url in candidates:
        if len(snapshots) == count:
            break
        snapshot = _load_snapshot(title, article_url, atc_code)
        if snapshot is not None:
            snapshots.append(snapshot)

    if len(snapshots) < count:
        raise SourceError(
            "Na stránke ministerstva sa nenašli dva použiteľné zoznamy liekov."
        )
    return snapshots
