"""Verify an Advisor Match workbook using the production contract."""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from advisor_match.advisor_matching.workbook import verify_match_workbook

if __name__ == "__main__":
    print(
        json.dumps(
            verify_match_workbook(Path(sys.argv[1]).read_bytes()),
            sort_keys=True,
        )
    )
