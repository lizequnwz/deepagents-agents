"""Portable evidence bundles from a published turn, without model/source execution."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
from zipfile import ZipFile, ZIP_DEFLATED

from data_analytics_agent import export_replay
from data_analytics_agent.agents.data_analysis import worker
from data_analytics_agent.schemas import RunStatus


class ExportConflict(ValueError):
    pass


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def prepare_export(services, run_id, report_id):
    run = services.runs.get(run_id)
    answer = run.answer
    if run.status != RunStatus.COMPLETED or not answer or not answer.report:
        raise ExportConflict(
            "Complete the turn and its HTML report before downloading analysis."
        )
    if answer.report.report_id != report_id:
        raise ExportConflict(
            "This report has changed. Reload before downloading analysis."
        )
    report = services.reports.get(report_id, run.thread_id, source_id=run.source_id)
    if _hash(report.html_path) != report.html_sha256:
        raise ValueError("The stored report failed its content hash check.")
    datasets, steps = {}, {}
    visiting = set()
    available = {
        e.execution_id: e
        for key in services.conversations.get(run.thread_id).run_ids + [run_id]
        for e in services.runs.get_python_execution(key)
        if e.error is None
    }
    # Analyses can be reused in later turns; authoritative saved executions stay
    # scoped by conversation/source rather than the exporting run.
    analyses = {a.analysis_id: a for a in answer.analyses}
    for analysis_id in report.input_analysis_ids:
        analyses[analysis_id] = services.analyses.get(
            analysis_id, run.thread_id, source_id=run.source_id
        ).analysis
    for analysis in analyses.values():
        available.update(
            {e.execution_id: e for e in analysis.executions if e.error is None}
        )

    def add_step(execution):
        if execution.execution_id in steps:
            return
        marker = ("step", execution.execution_id)
        if marker in visiting:
            raise ValueError("Cyclic execution lineage.")
        visiting.add(marker)
        for result_id in execution.inputs.values():
            add_dataset(result_id)
        steps[execution.execution_id] = execution
        visiting.remove(marker)
        for result_id in execution.output_datasets.values():
            add_dataset(result_id)

    def add_dataset(result_id):
        if result_id in datasets:
            return
        marker = ("dataset", result_id)
        if marker in visiting:
            raise ValueError("Cyclic dataset lineage.")
        visiting.add(marker)
        result = services.results.get(result_id, run.thread_id, source_id=run.source_id)
        # Put it in the selection before resolving its producer's other outputs.
        datasets[result_id] = result
        for parent in result.parent_result_ids:
            add_dataset(parent)
        if result.kind == "python":
            execution = available.get(result.execution_id)
            if execution is None:
                raise ValueError("The exact producing Python execution is unavailable.")
            add_step(execution)
        visiting.remove(marker)

    selected = list(
        dict.fromkeys(
            [r.result_id for r in answer.results]
            + report.input_result_ids
            + [c.result_id for c in answer.charts]
        )
    )
    for result_id in selected:
        add_dataset(result_id)
    for analysis in analyses.values():
        if analysis.forecast_evaluation:
            for key in (
                analysis.forecast_evaluation.predictions_result_id,
                analysis.forecast_evaluation.scores_result_id,
            ):
                add_dataset(key)
                if key not in selected:
                    selected.append(key)
        for result_id in analysis.input_result_ids:
            add_dataset(result_id)
        for execution in analysis.executions:
            if execution.error is None:
                add_step(execution)
    if answer.analytical_input and not answer.source_expansion_allowed:
        from data_analytics_agent.analytical_scope import descends_from

        selected = [
            key
            for key in selected
            if descends_from(
                services.results,
                key,
                answer.analytical_input.input_result_id,
                run.thread_id,
                run.source_id,
            )
        ]
    return (
        run,
        answer,
        report,
        datasets,
        list(steps.values()),
        list(analyses.values()),
        selected,
    )


def write_bundle(services, run_id, report_id, target):
    """Write a temporary ZIP; caller owns cleanup after delivery."""
    run, answer, report, datasets, executions, analyses, selected = prepare_export(
        services, run_id, report_id
    )
    files = {}
    manifest = {
        "format_version": 2,
        "question": run.question,
        "analytical_input": answer.analytical_input.model_dump(mode="json")
        if answer.analytical_input
        else None,
        "source_expansion_allowed": answer.source_expansion_allowed,
        "refreshed_from_report_id": answer.refreshed_from_report_id,
        "forecast_evaluations": [
            a.forecast_evaluation.model_dump(mode="json")
            for a in analyses
            if a.forecast_evaluation
        ],
        "source_id": run.source_id,
        "partial": answer.partial,
        "unresolved_questions": answer.unresolved_questions,
        "population_complete": not any(d.truncated for d in datasets.values()),
        "source_freshness": "Unknown unless explicitly declared in the published evidence.",
        "sql_replay": "Saved snapshots; no warehouse refresh or SQL re-execution.",
        "limits": asdict(services.settings.python_execution_limits()),
        "selected_result_ids": selected,
        "lineage_result_ids": [key for key in datasets if key not in selected],
        "datasets": {},
        "steps": [],
        "files": files,
        "report_id": report_id,
        "runtime": {"python": platform.python_version()},
        "numerical_tolerance": {"rtol": 1e-7, "atol": 1e-10},
    }
    packages = {name: version(name) for name in ("pandas", "numpy", "pyarrow")}
    for execution in executions:
        packages.update(
            {k: v for k, v in execution.runtime_versions.items() if k != "python"}
        )
    manifest["runtime"].update(packages)
    manifest["dependency_record_note"] = (
        "Recorded execution versions where available. Baseline versions are from the export environment; older executions without records are not environment-certified."
    )
    warnings = list(
        dict.fromkeys(
            answer.unresolved_questions
            + [w for a in analyses for w in a.warnings]
            + [
                w
                for d in datasets.values()
                if d.upload_provenance
                for w in d.upload_provenance.warnings
            ]
        )
    )
    sql_queries = [
        {
            "result_id": d.result_id,
            "path": f"sql/query-{index + 1:03}.sql",
            "query": d.executed_sql,
            "kind": d.kind,
            "label": d.short_label,
            "snapshot_path": f"data/{d.result_id}.parquet",
            "parent_result_ids": d.parent_result_ids,
            "sql_bindings": d.sql_bindings,
            "question": d.originating_question,
        }
        for index, d in enumerate(
            sorted(
                (
                    d
                    for d in datasets.values()
                    if d.kind in {"source_sql", "saved_sql"} and d.executed_sql
                ),
                key=lambda d: (d.created_at, d.result_id),
            )
        )
    ]
    readme = f"""# {report.title}

Question: {run.question}

{answer.answer}

## Scope and limitations

Partial findings: {answer.partial}. Extracted populations complete: {manifest["population_complete"]}.
These are immutable saved snapshots. Source freshness/completeness is established only by an explicit source statement, not by upload time or first/last transaction dates.
Exact executed SQL is included for inspection; this package does not refresh warehouse data or re-execute SQL transformations.
Chart presentation snapshots may be sampled; their complete parents remain in data/ and the manifest.

"""
    if answer.analytical_input:
        from data_analytics_agent.analytical_scope import scope_description

        readme += scope_description(answer.analytical_input) + "\n\n"
        if answer.source_expansion_allowed:
            readme += "Additional source retrieval was explicitly authorized. The selected snapshot describes the starting population; consult the resulting evidence for expanded populations.\n\n"
    readme += "\n".join("- " + x for x in answer.assumptions + warnings)
    for analysis in analyses:
        readme += (
            f"\n\n## Method\n\n{analysis.method}\n\n{analysis.answer}\n"
            + "\n".join("- " + x for x in analysis.assumptions)
        )
        if analysis.forecast_evaluation:
            evaluation = analysis.forecast_evaluation
            readme += "\n\n## Forecast evaluation\n\n" + evaluation.description + "\n\n"
            readme += "\n".join("- " + warning for warning in evaluation.warnings)
            readme += f"\n\nPredictions: `data/{evaluation.predictions_result_id}.parquet`. Scores: `data/{evaluation.scores_result_id}.parquet`.\n"
    readme += "\n\n## SQL queries\n\n"
    if sql_queries:
        readme += (
            "Each file in sql/ contains one exact executed query. "
            "sql-provenance.json maps the files to their saved data snapshots, questions and input result IDs. "
            "Source queries refer to the original database; saved-data queries use named snapshot inputs. "
            "Input result IDs are evidence references, not warehouse table names.\n\n"
        )
        readme += "\n".join(
            f"- [{Path(q['path']).name}]({q['path']}) — {q['label']} "
            + ("(saved-data query)" if q["kind"] == "saved_sql" else "(source query)")
            for q in sql_queries
        )
    else:
        readme += "No SQL queries were recorded for this exported evidence.\n"
    readme += """

## Run locally

Use a Python environment matching manifest.json. Install dependencies with `python -m pip install -r requirements.txt`, then run `python analysis.py`.
Outputs go into replayed/. Each exact step in steps/ runs in a fresh local process, using explicit named inputs. SQL snapshots remain fixed boundaries. Notebook execution uses the same helper.
Open analysis.ipynb in Jupyter with this extracted folder as the working directory. Run all cells in order; editing a step changes replay code, never the stored evidence.
The HTML report contains the original published charts and narrative. The notebook retains stored compact tables and figures for viewing before replay.
Replay validates typed output datasets with rtol=1e-7 and atol=1e-10. Stochastic methods require explicit seeds in the original code; matching is not guaranteed otherwise. Successful replay alone does not establish methodological correctness.
Dependencies from recorded executions are included where available; versions for older executions are unknown. Custom/dynamic imports or code depending on external files/services require manual review. No environment files or service credentials are bundled.
"""
    manifest["warnings"] = warnings
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:

        def put(name, content):
            data = content.encode("utf-8") if isinstance(content, str) else content
            archive.writestr(name, data)
            files[name] = hashlib.sha256(data).hexdigest()

        def copy(name, path):
            archive.write(path, name)
            files[name] = _hash(path)

        for key, dataset in datasets.items():
            name = f"data/{key}.parquet"
            copy(name, dataset.parquet_path)
            manifest["datasets"][key] = {
                **dataset.model_dump(mode="json", exclude={"parquet_path", "preview"}),
                "path": name,
            }
        for index, execution in enumerate(executions):
            code_path = f"steps/step-{index + 1:03}.py"
            put(code_path, execution.executed_python)
            record = execution.model_dump(
                mode="json", exclude={"executed_python", "stderr", "stdout"}
            )
            for output_index, output in enumerate(record["outputs"]):
                if output.get("image_path"):
                    name = f"figures/step-{index + 1:03}-{output_index}.png"
                    copy(name, output["image_path"])
                    output["image_path"] = name
            record["code_path"] = code_path
            manifest["steps"].append(record)
        put("README.md", readme)
        put(
            "requirements.txt",
            "\n".join(f"{name}=={value}" for name, value in sorted(packages.items()))
            + "\n",
        )
        put(
            "analysis.py",
            'from pathlib import Path\nfrom replay import replay_all\n\nif __name__ == "__main__":\n    replay_all(Path(__file__).resolve().parent)\n',
        )
        put("replay.py", Path(export_replay.__file__).read_bytes())
        put("worker.py", Path(worker.__file__).read_bytes())
        copy("report.html", report.html_path)
        for query in sql_queries:
            put(query["path"], query["query"])
        put(
            "sql-provenance.json", json.dumps(sql_queries, indent=2, ensure_ascii=False)
        )
        put(
            "charts.json",
            json.dumps([c.model_dump(mode="json") for c in answer.charts], indent=2),
        )
        put("report-spec.json", report.spec.model_dump_json(indent=2))
        put("analysis.ipynb", build_notebook(manifest, readme, executions, datasets))
        archive.writestr(
            "manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False)
        )


def build_notebook(manifest, readme, executions, datasets):
    import base64
    import nbformat as nbf

    cells = [
        nbf.v4.new_markdown_cell(readme),
        nbf.v4.new_code_cell(
            "from pathlib import Path\nfrom replay import load_manifest, run_step\nROOT = Path.cwd()\nmanifest = load_manifest(ROOT)"
        ),
    ]
    for index, (step, execution) in enumerate(
        zip(manifest["steps"], executions, strict=True)
    ):
        cells.append(
            nbf.v4.new_markdown_cell(
                f"## Step {index + 1}\n\nNamed inputs: "
                + ", ".join(f"`{a}` → `{r}`" for a, r in step["inputs"].items())
                + "\n\nThe next cell saves the exact executed code. Edit it to explore, then run the replay cell. Each replay uses a fresh local Python process."
            )
        )
        cells.append(
            nbf.v4.new_code_cell(
                "%%writefile " + step["code_path"] + "\n" + execution.executed_python
            )
        )
        outputs = []
        for output in execution.outputs:
            data = {
                "text/plain": output.name
                + "\n"
                + (
                    output.text
                    if output.text is not None
                    else str(output.value)
                    if output.kind == "scalar"
                    else json.dumps(output.rows[:10], indent=2)
                    if output.kind == "table"
                    else "Saved diagnostic figure"
                )
            }
            if output.image_path:
                data["image/png"] = base64.b64encode(
                    Path(output.image_path).read_bytes()
                ).decode("ascii")
            outputs.append(nbf.v4.new_output("display_data", data=data, metadata={}))
        cell = nbf.v4.new_code_cell(
            f'payload = run_step(ROOT, {index})\nfrom IPython.display import display, Image\nfor output in payload["outputs"]:\n    if output.get("image_path"):\n        display(Image(filename=str(ROOT / output["image_path"])))\n    elif output["kind"] == "table":\n        display(output["name"], output["rows"][:10])\n    else:\n        display(output["name"], output.get("text") or output.get("value"))',
            outputs=outputs,
        )
        cells.append(cell)
    if not executions:
        cells.append(
            nbf.v4.new_markdown_cell(
                "## Saved data\n\nInspect complete snapshots locally. Exact SQL files, when present, are linked in README.md and indexed in sql-provenance.json."
            )
        )
        cells.append(
            nbf.v4.new_code_cell(
                'import pandas as pd\nfrom IPython.display import display\nfor result_id in manifest["selected_result_ids"]:\n    frame = pd.read_parquet(ROOT / manifest["datasets"][result_id]["path"])\n    display(result_id, frame.head(10))',
                outputs=[
                    nbf.v4.new_output(
                        "display_data",
                        data={
                            "text/plain": key
                            + "\n"
                            + json.dumps(
                                datasets[key].preview[:10], default=str, indent=2
                            )
                        },
                        metadata={},
                    )
                    for key in manifest["selected_result_ids"]
                ],
            )
        )
    if manifest["forecast_evaluations"]:
        from data_analytics_agent.forecasting import ForecastEvaluation

        descriptions = [
            ForecastEvaluation.model_validate(value)
            for value in manifest["forecast_evaluations"]
        ]
        cells.extend(
            [
                nbf.v4.new_markdown_cell(
                    "## Forecast evaluation\n\n"
                    + "\n\n".join(
                        value.description
                        + "\n\n"
                        + "\n".join("- " + warning for warning in value.warnings)
                        for value in descriptions
                    )
                    + "\n\nRecompute MAE, RMSE and measured coverage from the saved or replayed predictions; compare them with the saved scores."
                ),
                nbf.v4.new_code_cell(
                    "from replay import evaluate_forecasts\nforecast_scores = evaluate_forecasts(ROOT)\nfor score in forecast_scores:\n    display(score)"
                ),
            ]
        )
    cells.append(
        nbf.v4.new_markdown_cell(
            "## Published report\n\nOpen [report.html](report.html) to inspect the exact saved charts and report. Chart definitions are in charts.json; the report is not regenerated during replay."
        )
    )
    notebook = nbf.v4.new_notebook(
        cells=cells,
        metadata={
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {
                "name": "python",
                "version": manifest["runtime"]["python"],
            },
            "analysis_export": {
                "partial": manifest["partial"],
                "population_complete": manifest["population_complete"],
            },
        },
    )
    nbf.validate(notebook)
    return nbf.writes(notebook)
