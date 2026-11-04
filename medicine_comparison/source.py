from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO
from time import sleep
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from openpyxl import load_workbook

from medicine_comparison.config import ATC_GROUPS

DEFAULT_MINISTRY_LISTINGS_URL = (
    "https://www.health.gov.sk/odbornik/kategorizacia-a-cenotvorba/"
    "kategorizacia-liekov/zoznam-kategorizovanych-liekov/"
)
ATC_PATTERN = re.compile(r"[A-Z]\d{2}[A-Z]{2}\d{2}")
ARTICLE_DATE_PATTERN = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
MONTHLY_LISTING_PATTERN = re.compile(
    r"zoznam\s+liekov\s*\(\s*(\d{1,2})\s*/\s*(\d{4})\s*\)", re.IGNORECASE
)
REQUEST_HEADERS = {"User-Agent": "ATC-B01AB05-price-comparison/1.0"}
REQUEST_ATTEMPTS = 3
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
PERIOD_PATTERN = re.compile(r"\d{4}(0[1-9]|1[0-2])")


def ministry_listings_url() -> str:
    return os.environ.get("MINISTRY_LISTINGS_URL", DEFAULT_MINISTRY_LISTINGS_URL)


class SourceError(RuntimeError):
    """Raised when the ministry's current spreadsheets cannot be read."""


@dataclass(frozen=True)
class SpreadsheetSnapshot:
    title: str
    url: str
    medicines: list[dict[str, Any]]


def _get(url: str) -> requests.Response:
    for attempt in range(REQUEST_ATTEMPTS):
        try:
            response = requests.get(url, headers=REQUEST_HEADERS, timeout=25)
            response.raise_for_status()
        except requests.RequestException as error:
            status_code = (
                error.response.status_code
                if isinstance(error, requests.HTTPError) and error.response is not None
                else None
            )
            retryable = (
                not isinstance(error, requests.HTTPError)
                or status_code in RETRYABLE_STATUS_CODES
            )
            if not retryable or attempt == REQUEST_ATTEMPTS - 1:
                raise SourceError(
                    "The medicine list could not be loaded."
                ) from error
            sleep(0.25 * (2**attempt))
            continue

        content_type = response.headers.get("Content-Type", "").casefold()
        if "text/html" in content_type and "charset=" not in content_type:
            response.encoding = response.apparent_encoding
        return response

    raise SourceError("The medicine list could not be loaded.")


def _article_candidates(html: str, base_url: str) -> list[tuple[date, str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: dict[str, tuple[date, str, str]] = {}
    for anchor in soup.select("a[href]"):
        title = " ".join(" ".join(anchor.stripped_strings).split())
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
        if urlparse(url).netloc.casefold() != urlparse(base_url).netloc.casefold():
            continue
        candidates[url] = (article_date, title, url)
    return sorted(candidates.values(), reverse=True)


def _monthly_spreadsheet_candidates(
    html: str, base_url: str
) -> list[tuple[date, str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: dict[str, tuple[date, str, str]] = {}
    for anchor in soup.select("a[href]"):
        title = " ".join(" ".join(anchor.stripped_strings).split())
        match = MONTHLY_LISTING_PATTERN.search(title)
        href = anchor.get("href")
        if not match or not isinstance(href, str):
            continue
        month, year = (int(part) for part in match.groups())
        if not 1 <= month <= 12 or year < 1:
            continue
        url = urljoin(base_url, href)
        if not urlparse(url).path.casefold().endswith(".xlsx"):
            continue
        if urlparse(url).netloc.casefold() != urlparse(base_url).netloc.casefold():
            continue
        candidates[url] = (date(year, month, 1), title, url)
    return sorted(candidates.values(), reverse=True)


def _spreadsheet_link(html: str, base_url: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    monthly_links: list[str] = []
    generic_links: list[str] = []
    for anchor in soup.select("a[href]"):
        href = anchor.get("href")
        if not isinstance(href, str):
            continue
        url = urljoin(base_url, href)
        parsed_url = urlparse(url)
        hostname = (parsed_url.hostname or "").casefold()
        allowed_hosts = {
            (urlparse(base_url).hostname or "").casefold(),
            "cloud.health.gov.sk",
        }
        if hostname not in allowed_hosts:
            continue
        is_cloud_download = (
            hostname == "cloud.health.gov.sk"
            and parsed_url.path.rstrip("/").casefold().endswith("/download")
        )
        if not parsed_url.path.casefold().endswith(".xlsx") and not is_cloud_download:
            continue
        label = " ".join(" ".join(anchor.stripped_strings).split())
        if MONTHLY_LISTING_PATTERN.fullmatch(label):
            monthly_links.append(url)
        elif label.casefold() == "zoznam liekov":
            generic_links.append(url)
    if monthly_links:
        return monthly_links[0]
    return generic_links[0] if generic_links else None


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
        raise ValueError(f"Unsupported ATC group: {atc_code}")
    try:
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
        worksheet = workbook.active
        if worksheet is None:
            raise ValueError("The medicine workbook has no active worksheet.")
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
        raise SourceError("The medicine workbook has an unexpected format.") from error


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


def _load_monthly_snapshot(
    title: str, workbook_url: str, atc_code: str
) -> SpreadsheetSnapshot | None:
    try:
        workbook_response = _get(workbook_url)
        medicines = parse_workbook(workbook_response.content, atc_code)
        return SpreadsheetSnapshot(title, workbook_url, medicines)
    except SourceError:
        return None


def _previous_month(value: date) -> date:
    return (date(value.year, value.month, 1) - timedelta(days=1)).replace(day=1)


def fetch_latest_spreadsheets(
    count: int = 2,
    atc_code: str = "B01AB05",
    previous_period: str | None = None,
) -> list[SpreadsheetSnapshot]:
    if atc_code not in ATC_GROUPS:
        raise ValueError(f"Unsupported ATC group: {atc_code}")
    if previous_period is not None and not PERIOD_PATTERN.fullmatch(previous_period):
        raise ValueError("Period must use the YYYYMM format.")
    landing = _get(ministry_listings_url())
    monthly_candidates = _monthly_spreadsheet_candidates(landing.text, landing.url)

    if monthly_candidates:
        if count == 0 and previous_period is None:
            return []
        latest_date, latest_title, latest_url = monthly_candidates[0]
        selected_candidates = [(latest_date, latest_title, latest_url)]

        if previous_period is not None:
            previous_candidate = next(
                (
                    candidate
                    for candidate in monthly_candidates
                    if candidate[0].strftime("%Y%m") == previous_period
                ),
                None,
            )
            if previous_candidate is None:
                raise SourceError(
                    f"No medicine list was found for period {previous_period}."
                )
            if previous_candidate[0] >= latest_date:
                raise SourceError(
                    "The comparison period must be earlier than the latest list."
                )
            selected_candidates.append(previous_candidate)
        else:
            expected_date = latest_date
            while len(selected_candidates) < count:
                expected_date = _previous_month(expected_date)
                previous_candidate = next(
                    (
                        candidate
                        for candidate in monthly_candidates
                        if candidate[0] == expected_date
                    ),
                    None,
                )
                if previous_candidate is None:
                    raise SourceError(
                        "The Ministry page does not contain lists for "
                        "consecutive months."
                    )
                selected_candidates.append(previous_candidate)

        snapshots: list[SpreadsheetSnapshot] = []
        for _, title, url in selected_candidates:
            snapshot = _load_monthly_snapshot(title, url, atc_code)
            if snapshot is None:
                raise SourceError("A medicine list could not be loaded.")
            snapshots.append(snapshot)
        return snapshots

    candidates = _article_candidates(landing.text, landing.url)

    if previous_period is not None:
        target_candidates = [
            candidate
            for candidate in candidates
            if candidate[0].strftime("%Y%m") == previous_period
        ]
        if not target_candidates:
            raise SourceError(
                f"No categorized medicine list was found for period {previous_period}."
            )

        latest_snapshot = None
        latest_article_date = None
        for candidate_date, title, article_url in candidates:
            latest_snapshot = _load_snapshot(title, article_url, atc_code)
            if latest_snapshot is not None:
                latest_article_date = candidate_date
                break
        if latest_snapshot is None or latest_article_date is None:
            raise SourceError("The latest medicine list could not be loaded.")

        selected_candidate = next(
            (
                candidate
                for candidate in target_candidates
                if candidate[2] != latest_snapshot.url
            ),
            target_candidates[0],
        )
        if selected_candidate[0] >= latest_article_date:
            raise SourceError(
                "The comparison period must be earlier than the latest list."
            )
        previous_snapshot = _load_snapshot(
            selected_candidate[1], selected_candidate[2], atc_code
        )
        if previous_snapshot is None:
            raise SourceError(
                f"The medicine list for period {previous_period} could not be loaded."
            )
        return [latest_snapshot, previous_snapshot]

    article_snapshots: list[SpreadsheetSnapshot] = []

    for _, title, article_url in candidates:
        if len(article_snapshots) == count:
            break
        snapshot = _load_snapshot(title, article_url, atc_code)
        if snapshot is not None:
            article_snapshots.append(snapshot)

    if len(article_snapshots) < count:
        raise SourceError(
            "The Ministry page did not contain two usable medicine lists."
        )
    return article_snapshots
