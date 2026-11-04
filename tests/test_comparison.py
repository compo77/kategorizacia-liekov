from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace

import requests
from openpyxl import Workbook
from requests import Response

from app import create_app
from medicine_comparison.config import load_atc_config
from medicine_comparison.service import build_comparison
from medicine_comparison.source import (
    DEFAULT_MINISTRY_LISTINGS_URL,
    SpreadsheetSnapshot,
    _article_candidates,
    _get,
    _monthly_spreadsheet_candidates,
    fetch_latest_spreadsheets,
    ministry_listings_url,
    parse_workbook,
)


def make_workbook() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(["ATC", None, None, None, None, "Názov", "Doplnok"])
    sheet.append(
        [
            "Kód",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            "Konečná c.",
            "ÚZP",
            None,
            "DOP",
        ]
    )
    sheet.append(["B01AB05", None, None, None, None, "Enoxaparín", "parent. 4 000 IU"])
    sheet.append(
        [
            "12345",
            None,
            None,
            None,
            "B",
            "Ledraxen",
            "10 striekačiek",
            None,
            None,
            None,
            24.35,
            24.35,
            "S",
            0,
        ]
    )
    sheet.append(["B01AB06", None, None, None, None, "Nadroparín", "2 850 IU"])
    sheet.append(
        [
            "67890",
            None,
            None,
            None,
            "B",
            "Fraxiparine",
            "10 striekačiek",
            None,
            None,
            None,
            12.5,
            10,
            "S",
            2.5,
        ]
    )
    sheet.append(
        ["B01AC06", None, None, None, None, "Kyselina acetylsalicylová", "75 mg"]
    )
    sheet.append(
        [
            "55555",
            None,
            None,
            None,
            "B",
            "Iný liek",
            "balenie",
            None,
            None,
            None,
            3,
            3,
            "S",
            0,
        ]
    )
    data = BytesIO()
    workbook.save(data)
    return data.getvalue()


def test_parse_workbook_keeps_only_the_requested_atc_group():
    medicines = parse_workbook(make_workbook(), "B01AB05")

    assert len(medicines) == 1
    assert medicines[0]["code"] == "12345"
    assert medicines[0]["price"] == Decimal("24.35")
    assert medicines[0]["copay"] == Decimal("0")


def test_parse_workbook_reads_b01ab06_and_config_groups_are_yaml_backed():
    medicines = parse_workbook(make_workbook(), "B01AB06")
    groups, default = load_atc_config()

    assert default == "B01AB05"
    assert groups["B01AB06"] == "Nadroparín"
    assert [medicine["name"] for medicine in medicines] == ["Fraxiparine"]


def test_atc_config_accepts_a_new_yaml_only_group(tmp_path):
    config_path = tmp_path / "atc_groups.yaml"
    config_path.write_text(
        "default: B01AB99\ngroups:\n  B01AB99:\n    name: Testovacia skupina\n",
        encoding="utf-8",
    )

    groups, default = load_atc_config(config_path)

    assert groups == {"B01AB99": "Testovacia skupina"}
    assert default == "B01AB99"


def test_ministry_listings_url_defaults_and_can_be_overridden(monkeypatch):
    monkeypatch.delenv("MINISTRY_LISTINGS_URL", raising=False)
    assert ministry_listings_url() == DEFAULT_MINISTRY_LISTINGS_URL

    custom_url = "https://example.test/medicine-lists/"
    monkeypatch.setenv("MINISTRY_LISTINGS_URL", custom_url)
    assert ministry_listings_url() == custom_url


def test_ministry_html_without_charset_is_decoded_from_apparent_encoding(monkeypatch):
    response = Response()
    response.status_code = 200
    response.headers["Content-Type"] = "text/html"
    response.url = "https://example.test/lists/"
    response._content = (
        '<a href="/lieky202612/">Zoznam kategorizovaných liekov '
        "1.12.2026 – 31.12.2026</a>"
    ).encode()
    response._content_consumed = True
    monkeypatch.setattr(
        "medicine_comparison.source.requests.get", lambda *a, **k: response
    )

    page = _get(response.url)

    candidates = _article_candidates(page.text, page.url)

    assert len(candidates) == 1
    assert candidates[0][1] == (
        "Zoznam kategorizovaných liekov 1.12.2026 – 31.12.2026"
    )


def test_get_retries_transient_connection_errors(monkeypatch):
    response = Response()
    response.status_code = 200
    response.headers["Content-Type"] = "application/octet-stream"
    response.url = "https://example.test/workbook.xlsx"
    attempts = 0

    def flaky_get(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise requests.ConnectionError("temporary connection reset")
        return response

    monkeypatch.setattr("medicine_comparison.source.requests.get", flaky_get)
    monkeypatch.setattr("medicine_comparison.source.sleep", lambda _: None)

    assert _get(response.url) is response
    assert attempts == 2


def test_monthly_listings_download_latest_and_previous_month(monkeypatch):
    landing_url = "https://example.test/medicine-lists/"
    monkeypatch.setenv("MINISTRY_LISTINGS_URL", landing_url)
    page = """
        <a href="/files/december.xlsx">Zoznam liekov (12/2026)</a>
        <a href="/files/november.xlsx">Zoznam liekov (11/2026)</a>
        <a href="/files/september.xlsx">Zoznam liekov (09/2026)</a>
    """
    candidates = _monthly_spreadsheet_candidates(page, landing_url)
    assert [candidate[1] for candidate in candidates] == [
        "Zoznam liekov (12/2026)",
        "Zoznam liekov (11/2026)",
        "Zoznam liekov (09/2026)",
    ]

    def fake_get(url):
        if url == landing_url:
            return SimpleNamespace(text=page, url=landing_url)
        return SimpleNamespace(content=url.encode())

    monkeypatch.setattr("medicine_comparison.source._get", fake_get)
    monkeypatch.setattr(
        "medicine_comparison.source.parse_workbook",
        lambda content, atc_code: [{"code": content.decode()}],
    )

    snapshots = fetch_latest_spreadsheets()

    assert [snapshot.title for snapshot in snapshots] == [
        "Zoznam liekov (12/2026)",
        "Zoznam liekov (11/2026)",
    ]
    assert [snapshot.medicines[0]["code"] for snapshot in snapshots] == [
        "https://example.test/files/december.xlsx",
        "https://example.test/files/november.xlsx",
    ]


def test_dated_subpages_use_monthly_cloud_download_links(monkeypatch):
    landing_url = "https://www.health.gov.sk/lists/"
    december_url = f"{landing_url}lieky202612/"
    november_url = f"{landing_url}lieky202611/"
    landing_html = f"""
        <a href="{december_url}">Zoznam kategorizovaných liekov
        1.12.2026 – 31.12.2026</a>
        <a href="{november_url}">Zoznam kategorizovaných liekov
        1.11.2026 – 30.11.2026</a>
    """
    december_html = """
        <a href="https://cloud.health.gov.sk/s/december/download?v=1">
            Zoznam liekov (12/2026)
        </a>
        <a href="https://cloud.health.gov.sk/s/december-abc/download?v=1">
            Abecedný zoznam liekov (12/2026)
        </a>
        cast_A_zoznam_liekov_N_k_01_12_2026.xlsx
    """
    november_html = """
        <a href="https://cloud.health.gov.sk/s/november/download?v=1">
            Zoznam liekov (11/2026)
        </a>
        cast_A_zoznam_liekov_N_k_01_11_2026.xlsx
    """
    pages = {
        landing_url: SimpleNamespace(text=landing_html, url=landing_url),
        december_url: SimpleNamespace(text=december_html, url=december_url),
        november_url: SimpleNamespace(text=november_html, url=november_url),
        "https://cloud.health.gov.sk/s/december/download?v=1": SimpleNamespace(
            content=b"december"
        ),
        "https://cloud.health.gov.sk/s/november/download?v=1": SimpleNamespace(
            content=b"november"
        ),
    }

    monkeypatch.setenv("MINISTRY_LISTINGS_URL", landing_url)
    monkeypatch.setattr(
        "medicine_comparison.source._get",
        lambda url: pages[url],
    )
    monkeypatch.setattr(
        "medicine_comparison.source.parse_workbook",
        lambda content, atc_code: [{"code": content.decode()}],
    )

    snapshots = fetch_latest_spreadsheets()

    assert [snapshot.title for snapshot in snapshots] == [
        "Zoznam kategorizovaných liekov 1.12.2026 – 31.12.2026",
        "Zoznam kategorizovaných liekov 1.11.2026 – 30.11.2026",
    ]
    assert [snapshot.url for snapshot in snapshots] == [
        "https://cloud.health.gov.sk/s/december/download?v=1",
        "https://cloud.health.gov.sk/s/november/download?v=1",
    ]
    assert [snapshot.medicines[0]["code"] for snapshot in snapshots] == [
        "december",
        "november",
    ]


def test_build_comparison_calculates_copay_change_and_new_products():
    current = [
        {
            "code": "1",
            "name": "Ledraxen",
            "package": "10 ks",
            "price": 25,
            "reimbursement": 20,
            "copay": 5,
        }
    ]
    previous = [
        {
            "code": "1",
            "name": "Ledraxen",
            "package": "10 ks",
            "price": 24,
            "reimbursement": 20,
            "copay": 4,
        },
        {
            "code": "2",
            "name": "Inhixa",
            "package": "10 ks",
            "price": 15,
            "reimbursement": 14,
            "copay": 1,
        },
    ]
    snapshots = [
        SpreadsheetSnapshot("november", "https://example.test/new.xlsx", current),
        SpreadsheetSnapshot("october", "https://example.test/old.xlsx", previous),
    ]

    comparison = build_comparison(snapshots)

    ledraxen = next(row for row in comparison["rows"] if row["current"])
    inhixa = next(row for row in comparison["rows"] if row["status"] == "removed")
    assert ledraxen["copay_change"] == 1
    assert ledraxen["price_change"] == 1
    assert inhixa["previous"]["name"] == "Inhixa"


def test_home_page_renders_comparison_values(monkeypatch):
    medicine = {
        "code": "12345",
        "name": "Ledraxen",
        "package": "10 striekačiek",
        "price": Decimal("24.35"),
        "reimbursement": Decimal("24.35"),
        "copay": Decimal("0"),
    }
    snapshots = [
        SpreadsheetSnapshot("november", "https://example.test/new.xlsx", [medicine]),
        SpreadsheetSnapshot("october", "https://example.test/old.xlsx", [medicine]),
    ]
    source_url = "https://example.test/medicine-lists/"
    monkeypatch.setenv("MINISTRY_LISTINGS_URL", source_url)
    app = create_app()
    app.extensions["comparison_service"] = SimpleNamespace(
        get_comparison=lambda atc_code, previous_period: build_comparison(snapshots)
    )

    response = app.test_client().get("/?previous=202608")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'lang="en"' in html
    assert "Package comparison" in html
    assert "Medicine and package" in html
    assert "Ledraxen" in html
    assert "10 striekačiek" in html
    assert "€24.35" in html
    assert "24,35 €" not in html
    assert 'value="202608"' in html
    assert f'href="{source_url}"' in html


def test_invalid_period_error_is_english():
    response = create_app().test_client().get("/?previous=202613")

    assert response.status_code == 400
    assert response.get_data(as_text=True) == "Period must use the YYYYMM format."


def test_cloud_run_status_endpoint():
    response = create_app().test_client().get("/status")

    assert response.status_code == 200
    assert response.json == {"status": "ok"}
