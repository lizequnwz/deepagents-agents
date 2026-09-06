"""Coordinator-owned charts with immutable versions and bounded presentation data."""

from uuid import uuid4
import json
import duckdb
from pydantic_core import to_json
from langchain.tools import tool, ToolRuntime
from data_analytics_agent.agents.text_to_sql.tools import _runtime_context
from data_analytics_agent.visualization.schemas import ChartSpec, ChartType
from data_analytics_agent.visualization.validation import (
    validate_chart_spec,
    chart_columns,
)

MAX_CHART_ROWS = 5000
MAX_CHART_BYTES = 4 * 1024 * 1024


def create_chart_tool(results, runs, *, source_id):
    @tool
    def create_chart(spec: ChartSpec, runtime: ToolRuntime) -> dict:
        """Validate and save one shared chart; returns chart_id for chat and reports.

        Use saved source or Python-derived datasets. Revise by previous_chart_id.
        Scalar/empty results do not need charts. If grain is wrong, ask SQL to
        reshape saved data. Never substitute an explicitly requested chart type.
        """
        context = _runtime_context(runtime)
        if committed := runs.storage.committed(context.run_id, runtime.tool_call_id):
            return json.loads(committed)
        try:
            source = results.get(spec.result_id, context.thread_id, source_id=source_id)
            if source.kind == "presentation":
                source = results.get(
                    source.parent_result_ids[0], context.thread_id, source_id=source_id
                )
            version = 1
            if spec.previous_chart_id:
                previous = runs.storage.load("charts", dict).get(spec.previous_chart_id)
                if (
                    not previous
                    or previous["thread_id"] != context.thread_id
                    or previous["source_id"] != source_id
                ):
                    raise ValueError("Previous chart is not in this conversation.")
                version = previous["spec"]["version"] + 1
            spec = spec.model_copy(
                update={
                    "chart_id": str(uuid4()),
                    "result_id": source.result_id,
                    "version": version,
                    "source_result_id": source.result_id,
                }
            )
            needed = chart_columns(spec)
            if not needed <= set(source.columns):
                raise ValueError("Chart references unknown columns.")
            columns = [name for name in source.columns if name in needed]
            sampled = source.row_count > MAX_CHART_ROWS
            if sampled and (
                spec.chart_type
                not in {ChartType.LINE, ChartType.AREA, ChartType.SCATTER}
                or spec.color
            ):
                raise ValueError(
                    "Aggregate or bin the full saved population before charting more than 5000 rows. Histograms must not silently use a sample."
                )
            with duckdb.connect() as db:
                relation = db.read_parquet(source.parquet_path).project(
                    ",".join('"' + name.replace('"', '""') + '"' for name in columns)
                )
                if sampled:
                    if spec.x and spec.chart_type in {ChartType.LINE, ChartType.AREA}:
                        field = '"' + spec.x.replace('"', '""') + '"'
                        relation.order(field).create_view("ordered_data")
                        stride = (source.row_count + 4998) // 4999
                        relation = db.sql(
                            f"SELECT * EXCLUDE (row_no) FROM (SELECT *, row_number() OVER () AS row_no FROM ordered_data) WHERE (row_no-1) % {stride}=0 OR row_no={source.row_count}"
                        )
                    else:
                        relation.create_view("chart_data")
                        relation = db.sql(
                            "SELECT * FROM chart_data USING SAMPLE reservoir(5000 ROWS) REPEATABLE(0)"
                        )
                table = relation.to_arrow_table()
            if (
                table.nbytes > MAX_CHART_BYTES
                or len(to_json(table.to_pylist())) > MAX_CHART_BYTES
            ):
                raise ValueError(
                    "Chart data exceeds 4 MiB. Shorten labels or aggregate the saved evidence before charting."
                )
            if sampled or columns != source.columns:
                presentation = results.save_batches(
                    table.to_batches(),
                    thread_id=context.thread_id,
                    source_id=source_id,
                    purpose=f"Chart presentation: {spec.title}",
                    kind="presentation",
                    parent_result_ids=[source.result_id],
                    truncated=source.truncated,
                )
                spec = spec.model_copy(update={"result_id": presentation.result_id})
            notes = list(spec.notes)
            if sampled:
                notes.append(
                    f"Downsampled to {table.num_rows:,} of {source.row_count:,} saved rows for display. Full data remains downloadable."
                )
            if source.truncated:
                notes.append(
                    "Source extraction is incomplete; the chart shows only the saved portion."
                )
            spec = spec.model_copy(update={"notes": notes})
            validate_chart_spec(
                spec,
                results.get(spec.result_id, context.thread_id, source_id=source_id),
            )
            runs.storage.put(
                "charts",
                spec.chart_id,
                {
                    "thread_id": context.thread_id,
                    "source_id": source_id,
                    "spec": spec.model_dump(mode="json"),
                },
                dict,
            )
            runs.add_chart(context.run_id, spec.model_dump(mode="json"))
            response = {
                "ok": True,
                "chart_id": spec.chart_id,
                "chart": spec.model_dump(mode="json"),
            }
            runs.storage.commit(
                context.run_id, runtime.tool_call_id, json.dumps(response)
            )
            return response
        except (ValueError, KeyError, duckdb.Error) as exc:
            return {"ok": False, "error": str(exc)}

    return create_chart
