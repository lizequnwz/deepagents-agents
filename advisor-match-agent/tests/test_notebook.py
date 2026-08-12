from __future__ import annotations

import json
from pathlib import Path


def test_interactive_notebook_is_valid_and_covers_full_api_workflow() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "notebooks/advisor_match_stateless_workflow.ipynb"
    )
    notebook = json.loads(path.read_text(encoding="utf-8"))

    assert notebook["nbformat"] == 4
    assert notebook["metadata"]["kernelspec"]["name"] == "python3"
    source = "\n".join(cell["source"] for cell in notebook["cells"])
    for required in (
        "widgets.FileUpload",
        "Analyze columns",
        "Start matching",
        "Use matched workbook for profiles",
        "Analyze CRD column",
        "Generate profile report",
        "display_download",
        "AdvisorMatchAPIClient",
    ):
        assert required in source

    for index, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] == "code":
            compile(cell["source"], f"{path}:cell-{index}", "exec")
