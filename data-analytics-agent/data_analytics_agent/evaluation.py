"""Read-only execution fingerprints for the existing offline evaluation runner."""

from dataclasses import asdict
import hashlib
from importlib.metadata import distributions
import json
import os
from pathlib import Path
import platform


def tool_observation(name, output):
    """Compact identities and timings, independent of truncated inspection panels."""
    from langchain_core.messages import ToolMessage

    if isinstance(output, ToolMessage):
        output = output.content
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except ValueError:
            output = {"error": output}
    if not isinstance(output, dict):
        return None
    if name not in {"inline_semantic_context", "get_semantic_context", "browse_semantic_model", "lookup_values", "execute_sql", "query_saved_results"}:
        return None
    entities = []
    candidates = []
    for dataset in output.get("datasets", []):
        entities.append("dataset:" + dataset["name"])
        entities.extend("field:" + dataset["name"] + "." + f["name"] for f in dataset.get("fields", []))
    entities.extend("metric:" + m["name"] for m in output.get("metrics", []))
    entities.extend("relationship:" + r["name"] for r in output.get("relationships", []))
    for items in output.get("candidates", {}).values():
        candidates.extend((c.get("dataset") + "." if c.get("dataset") else "") + c["name"] for c in items)
    for item in output.get("items", []):
        if "name" in item:
            candidates.append((item.get("dataset") + "." if item.get("dataset") else "") + item["name"])
    return {
        "tool": name, "mode": output.get("mode"), "model_hash": output.get("model_hash"),
        "entities": sorted(set(entities)), "candidates": sorted(set(candidates)),
        "response_characters": len(json.dumps(output, ensure_ascii=False, separators=(",", ":"))),
        "definitions_complete": output.get("definitions_complete"),
        "result_id": output.get("result_id"), "truncated": output.get("truncated"),
        "source_ms": output.get("elapsed_ms"), "semantic_grounding": output.get("semantic_grounding"),
        "error_code": output.get("code"), "error": output.get("error"),
    }


def inline_observation(messages, source_id):
    """Observe definitions actually supplied in a system prompt, without storing it."""
    from langchain_core.messages import SystemMessage
    from data_analytics_agent.semantic_context import INLINE_CONTEXT_HEADER

    for batch in messages:
        for message in batch:
            if not isinstance(message, SystemMessage):
                continue
            text = message.text
            if INLINE_CONTEXT_HEADER not in text:
                continue
            encoded = text.split(INLINE_CONTEXT_HEADER, 1)[1]
            try:
                context, _ = json.JSONDecoder().raw_decode(encoded)
            except ValueError:
                continue
            if isinstance(context, dict) and context.get("source_id") == source_id and context.get("projection") == "physical" and context.get("definitions_complete") is True:
                return tool_observation("inline_semantic_context", context)
    return None


def semantic_metrics(run, expected, review):
    """Measure recall and the independently reviewed first correct snapshot."""
    receipts = run.get("evaluation_receipts", [])
    discovered = set().union(*(set(r.get("entities", [])) for r in receipts))
    selected = set()
    for r in receipts:
        grounding = r.get("semantic_grounding") or {}
        selected.update(grounding.get("selected_entities", []))
        selected.update("metric:" + name for name in grounding.get("metric_names", []))
        selected.update("relationship:" + name for name in grounding.get("relationship_names", []))
    required = set(expected.get("required_entities", []))
    snapshots = [r for r in receipts if r.get("tool") in {"execute_sql", "query_saved_results"}]
    snapshot_reviews = review.get("snapshot_reviews", {})
    successful = [r for r in snapshots if r.get("result_id") and r.get("truncated") is False]
    complete_reviews = all(snapshot_reviews.get(r["result_id"], {}).get("status") in {"pass", "fail"} and snapshot_reviews[r["result_id"]].get("evidence") for r in successful)
    correct_id = next((r["result_id"] for r in successful if snapshot_reviews.get(r["result_id"], {}).get("status") == "pass"), None) if complete_reviews else None
    correct = next((r for r in snapshots if r.get("result_id") == correct_id and r.get("truncated") is False), None) if correct_id else None
    measured_receipts = receipts[:receipts.index(correct) + 1] if correct else receipts
    return {
        "required_entity_recall": len(required & discovered) / len(required) if required else None,
        "grounded_entity_recall": len(required & selected) / len(required) if required else None,
        "missing_entities": sorted(required - selected),
        "snapshot_reviews_complete": bool(successful and complete_reviews),
        "first_correct_result_id": correct_id,
        "discovery_calls": sum(r.get("tool") in {"get_semantic_context", "browse_semantic_model"} for r in receipts),
        "discovery_characters": sum(r.get("response_characters", 0) for r in receipts if r.get("tool") in {"get_semantic_context", "browse_semantic_model"}),
        "inline_definition_characters": sum(r.get("response_characters", 0) for r in receipts if r.get("tool") == "inline_semantic_context"),
        "discovery_ms": sum(r.get("duration_ms", 0) for r in receipts if r.get("tool") in {"get_semantic_context", "browse_semantic_model"}),
        "source_ms": sum(r.get("source_ms") or 0 for r in measured_receipts if r.get("tool") in {"execute_sql", "lookup_values"}),
        "model_ms": correct.get("model_ms") if correct else None,
        "cumulative_model_input_tokens": ((run.get("run_diagnostics") or {}).get("tokens") or {}).get("input_tokens") if not (run.get("run_diagnostics") or {}).get("token_usage_partial", True) else None,
        "active_ms_to_first_correct_snapshot": correct.get("active_ms") if correct else None,
        "sql_repair_count": snapshots.index(correct) if correct else None,
        "sql_error_count": sum(bool(r.get("error")) for r in snapshots),
        "first_attempt_correct": bool(correct and snapshots and snapshots[0] is correct) if correct else None,
    }


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def files_hash(files: dict[str, str]) -> str:
    return hashlib.sha256(
        json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def receipt_hash(folder: Path) -> str:
    return files_hash(
        {
            path.name: file_hash(path)
            for path in sorted(folder.iterdir())
            if path.is_file()
        }
    )


def evaluation_context(settings, catalog, source_ids: list[str]) -> dict:
    """Fingerprint the serving checkout/settings, never the client's checkout.

    Only requested SQLite snapshots are read. Remote source contents cannot be
    fingerprinted here, and must not be described as frozen by the evaluator.
    Credentials and environment files are neither inspected nor returned.
    """
    code_root = Path(__file__).resolve().parents[1]
    code = {
        str(path.relative_to(code_root)): file_hash(path)
        for path in sorted((code_root / "data_analytics_agent").rglob("*.py"))
    }
    instruction_paths = [
        settings.project_root / "AGENTS.md",
        *sorted((settings.project_root / "skills").rglob("*.md")),
    ]
    instructions = {
        str(path.relative_to(settings.project_root)): file_hash(path)
        for path in instruction_paths
    }
    runtime = {
        name: value
        for name, value in asdict(settings).items()
        if name
        not in {
            "project_root",
            "data_sources_config_path",
            "api_base_url",
            "transcription_model",
        }
    }
    provider_options = (
        [
            "OPENAI_API_BASE",
            "OPENAI_BASE_URL",
            "OPENAI_PROXY",
            "OPENAI_ORG_ID",
            "OPENAI_ORGANIZATION",
        ]
        if settings.model_provider == "openai"
        else [
            "AWS_REGION",
            "AWS_DEFAULT_REGION",
            "AWS_PROFILE",
            "AWS_ENDPOINT_URL_BEDROCK_RUNTIME",
        ]
    )
    runtime["provider_environment_sha256"] = {
        name: hashlib.sha256(value.encode()).hexdigest()
        if (value := os.getenv(name)) is not None
        else None
        for name in provider_options
    }
    sources = {}
    for source_id in sorted(set(source_ids)):
        source = catalog.get(source_id)
        snapshot_hash = None
        if source.backend_type == "sqlite":
            path = Path(source.target["path"]).expanduser()
            if not path.is_absolute():
                path = settings.project_root / path
            wal = path.with_name(path.name + "-wal")
            snapshot_hash = files_hash(
                {
                    "database": file_hash(path),
                    **({"wal": file_hash(wal)} if wal.exists() else {}),
                }
            )
        sources[source_id] = {
            "semantic_sha256": file_hash(source.semantic_model_path),
            "snapshot_sha256": snapshot_hash,
            "frozen": snapshot_hash is not None,
        }
    return {
        "code_files": code,
        "code_sha256": files_hash(code),
        "instruction_files": instructions,
        "instructions_sha256": files_hash(instructions),
        "dependencies_sha256": file_hash(code_root / "uv.lock"),
        "registry_sha256": (
            file_hash(settings.data_sources_config_path)
            if settings.data_sources_config_path.is_file()
            else None
        ),
        "runtime": runtime,
        "versions": {
            "python": platform.python_version(),
            **{dist.metadata["Name"]: dist.version for dist in distributions()},
        },
        "sources": sources,
    }
