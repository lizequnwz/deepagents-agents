"""Bounded subprocess runner for validated statistical Python."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import pickle
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory, gettempdir
from threading import Thread
import time
from typing import BinaryIO

import pandas as pd

from data_analytics_agent.agents.statistical_analysis.schemas import (
    PythonExecutionResult,
    StatisticalOutput,
)


@dataclass(frozen=True)
class PythonExecutionLimits:
    timeout_seconds: float = 30
    max_stdout_chars: int = 10_000
    max_output_items: int = 10
    max_output_rows: int = 50
    max_output_columns: int = 20
    max_output_chars: int = 50_000
    max_figures: int = 4
    max_figure_bytes: int = 1_048_576
    max_total_figure_bytes: int = 3_145_728
    max_figure_width: int = 1_600
    max_figure_height: int = 1_200
    max_execution_attempts: int = 2


class StatisticalExecutionError(RuntimeError):
    """Bounded, model-presentable failure from executed Python."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "python_execution_failed",
        traceback: str = "",
        stdout: str = "",
        stderr: str = "",
        repairable: bool = True,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.traceback = traceback
        self.stdout = stdout
        self.stderr = stderr
        self.repairable = repairable


def _sanitized_environment(workdir: Path) -> dict[str, str]:
    """Provide imports and locale without inheriting service credentials."""

    matplotlib_cache = Path(gettempdir()) / "data-analytics-agent-matplotlib"
    matplotlib_cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "HOME": str(workdir),
        "TMPDIR": str(workdir),
        "MPLBACKEND": "Agg",
        "MPLCONFIGDIR": str(matplotlib_cache),
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if os.name == "nt" and os.environ.get("SYSTEMROOT"):
        environment["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    return environment


def _drain_bounded(
    stream: BinaryIO,
    *,
    character_limit: int,
    target: dict[str, object],
) -> None:
    retained = bytearray()
    truncated = False
    byte_limit = max(character_limit * 4, character_limit)
    while True:
        chunk = stream.read(8_192)
        if not chunk:
            break
        remaining = byte_limit - len(retained)
        if remaining > 0:
            retained.extend(chunk[:remaining])
        if len(chunk) > max(remaining, 0):
            truncated = True
    text = retained.decode("utf-8", errors="replace")
    if len(text) > character_limit:
        text = text[:character_limit]
        truncated = True
    target["text"] = text
    target["truncated"] = truncated


def _bounded_process_output(
    process: subprocess.Popen[bytes],
    *,
    timeout_seconds: float,
    character_limit: int,
) -> tuple[str, str, bool, bool, bool]:
    stdout_result: dict[str, object] = {}
    stderr_result: dict[str, object] = {}
    assert process.stdout is not None
    assert process.stderr is not None
    threads = [
        Thread(
            target=_drain_bounded,
            args=(process.stdout,),
            kwargs={
                "character_limit": character_limit,
                "target": stdout_result,
            },
            daemon=True,
        ),
        Thread(
            target=_drain_bounded,
            args=(process.stderr,),
            kwargs={
                "character_limit": character_limit,
                "target": stderr_result,
            },
            daemon=True,
        ),
    ]
    for thread in threads:
        thread.start()
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait()
        timed_out = True
    else:
        timed_out = False
    for thread in threads:
        thread.join(timeout=2)
    return (
        str(stdout_result.get("text", "")),
        str(stderr_result.get("text", "")),
        bool(stdout_result.get("truncated", False)),
        bool(stderr_result.get("truncated", False)),
        timed_out,
    )


def execute_reviewed_python(
    *,
    dataframe: pd.DataFrame,
    code: str,
    parent_result_id: str,
    attempt: int,
    limits: PythonExecutionLimits,
) -> PythonExecutionResult:
    """Execute the exact code with a preloaded DataFrame named ``df``."""

    started = time.perf_counter()
    with TemporaryDirectory(prefix="statistical-analysis-") as raw_workdir:
        workdir = Path(raw_workdir)
        frame_path = workdir / "dataset.pkl"
        code_path = workdir / "reviewed.py"
        config_path = workdir / "limits.json"
        output_path = workdir / "execution.json"
        with frame_path.open("wb") as file:
            pickle.dump(dataframe, file, protocol=pickle.HIGHEST_PROTOCOL)
        code_path.write_text(code, encoding="utf-8", newline="")
        config_path.write_text(
            json.dumps(asdict(limits), sort_keys=True),
            encoding="utf-8",
        )

        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "data_analytics_agent.agents.statistical_analysis.worker",
                str(frame_path),
                str(code_path),
                str(config_path),
                str(output_path),
            ],
            cwd=workdir,
            env=_sanitized_environment(workdir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=(os.name == "posix"),
        )
        stdout, stderr, stdout_truncated, stderr_truncated, timed_out = (
            _bounded_process_output(
                process,
                timeout_seconds=limits.timeout_seconds,
                character_limit=limits.max_stdout_chars,
            )
        )
        elapsed_ms = (time.perf_counter() - started) * 1_000
        if timed_out:
            raise StatisticalExecutionError(
                "Reviewed Python exceeded the "
                f"{limits.timeout_seconds:g}-second timeout.",
                code="python_timeout",
                stdout=stdout,
                stderr=stderr,
            )
        if process.returncode is None:
            raise StatisticalExecutionError(
                "The Python worker did not report an exit status.",
                stdout=stdout,
                stderr=stderr,
            )
        if not output_path.is_file():
            raise StatisticalExecutionError(
                "The Python worker exited without an execution result.",
                stdout=stdout,
                stderr=stderr,
            )
        maximum_encoded_figure_bytes = (
            (limits.max_total_figure_bytes + 2) // 3
        ) * 4
        maximum_result_bytes = (
            maximum_encoded_figure_bytes
            + limits.max_output_chars * 4
            + 100_000
        )
        if output_path.stat().st_size > maximum_result_bytes:
            raise StatisticalExecutionError(
                "The structured Python output exceeded its total size limit.",
                code="python_output_too_large",
                stdout=stdout,
                stderr=stderr,
            )
        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise StatisticalExecutionError(
                "The Python worker returned an invalid execution result.",
                stdout=stdout,
                stderr=stderr,
            ) from exc
        if not payload.get("ok"):
            raise StatisticalExecutionError(
                str(payload.get("error") or "Reviewed Python failed."),
                code=str(payload.get("code") or "python_execution_failed"),
                traceback=str(payload.get("traceback") or "")[:20_000],
                stdout=stdout,
                stderr=stderr,
            )

        warnings = list(payload.get("warnings") or [])
        if stdout_truncated:
            warnings.append("Standard output was truncated for display.")
        if stderr_truncated:
            warnings.append("Standard error was truncated for display.")
        try:
            outputs = [
                StatisticalOutput.model_validate(item)
                for item in payload.get("outputs") or []
            ]
        except ValueError as exc:
            raise StatisticalExecutionError(
                "The Python worker returned an invalid bounded output.",
                code="python_output_invalid",
                stdout=stdout,
                stderr=stderr,
            ) from exc
        return PythonExecutionResult(
            parent_result_id=parent_result_id,
            executed_python=code,
            attempt=attempt,
            outputs=outputs,
            stdout=stdout,
            stderr=stderr,
            elapsed_ms=elapsed_ms,
            warnings=warnings,
        )
