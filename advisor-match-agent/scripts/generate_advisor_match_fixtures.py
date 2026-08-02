"""Generate deterministic user-facing Advisor Match example uploads."""

from __future__ import annotations

import csv
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "examples" / "advisor-match"

FIXTURES = {
    "clean_exact_matches.csv": [
        ["CRD_NUMBER", "FIRST_NAME", "LAST_NAME", "EMAIL"],
        ["99000001", "Avery", "Stone", "avery.stone@example.com"],
        ["99000005", "Elizabeth", "Hart", "elizabeth.hart@example.com"],
        ["99000009", "Maya", "Chen", "maya.chen@example.com"],
    ],
    "address_variations.csv": [
        ["First Name", "Last Name", "Firm Name", "Street Address", "City", "State", "ZIP"],
        ["John", "Smith", "Northstar Wealth Partners LLC", "100 Beacon St Ste 400", "Boston", "Massachusetts", "02108-1200"],
        ["Michael", "Chen", "Evergreen Capital Counsel", "901 Pine Street", "Seattle", "WA", "98101"],
    ],
    "partial_matches.csv": [
        ["Advisor Name", "Company", "City", "State"],
        ["Jon Smith", "Northstar Wealth", "Boston", "MA"],
        ["Bob Mercer", "Cedar Grove Advisory", "Richmond", "VA"],
        ["Liz Hart", "Blue Oak Financial", "Philadelphia", "PA"],
    ],
    "unknown_advisors.csv": [
        ["First Name", "Last Name", "Firm Name", "City", "State"],
        ["Quinn", "Example", "Imaginary Finance", "Albany", "NY"],
        ["Riley", "Sample", "Neverland Advisors", "Austin", "TX"],
    ],
}

XLSX_FIXTURES = {
    "casing_and_whitespace.xlsx": [
        ["first name", "last name", "email address", "firm"],
        ["  AVERY ", " stone ", " AVERY.STONE@EXAMPLE.COM ", " northstar wealth partners "],
        [" maya", "CHEN ", "MAYA.CHEN@EXAMPLE.COM", " evergreen capital counsel"],
    ],
    "missing_fields.xlsx": [
        ["First Name", "Last Name", "Email", "Firm Name", "City", "State"],
        ["John", "Smith", "", "Northstar Wealth Partners", "Boston", "MA"],
        ["", "", "amelia.patel@example.com", "", "", ""],
        ["", "", "", "Atlas Financial Planning", "Boston", "MA"],
    ],
    "duplicate_rows.xlsx": [
        ["CRD", "First Name", "Last Name", "Email"],
        ["99000012", "Sofia", "Garcia", "sofia.garcia@example.com"],
        ["99000012", "Sofia", "Garcia", "sofia.garcia@example.com"],
        ["99000013", "William", "Brooks", "william.brooks@example.com"],
    ],
    "unfamiliar_columns.xlsx": [
        ["Rep Identifier", "Given", "Family", "Organization", "Electronic Mail", "Town", "Province"],
        ["99000018", "Amelia", "Patel", "Orchard Lane Advisors", "amelia.patel@example.com", "Edison", "NJ"],
        ["99000024", "Isabella", "Moore", "Queen City Planning", "isabella.moore@example.com", "Charlotte", "NC"],
    ],
}


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, rows in FIXTURES.items():
        with (OUTPUT / name).open("w", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerows(rows)
    for name, rows in XLSX_FIXTURES.items():
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Advisors"
        for row in rows:
            sheet.append(row)
        workbook.save(OUTPUT / name)


if __name__ == "__main__":
    main()
