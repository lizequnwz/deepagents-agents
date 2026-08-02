"""Print deterministic mapping suggestions from the bounded profiler."""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from general_agent.advisor_matching.profiler import profile_advisor_file
from general_agent.config import Settings

if __name__ == "__main__":
    profile = profile_advisor_file(Path(sys.argv[1]), Settings(project_root=Path.cwd(), model_name="developer"))
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
