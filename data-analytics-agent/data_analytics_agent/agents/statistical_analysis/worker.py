"""Child-process entry point for reviewed statistical Python."""

from __future__ import annotations

import base64
from io import BytesIO
import json
import math
from pathlib import Path
import pickle
import struct
import sys
import traceback
from typing import Any

import numpy as np
import pandas as pd


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, pd.Timedelta):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_value(item) for item in value]
    return str(value)


def _table_output(name: str, frame: pd.DataFrame, limits: dict[str, Any]):
    if len(frame.index) > limits["max_output_rows"]:
        raise ValueError(
            f"Output {name!r} has {len(frame.index)} rows; compact it to at most "
            f"{limits['max_output_rows']}."
        )
    if len(frame.columns) > limits["max_output_columns"]:
        raise ValueError(
            f"Output {name!r} has {len(frame.columns)} columns; compact it to at most "
            f"{limits['max_output_columns']}."
        )
    clean = frame.copy()
    clean.columns = [str(column) for column in clean.columns]
    return {
        "name": name,
        "kind": "table",
        "columns": list(clean.columns),
        "rows": [
            {str(key): _json_value(value) for key, value in row.items()}
            for row in clean.to_dict(orient="records")
        ],
    }


def _figure_output(
    name: str,
    value: Any,
    limits: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    if not type(value).__module__.startswith("matplotlib."):
        raise TypeError
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure

    figure = value.figure if isinstance(value, Axes) else value
    if not isinstance(figure, Figure):
        raise TypeError
    width, height = figure.get_size_inches() * figure.dpi
    if width > limits["max_figure_width"] or height > limits["max_figure_height"]:
        raise ValueError(
            f"Figure {name!r} is {width:.0f}x{height:.0f}; keep it within "
            f"{limits['max_figure_width']}x{limits['max_figure_height']} pixels."
        )
    image = BytesIO()
    figure.savefig(image, format="png", dpi=figure.dpi, bbox_inches="tight")
    data = image.getvalue()
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        rendered_width, rendered_height = struct.unpack(">II", data[16:24])
        if (
            rendered_width > limits["max_figure_width"]
            or rendered_height > limits["max_figure_height"]
        ):
            raise ValueError(
                f"Rendered figure {name!r} is {rendered_width}x{rendered_height}; "
                f"keep it within {limits['max_figure_width']}x"
                f"{limits['max_figure_height']} pixels."
            )
    if len(data) > limits["max_figure_bytes"]:
        raise ValueError(
            f"Figure {name!r} is {len(data)} bytes; keep it within "
            f"{limits['max_figure_bytes']} bytes."
        )
    return (
        {
            "name": name,
            "kind": "figure",
            "image_base64": base64.b64encode(data).decode("ascii"),
            "media_type": "image/png",
        },
        len(data),
    )


def _normalize_outputs(
    raw_outputs: Any,
    limits: dict[str, Any],
    input_frame: pd.DataFrame,
) -> list[dict[str, Any]]:
    if not isinstance(raw_outputs, dict):
        raise TypeError(
            "analysis_outputs must be a dictionary of output names to values."
        )
    if not raw_outputs:
        raise ValueError(
            "analysis_outputs must contain at least one compact named output."
        )
    if len(raw_outputs) > limits["max_output_items"]:
        raise ValueError(
            f"analysis_outputs has {len(raw_outputs)} items; keep at most "
            f"{limits['max_output_items']}."
        )

    outputs: list[dict[str, Any]] = []
    figure_count = 0
    figure_bytes = 0
    for raw_name, value in raw_outputs.items():
        name = str(raw_name).strip()
        if not name or len(name) > 200:
            raise ValueError("Each analysis output needs a 1-200 character name.")
        try:
            output, image_size = _figure_output(name, value, limits)
        except TypeError:
            output = None
            image_size = 0
        if output is not None:
            figure_count += 1
            figure_bytes += image_size
            if figure_count > limits["max_figures"]:
                raise ValueError(
                    f"Return at most {limits['max_figures']} figures."
                )
            if figure_bytes > limits["max_total_figure_bytes"]:
                raise ValueError(
                    "Combined figure bytes exceed the configured limit."
                )
            outputs.append(output)
            continue
        if isinstance(value, pd.Series):
            column_name = str(value.name or "value")
            outputs.append(
                _table_output(name, value.rename(column_name).reset_index(), limits)
            )
        elif isinstance(value, pd.DataFrame):
            if value is input_frame or value.equals(input_frame):
                raise ValueError(
                    "analysis_outputs cannot return the complete input DataFrame; "
                    "return a compact statistical summary instead."
                )
            outputs.append(_table_output(name, value, limits))
        elif isinstance(value, np.ndarray):
            array = np.asarray(value)
            if array.ndim == 1:
                frame = pd.DataFrame({"value": array})
            elif array.ndim == 2:
                frame = pd.DataFrame(array)
            else:
                raise ValueError(
                    f"Array output {name!r} must have one or two dimensions."
                )
            outputs.append(_table_output(name, frame, limits))
        elif isinstance(value, list) and value and all(
            isinstance(item, dict) for item in value
        ):
            outputs.append(_table_output(name, pd.DataFrame(value), limits))
        elif isinstance(value, list) and not value:
            outputs.append({"name": name, "kind": "text", "text": "[]"})
        elif isinstance(value, str):
            outputs.append({"name": name, "kind": "text", "text": value})
        elif value is None or isinstance(
            value, str | int | float | bool | np.generic
        ):
            outputs.append(
                {"name": name, "kind": "scalar", "value": _json_value(value)}
            )
        elif isinstance(value, dict):
            outputs.append(
                {
                    "name": name,
                    "kind": "text",
                    "text": json.dumps(_json_value(value), ensure_ascii=False),
                }
            )
        else:
            raise TypeError(
                f"Unsupported analysis output type for {name!r}: "
                f"{type(value).__name__}."
            )

    non_image_payload = [
        {key: value for key, value in output.items() if key != "image_base64"}
        for output in outputs
    ]
    serialized = json.dumps(non_image_payload, ensure_ascii=False)
    if len(serialized) > limits["max_output_chars"]:
        raise ValueError(
            "Non-image analysis outputs exceed the configured character limit."
        )
    return outputs


def main() -> int:
    if len(sys.argv) != 5:
        return 2
    frame_path, code_path, limits_path, output_path = map(Path, sys.argv[1:])
    try:
        with frame_path.open("rb") as file:
            df = pickle.load(file)
        code = code_path.read_text(encoding="utf-8")
        limits = json.loads(limits_path.read_text(encoding="utf-8"))
        namespace: dict[str, Any] = {
            "__name__": "__statistical_analysis__",
            "df": df,
            "pd": pd,
            "np": np,
        }
        exec(compile(code, "<reviewed-statistical-analysis>", "exec"), namespace)
        outputs = _normalize_outputs(
            namespace.get("analysis_outputs"),
            limits,
            df,
        )
        payload = {"ok": True, "outputs": outputs, "warnings": []}
        status = 0
    except BaseException as exc:
        payload = {
            "ok": False,
            "code": "python_execution_failed",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(limit=20)[-20_000:],
        }
        status = 1
    Path(output_path).write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return status


if __name__ == "__main__":
    raise SystemExit(main())
