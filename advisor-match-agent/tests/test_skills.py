from __future__ import annotations

import re
from pathlib import Path

import yaml

EXPECTED_SKILLS = {"advisor-match"}


def test_main_skill_tree_uses_canonical_packages() -> None:
    skills = Path(__file__).resolve().parents[1] / "skills"
    actual = {path.name for path in skills.iterdir() if (path / "SKILL.md").is_file()}
    assert actual == EXPECTED_SKILLS

    for name in sorted(actual):
        content = (skills / name / "SKILL.md").read_text(encoding="utf-8")
        match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        assert match, f"{name} has invalid frontmatter delimiters"
        frontmatter = yaml.safe_load(match.group(1))
        assert frontmatter["name"] == name
        assert isinstance(frontmatter["description"], str)
        assert frontmatter["description"].strip()


def test_skill_markdown_has_no_broken_relative_links() -> None:
    skills = Path(__file__).resolve().parents[1] / "skills"
    link_pattern = re.compile(r"\[[^]]*]\(([^)]+)\)")
    for skill_md in skills.glob("*/SKILL.md"):
        for target in link_pattern.findall(skill_md.read_text(encoding="utf-8")):
            if target.startswith(("#", "http://", "https://")):
                continue
            relative = target.split("#", 1)[0]
            assert (skill_md.parent / relative).exists(), (
                f"{skill_md.relative_to(skills)} links to missing {target}"
            )


def test_prepare_directories_removes_retired_installed_skills(settings) -> None:
    source = settings.skills_source_root
    (source / "advisor-match").mkdir(parents=True)
    (source / "advisor-match/SKILL.md").write_text(
        "---\nname: advisor-match\ndescription: test\n---\n", encoding="utf-8"
    )
    stale = settings.installed_skills_root / "spreadsheets"
    stale.mkdir(parents=True)
    (stale / "SKILL.md").write_text(
        "---\nname: spreadsheets\ndescription: stale\n---\n", encoding="utf-8"
    )

    settings.prepare_directories()

    assert (settings.installed_skills_root / "advisor-match/SKILL.md").is_file()
    assert {
        path.name for path in settings.installed_skills_root.iterdir()
    } == {"advisor-match"}
    assert not stale.exists()
