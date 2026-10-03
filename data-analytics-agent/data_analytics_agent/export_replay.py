"""Standalone snapshot replay helper, also shipped verbatim in analysis bundles."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

import pandas as pd
import pyarrow.parquet as pq


def load_manifest(root):
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest["format_version"] != 2:
        raise ValueError("Unsupported analysis bundle version.")
    for relative, expected in manifest["files"].items():
        # Notebook cells and step files are editable; verify immutable evidence.
        if not (
            relative.startswith(("data/", "figures/")) or relative == "report.html"
        ):
            continue
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("Invalid bundle path.")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != expected:
            raise ValueError(f"Bundle file changed: {relative}")
    return manifest


def check_diagnostics(expected, actual):
    import math

    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if not isinstance(actual, (int, float)) or not math.isclose(
            expected, actual, rel_tol=1e-7, abs_tol=1e-10
        ):
            raise AssertionError(
                f"Diagnostic differs: expected {expected!r}, got {actual!r}"
            )
    elif isinstance(expected, dict):
        if not isinstance(actual, dict) or set(expected) != set(actual):
            raise AssertionError("Diagnostic keys differ.")
        for key in expected:
            check_diagnostics(expected[key], actual[key])
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            raise AssertionError("Diagnostic rows differ.")
        for a, b in zip(expected, actual, strict=True):
            check_diagnostics(a, b)
    elif expected != actual:
        raise AssertionError(
            f"Diagnostic differs: expected {expected!r}, got {actual!r}"
        )


def run_step(root, index):
    """Fresh process and inputs for every step; persist its portable replay outputs."""
    root = Path(root).resolve()
    manifest = json.loads((root / "manifest.json").read_text())
    step = manifest["steps"][index]
    replay = root / "replayed"
    replay.mkdir(exist_ok=True)
    bindings = {}
    producers = {
        result_id: i
        for i, item in enumerate(manifest["steps"])
        for result_id in item["output_datasets"].values()
    }
    for alias, result_id in step["inputs"].items():
        producer = producers.get(result_id)
        path = (
            replay / f"{result_id}.parquet"
            if producer is not None
            else root / manifest["datasets"][result_id]["path"]
        )
        if not path.exists():
            raise ValueError(f"Run step {producer + 1} before step {index + 1}.")
        bindings[alias] = str(path)
    with TemporaryDirectory(prefix="analysis-replay-") as directory:
        work = Path(directory)
        (work / "bindings.json").write_text(json.dumps(bindings))
        (work / "limits.json").write_text(json.dumps(manifest["limits"]))
        env = {
            key: os.environ[key]
            for key in ("PATH", "LANG", "LC_ALL", "SYSTEMROOT")
            if key in os.environ
        }
        env.update(
            HOME=str(work),
            TMPDIR=str(work),
            MPLBACKEND="Agg",
            MPLCONFIGDIR=str(work),
            PYTHONHASHSEED="0",
            PYTHONNOUSERSITE="1",
            PYTHONDONTWRITEBYTECODE="1",
        )
        result = subprocess.run(
            [
                sys.executable,
                str(root / "worker.py"),
                str(work / "bindings.json"),
                str(root / step["code_path"]),
                str(work / "limits.json"),
                str(work / "outputs.json"),
            ],
            cwd=work,
            env=env,
            timeout=manifest["limits"]["timeout_seconds"],
            capture_output=True,
            text=True,
        )
        if not (work / "outputs.json").exists():
            raise RuntimeError(result.stderr or "Replay worker returned no outputs.")
        payload = json.loads((work / "outputs.json").read_text())
        if not payload.get("ok"):
            raise RuntimeError(payload.get("error", result.stderr))
        # Checks deliberately compare typed data independently of file encodings.
        # Randomized code without fixed seeds may legitimately fail these checks.
        for alias, result_id in step["output_datasets"].items():
            generated = Path(payload["output_datasets"][alias])
            expected = root / manifest["datasets"][result_id]["path"]
            actual_table, expected_table = (
                pq.read_table(generated),
                pq.read_table(expected),
            )
            if (
                actual_table.schema.remove_metadata()
                != expected_table.schema.remove_metadata()
            ):
                raise AssertionError(
                    f"{alias}: replay schema differs from the stored result."
                )
            pd.testing.assert_frame_equal(
                actual_table.to_pandas(),
                expected_table.to_pandas(),
                check_exact=False,
                rtol=1e-7,
                atol=1e-10,
            )
            (replay / f"{result_id}.parquet").write_bytes(generated.read_bytes())
        stored_diagnostics = {
            o["name"]: o for o in step["outputs"] if o["kind"] in ("scalar", "table")
        }
        replayed_diagnostics = {
            o["name"]: o for o in payload["outputs"] if o["kind"] in ("scalar", "table")
        }
        for name, expected in stored_diagnostics.items():
            actual = replayed_diagnostics[name]
            key = "value" if expected["kind"] == "scalar" else "rows"
            check_diagnostics(expected[key], actual[key])
        # Save compact diagnostics and figures, keeping images out of terminal text.
        import base64

        for i, output in enumerate(payload["outputs"]):
            if image := output.pop("image_base64", None):
                image_path = replay / f"step-{index + 1}-{i}.png"
                image_path.write_bytes(base64.b64decode(image))
                output["image_path"] = str(image_path.relative_to(root))
        (replay / f"step-{index + 1}.json").write_text(
            json.dumps(payload, ensure_ascii=False)
        )
        if result.stdout:
            print(result.stdout[:10000], end="")
        print(
            f"Step {index + 1}: replayed {len(step['output_datasets'])} datasets; numerical tolerance rtol=1e-7, atol=1e-10."
        )
        return payload


def evaluate_forecasts(root):
    """Independent arithmetic checks using portable prediction/score snapshots."""
    import numpy as np

    root = Path(root)
    manifest = load_manifest(root)
    frames = []
    for evaluation in manifest["forecast_evaluations"]:
        key = evaluation["predictions_result_id"]
        replayed = root / "replayed" / f"{key}.parquet"
        frame = pd.read_parquet(replayed if replayed.exists() else root / manifest["datasets"][key]["path"])
        times = pd.to_datetime(frame[evaluation["time_column"]])
        test = frame[times.between(evaluation["holdout_start"], evaluation["holdout_end"])]
        scores = []
        for column, method in [(evaluation["candidate_column"], evaluation["candidate_method"]), (evaluation["baseline_column"], evaluation["baseline_method"])]:
            error = test[column] - test[evaluation["actual_column"]]
            row = {"method": method, "sample_size": len(test), "mae": float(np.abs(error).mean()), "rmse": float(np.sqrt(np.square(error).mean())), "measured_interval_coverage": None, "nominal_coverage": None}
            if column == evaluation["candidate_column"] and evaluation["interval"]:
                row["measured_interval_coverage"] = float(test[evaluation["actual_column"]].between(test[evaluation["lower_bound"]], test[evaluation["upper_bound"]]).mean())
                row["nominal_coverage"] = evaluation["interval"]["nominal_coverage"]
            scores.append(row)
        computed = pd.DataFrame(scores)
        stored = pd.read_parquet(root / manifest["datasets"][evaluation["scores_result_id"]]["path"])
        pd.testing.assert_frame_equal(computed, stored, check_dtype=False, check_exact=False, rtol=1e-7, atol=1e-10)
        frames.append(computed)
    return frames


def replay_all(root):
    root = Path(root).resolve()
    manifest = load_manifest(root)
    for index in range(len(manifest["steps"])):
        run_step(root, index)
    evaluate_forecasts(root)
    if not manifest["steps"]:
        for result_id in manifest["selected_result_ids"]:
            frame = pd.read_parquet(root / manifest["datasets"][result_id]["path"])
            print(f"{result_id}: {len(frame)} rows, columns {list(frame.columns)}")
    print(
        "Replay covers saved snapshots. SQL extraction is not refreshed. Read README.md for scope and limitations."
    )
