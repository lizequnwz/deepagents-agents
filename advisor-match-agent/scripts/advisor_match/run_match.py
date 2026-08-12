"""Run the production deterministic matcher from developer-supplied files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from advisor_match.advisor_matching.input_loader import load_input
from advisor_match.advisor_matching.matcher import run_matching
from advisor_match.advisor_matching.schemas import InputMapping
from advisor_match.advisor_matching.source import SyntheticAdvisorReferenceSource
from advisor_match.files import InMemoryFile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("master", type=Path)
    parser.add_argument("mapping", type=Path, help="JSON file containing an InputMapping")
    parser.add_argument("--max-rows", type=int, default=50_000)
    arguments = parser.parse_args()
    mapping = InputMapping.model_validate_json(arguments.mapping.read_text(encoding="utf-8"))
    source = InMemoryFile(arguments.input.name, arguments.input.read_bytes())
    rows = load_input(source, mapping, max_rows=arguments.max_rows)
    advisors = list(SyntheticAdvisorReferenceSource(arguments.master).iter_records())
    decisions, counts, warnings = run_matching(rows, advisors)
    print(json.dumps({
        "counts": counts.model_dump(mode="json"),
        "warnings": warnings,
        "decisions": [decision.model_dump(mode="json") for decision in decisions],
    }, indent=2))


if __name__ == "__main__":
    main()
