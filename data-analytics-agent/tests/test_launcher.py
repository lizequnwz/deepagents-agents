from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


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


@pytest.mark.parametrize("reload", ["false", "true"])
@pytest.mark.parametrize("react", ["false", "true"])
def test_launcher_passes_server_arguments_with_default_bash(tmp_path, reload, react):
    """Exercise macOS Bash 3's nounset behavior, not just shell syntax."""
    commands = tmp_path / "commands"
    commands.mkdir()
    for command in ("dirname", "sleep"):
        (commands / command).symlink_to(shutil.which(command))
    capture = tmp_path / "server-args.json"
    npm_calls = tmp_path / "npm-calls.txt"
    uv = commands / "uv"
    uv.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "if args == ['run', 'python', '-']:\n"
        "    print(os.environ['TEST_REACT_ENABLED'])\n"
        "if args[:2] == ['run', 'uvicorn']:\n"
        "    launch = {'args': args, 'react': os.getenv('ENABLE_REACT_UI')}\n"
        "    Path(os.environ['TEST_SERVER_ARGS']).write_text(json.dumps(launch))\n"
        "    sys.exit(1)\n"
        "if args[:2] == ['run', 'python'] and 'import socket' in args[-1]:\n"
        "    sys.exit(1)\n"
    )
    uv.chmod(0o755)
    curl = commands / "curl"
    curl.write_text("#!/bin/sh\nexit 1\n")
    curl.chmod(0o755)
    if react == "true":
        npm = commands / "npm"
        npm.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$TEST_NPM_CALLS"\n')
        npm.chmod(0o755)
    env = {
        **os.environ,
        "PATH": str(commands),
        "TEST_SERVER_ARGS": str(capture),
        "TEST_REACT_ENABLED": react,
        "TEST_NPM_CALLS": str(npm_calls),
        "API_AUTO_RELOAD": reload,
    }
    env.pop("ENABLE_REACT_UI", None)
    result = subprocess.run(
        ["/bin/bash", str(START_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1  # The fake server exits deliberately.
    assert "unbound variable" not in result.stderr
    assert capture.exists(), result.stderr
    launch = json.loads(capture.read_text())
    args = launch["args"]
    assert "--host" in args and "--port" in args and "--no-access-log" in args
    assert ("--reload" in args) == (reload == "true")
    assert launch["react"] == react
    if react == "true":
        npm_prefix = f"--prefix {PROJECT_ROOT / 'frontend'} "
        assert npm_calls.read_text().splitlines() == [
            f"{npm_prefix}ci --no-audit --no-fund",
            f"{npm_prefix}run build",
        ]
    else:
        assert not npm_calls.exists()
