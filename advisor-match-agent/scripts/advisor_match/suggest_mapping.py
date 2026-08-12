"""Print deterministic mapping suggestions from the bounded profiler."""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from advisor_match.advisor_matching.profiler import inspect_advisor_upload
from advisor_match.config import Settings
from advisor_match.files import InMemoryFile

if __name__ == "__main__":
    source_path = Path(sys.argv[1])
    source = InMemoryFile(source_path.name, source_path.read_bytes())
    profile = inspect_advisor_upload(
        source,
        Settings(project_root=Path.cwd(), model_name="developer"),
    )
    print(json.dumps([
        {
            "sheet": sheet["name"],
            "header_candidates": [
                {
                    "row_number": candidate["row_number"],
                    "mapping_suggestions": candidate["mapping_suggestions"],
                }
                for candidate in sheet["header_candidates"]
            ],
        }
        for sheet in profile["sheets"]
    ], indent=2))
