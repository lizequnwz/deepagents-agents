from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from advisor_match.ui.api_client import AdvisorMatchAPIClient


def test_match_result_handoff_switches_tab_and_analyzes_profiles(monkeypatch) -> None:
    match_analysis = {
        "source": {"filename": "advisors.csv", "format": "csv", "sha256": "a" * 64},
        "profile": _profile(None, ["CRD", "Name", "Email"]),
        "decision": {
            "mapping": {
                "sheet_name": None,
                "header_row": 1,
                "crd_number": {"index": 0, "header": "CRD"},
                "full_name": {"index": 1, "header": "Name"},
                "email": {"index": 2, "header": "Email"},
            },
            "clarification_required": False,
            "clarification_kind": None,
            "clarification_question": None,
        },
        "validation": {"warnings": []},
        "validation_error": None,
    }
    profile_analysis = {
        "source": {
            "filename": "advisor_matches.xlsx",
            "format": "xlsx",
            "sha256": "b" * 64,
        },
        "profile": _profile("Matched", ["Advisor CRD"]),
        "decision": {
            "mapping": {
                "sheet_name": "Matched",
                "header_row": 1,
                "crd_number": {"index": 0, "header": "Advisor CRD"},
            },
            "clarification_required": False,
            "missing_crd_column": False,
            "clarification_kind": None,
            "clarification_question": None,
        },
        "validation": {"unique_crd_count": 1},
        "validation_error": None,
    }
    workbook = b"generated-workbook"

    monkeypatch.setattr(
        AdvisorMatchAPIClient,
        "health",
        lambda _self: {"status": "ok", "version": "test"},
    )
    monkeypatch.setattr(
        AdvisorMatchAPIClient,
        "map_advisors",
        lambda *_args, **_kwargs: match_analysis,
    )
    monkeypatch.setattr(
        AdvisorMatchAPIClient,
        "match_advisors",
        lambda *_args, **_kwargs: (
            {
                "counts": {
                    "matched": 1,
                    "ambiguous_match": 0,
                    "no_match": 0,
                },
                "warnings": [],
            },
            workbook,
        ),
    )
    monkeypatch.setattr(
        AdvisorMatchAPIClient,
        "map_profile",
        lambda *_args, **_kwargs: profile_analysis,
    )

    app = AppTest.from_file(
        str(Path(__file__).resolve().parents[1] / "streamlit_app.py"),
        default_timeout=20,
    ).run()
    app.file_uploader[0].upload(
        "advisors.csv",
        b"CRD,Name,Email\n1001,Avery Stone,avery@example.com\n",
        "text/csv",
    ).run()
    _button(app, "Analyze columns").click().run()
    _button(app, "Start matching").click().run()
    _button(app, "Continue to profile generation").click().run()

    assert not app.exception
    assert app.session_state["workflow_tabs"] == "Profile Generation"
    assert app.session_state["profile_source"]["filename"] == "advisor_matches.xlsx"
    assert app.session_state["profile_source"]["content"] == workbook
    assert app.session_state["profile_analysis"] == profile_analysis
    assert _button(app, "Generate profile report")


def _button(app: AppTest, label: str):
    return next(button for button in app.button if button.label == label)


def _profile(sheet_name: str | None, headers: list[str]) -> dict:
    columns = [
        {
            "index": index,
            "header": header,
            "label": header,
            "non_null_sample": 1,
            "pattern": "text",
        }
        for index, header in enumerate(headers)
    ]
    return {
        "format": "csv" if sheet_name is None else "xlsx",
        "source_sha256": "a" * 64,
        "warnings": [],
        "sheets": [
            {
                "name": sheet_name,
                "preview_rows": [
                    {"row_number": 1, "values": headers},
                    {"row_number": 2, "values": ["1001", "Avery Stone", "a@x.com"][: len(headers)]},
                ],
                "header_candidates": [
                    {
                        "row_number": 1,
                        "columns": columns,
                        "sample_rows": [],
                        "mapping_suggestions": {},
                    }
                ],
                "headerless": {"columns": [], "sample_rows": []},
            }
        ],
    }
