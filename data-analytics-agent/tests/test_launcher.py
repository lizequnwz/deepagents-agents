from __future__ import annotations

import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
START_SCRIPT = PROJECT_ROOT / "scripts/start.sh"


def test_start_script_is_valid_bash() -> None:
    subprocess.run(
        ["bash", "-n", str(START_SCRIPT)],
        check=True,
        capture_output=True,
        text=True,
    )


def test_start_script_enables_configurable_development_reload() -> None:
    script = START_SCRIPT.read_text(encoding="utf-8")

    assert 'API_AUTO_RELOAD="${API_AUTO_RELOAD:-true}"' in script
    assert "--reload-include '*.py'" in script
    assert "--reload-include '*.md'" in script
    assert "--reload-include '*.yaml'" in script
    assert "--reload-include '.env'" in script
    assert "--server.runOnSave=true" in script
