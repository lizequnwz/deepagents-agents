from __future__ import annotations

from pathlib import Path


def test_runtime_skill_tree_was_replaced_by_static_contracts() -> None:
    root = Path(__file__).resolve().parents[1]
    assert not (root / "skills/advisor-match/SKILL.md").exists()
    assert (root / "docs/contracts/matching-policy.yaml").is_file()
    assert (root / "docs/contracts/workbook-contract.md").is_file()
    assert (root / "scripts/advisor_match/verify_workbook.py").is_file()
