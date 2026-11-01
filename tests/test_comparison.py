from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace

from openpyxl import Workbook

from app import create_app
from medicine_comparison.config import load_atc_config
from medicine_comparison.service import build_comparison
from medicine_comparison.source import SpreadsheetSnapshot, parse_workbook


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


def test_home_page_renders_comparison_values():
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
    app = create_app()
    app.extensions["comparison_service"] = SimpleNamespace(
        get_comparison=lambda atc_code, previous_period: build_comparison(snapshots)
    )

    response = app.test_client().get("/?previous=202608")

    assert response.status_code == 200
    assert "Ledraxen" in response.get_data(as_text=True)
    assert "24,35 €" in response.get_data(as_text=True)
    assert 'value="202608"' in response.get_data(as_text=True)


def test_cloud_run_status_endpoint():
    response = create_app().test_client().get("/status")

    assert response.status_code == 200
    assert response.json == {"status": "ok"}
