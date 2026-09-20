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


def test_start_script_watches_only_application_python() -> None:
    script = START_SCRIPT.read_text(encoding="utf-8")

    assert 'API_AUTO_RELOAD="${API_AUTO_RELOAD:-false}"' in script
    assert '--reload-dir "${PROJECT_ROOT}/data_analytics_agent"' in script
    assert '--reload-dir "${PROJECT_ROOT}"' not in script
    assert "--reload-include" not in script
    assert "--reload-exclude" not in script
    assert "--server.runOnSave=false" in script


def test_launcher_passes_server_arguments_with_default_bash(tmp_path):
    """Exercise macOS Bash 3's nounset behavior, not just shell syntax."""
    import json
    import os
    import sys

    commands = tmp_path / "commands"
    commands.mkdir()
    capture = tmp_path / "server-args.json"
    uv = commands / "uv"
    uv.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "if args[:2] == ['run', 'uvicorn']:\n"
        "    Path(os.environ['TEST_SERVER_ARGS']).write_text(json.dumps(args))\n"
        "    sys.exit(1)\n"
        "if args[:2] == ['run', 'python'] and 'import socket' in args[-1]:\n"
        "    sys.exit(1)\n"
    )
    uv.chmod(0o755)
    curl = commands / "curl"
    curl.write_text("#!/bin/sh\nexit 1\n")
    curl.chmod(0o755)
    for reload in ["false", "true"]:
        result = subprocess.run(
            ["/bin/bash", str(START_SCRIPT)],
            env={
                **os.environ,
                "PATH": f"{commands}:{os.environ['PATH']}",
                "TEST_SERVER_ARGS": str(capture),
                "API_AUTO_RELOAD": reload,
            },
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 1  # The fake server exits deliberately.
        assert "unbound variable" not in result.stderr
        args = json.loads(capture.read_text())
        assert "--host" in args and "--port" in args and "--no-access-log" in args
        assert ("--reload" in args) == (reload == "true")
        capture.unlink()
