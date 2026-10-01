"""Read-only execution fingerprints for the existing offline evaluation runner."""

from dataclasses import asdict
import hashlib
from importlib.metadata import distributions
import json
import os
from pathlib import Path
import platform


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
