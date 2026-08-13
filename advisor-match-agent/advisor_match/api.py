"""Synchronous, stateless FastAPI surface for Advisor Match."""

from __future__ import annotations

import json
import logging
import time
import uuid
from functools import partial
from io import BytesIO
from pathlib import PurePath
from typing import Annotated, Any
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from advisor_match.advisor_matching.index import ReferenceDataQualityError
from advisor_match.advisor_matching.profiler import inspect_advisor_upload
from advisor_match.advisor_matching.schemas import ProfileGenerationResult
from advisor_match.advisor_matching.source import (
    SyntheticAdvisorReferenceSource,
)
from advisor_match.api_models import (
    ErrorBody,
    ErrorResponse,
    MatchConfiguration,
    MatchMappingResponse,
    ProfileConfiguration,
    ProfileMappingResponse,
    SourceDescription,
)
from advisor_match.config import Settings, load_settings
from advisor_match.firm import FirmResolutionError
from advisor_match.files import InMemoryFile, InvalidUploadError, UnsupportedUploadType
from advisor_match.mapping import MappingModelError, MappingService
from advisor_match.advisor_service import (
    AdvisorService,
    ReferenceSourceError,
    ReferenceSourceFactory,
    SourceHashMismatch,
)

logger = logging.getLogger("advisor_match.api")

SourceFile = Annotated[
    UploadFile,
    File(description="CSV or XLSX source file."),
]
ConfigurationForm = Annotated[
    str,
    Form(
        max_length=64 * 1024,
        description=(
            "JSON containing the analyzed source SHA-256 and the confirmed mapping "
            "from the corresponding mapping endpoint."
        ),
        examples=[
            json.dumps(
                {
                    "analyzed_source_sha256": "0" * 64,
                    "mapping": {
                        "sheet_name": None,
                        "header_row": 1,
                        "crd_number": {"index": 0, "header": "CRD"},
                    },
                }
            )
        ],
    ),
]

_ERROR_DESCRIPTIONS = {
    400: "The upload is unreadable or invalid.",
    409: "The source file changed after analysis.",
    413: "The upload exceeds the configured size limit.",
    415: "The request or uploaded file uses an unsupported media type.",
    422: "The configuration or mapped input is invalid.",
    502: "The mapping model could not return a valid mapping.",
    503: "The authoritative advisor source is unavailable or invalid.",
    500: "Unexpected server error.",
}


def _error_responses(*statuses: int) -> dict[int, dict[str, Any]]:
    return {
        status: {"model": ErrorResponse, "description": _ERROR_DESCRIPTIONS[status]}
        for status in statuses
    }


def create_app(
    *,
    settings: Settings | None = None,
    mapping_service: MappingService | None = None,
    reference_source_factory: ReferenceSourceFactory | None = None,
) -> FastAPI:
    active_settings = settings or load_settings()
    errors = active_settings.readiness_errors(require_model=mapping_service is None)
    if errors:
        raise ValueError(" ".join(errors))
    _configure_logging(active_settings.log_level)
    mapper = mapping_service or MappingService(active_settings)
    source_factory = reference_source_factory or (
        lambda: SyntheticAdvisorReferenceSource(
            active_settings.synthetic_reference_path
        )
    )
    service = AdvisorService(active_settings, source_factory)

    app = FastAPI(
        title="Advisor Match API",
        version="1.0.0",
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.settings = active_settings
    app.state.mapping_service = mapper
    app.state.advisor_service = service

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = "req_" + uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        started = time.monotonic()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            json.dumps(
                {
                    "event": "api.request.completed",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                },
                separators=(",", ":"),
            )
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(request: Request, exc: RequestValidationError):
        return _error_response(
            request,
            422,
            "INVALID_REQUEST",
            "The request did not satisfy the API contract.",
            exc.errors(),
        )

    @app.exception_handler(_APIError)
    async def api_error(request: Request, exc: _APIError):
        return _error_response(
            request, exc.status, exc.code, exc.message, exc.details
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logger.exception(
            "Unexpected API error",
            extra={"request_id": getattr(request.state, "request_id", None)},
        )
        return _error_response(
            request,
            500,
            "INTERNAL_ERROR",
            "The API encountered an unexpected error.",
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "advisor-match", "version": "1.0.0"}

    @app.post(
        "/advisor-match/mapping",
        response_model=MatchMappingResponse,
        responses=_error_responses(400, 413, 415, 422, 502, 500),
    )
    async def map_advisor_input(file: SourceFile) -> MatchMappingResponse:
        source = await _read_upload(file, active_settings)
        try:
            source.validate_table_type()
            profile = await run_in_threadpool(
                inspect_advisor_upload, source, active_settings
            )
            decision = await mapper.propose_match(profile)
        except MappingModelError as exc:
            raise _APIError(502, "MAPPING_MODEL_FAILED", str(exc)) from exc
        except UnsupportedUploadType as exc:
            raise _APIError(415, "UNSUPPORTED_UPLOAD_TYPE", str(exc)) from exc
        except ValueError as exc:
            raise _APIError(400, "INVALID_UPLOAD", str(exc)) from exc
        validation = None
        validation_error = None
        if decision.mapping is not None:
            try:
                validation = await run_in_threadpool(
                    service.validate_match_input, source, decision.mapping
                )
            except ValueError as exc:
                validation_error = str(exc)
        return MatchMappingResponse(
            source=_source_description(source),
            profile=profile,
            decision=decision,
            validation=validation,
            validation_error=validation_error,
        )

    @app.post(
        "/advisor-match/match",
        response_class=Response,
        responses={
            200: {
                "description": (
                    "ZIP containing advisor_matches.xlsx and result.json."
                ),
                "content": {
                    "application/zip": {
                        "schema": {"type": "string", "format": "binary"}
                    }
                },
            },
            **_error_responses(400, 409, 413, 415, 422, 503, 500),
        },
    )
    async def match_advisors(
        file: SourceFile, configuration: ConfigurationForm
    ) -> Response:
        try:
            match_configuration = MatchConfiguration.model_validate_json(
                configuration
            )
        except ValidationError as exc:
            raise _APIError(
                422,
                "INVALID_CONFIGURATION",
                "The match configuration is invalid.",
                exc.errors(),
            ) from exc
        source = await _read_upload(file, active_settings)
        try:
            execution = await run_in_threadpool(
                partial(
                    service.match,
                    source,
                    analyzed_source_sha256=match_configuration.analyzed_source_sha256,
                    mapping=match_configuration.mapping,
                    firm_resolution=match_configuration.firm_resolution,
                    all_rows_firm=match_configuration.all_rows_firm,
                )
            )
        except SourceHashMismatch as exc:
            raise _APIError(409, "SOURCE_CHANGED", str(exc)) from exc
        except FirmResolutionError as exc:
            raise _APIError(
                422,
                "FIRM_RESOLUTION_REQUIRED",
                str(exc),
                exc.details.model_dump(mode="json"),
            ) from exc
        except ReferenceDataQualityError as exc:
            raise _APIError(
                503,
                exc.code,
                "The authoritative advisor source contains duplicate CRDs.",
                {
                    "duplicate_crd_count": len(exc.duplicate_crds),
                    "duplicate_crds": [
                        {"crd_number": crd, "occurrences": count}
                        for crd, count in list(exc.duplicate_crds.items())[:10]
                    ],
                },
            ) from exc
        except ReferenceSourceError as exc:
            raise _APIError(503, "REFERENCE_SOURCE_INVALID", str(exc)) from exc
        except UnsupportedUploadType as exc:
            raise _APIError(415, "UNSUPPORTED_UPLOAD_TYPE", str(exc)) from exc
        except InvalidUploadError as exc:
            raise _APIError(400, "INVALID_UPLOAD", str(exc)) from exc
        except ValueError as exc:
            raise _APIError(422, "INVALID_MATCH_INPUT", str(exc)) from exc
        content = _match_zip(execution.workbook, execution.result.model_dump(mode="json"))
        return Response(
            content=content,
            media_type="application/zip",
            headers={
                "Content-Disposition": 'attachment; filename="advisor_match_result.zip"'
            },
        )

    @app.post(
        "/advisor-profile/mapping",
        response_model=ProfileMappingResponse,
        responses=_error_responses(400, 413, 415, 422, 502, 500),
    )
    async def map_profile_input(file: SourceFile) -> ProfileMappingResponse:
        source = await _read_upload(file, active_settings)
        try:
            source.validate_table_type()
            profile = await run_in_threadpool(
                inspect_advisor_upload, source, active_settings
            )
            decision = await mapper.propose_crd(profile)
        except MappingModelError as exc:
            raise _APIError(502, "MAPPING_MODEL_FAILED", str(exc)) from exc
        except UnsupportedUploadType as exc:
            raise _APIError(415, "UNSUPPORTED_UPLOAD_TYPE", str(exc)) from exc
        except ValueError as exc:
            raise _APIError(400, "INVALID_UPLOAD", str(exc)) from exc
        validation = None
        validation_error = None
        if decision.mapping is not None:
            try:
                validation = await run_in_threadpool(
                    service.validate_profile_input, source, decision.mapping
                )
            except ValueError as exc:
                validation_error = str(exc)
        return ProfileMappingResponse(
            source=_source_description(source),
            profile=profile,
            decision=decision,
            validation=validation,
            validation_error=validation_error,
        )

    @app.post(
        "/advisor-profile/generate",
        response_model=ProfileGenerationResult,
        responses=_error_responses(400, 409, 413, 415, 422, 500),
    )
    async def generate_profile(
        file: SourceFile, configuration: ConfigurationForm
    ) -> ProfileGenerationResult:
        try:
            profile_configuration = ProfileConfiguration.model_validate_json(
                configuration
            )
        except ValidationError as exc:
            raise _APIError(
                422,
                "INVALID_CONFIGURATION",
                "The profile configuration is invalid.",
                exc.errors(),
            ) from exc
        source = await _read_upload(file, active_settings)
        try:
            result = await run_in_threadpool(
                partial(
                    service.generate_profile,
                    source,
                    analyzed_source_sha256=profile_configuration.analyzed_source_sha256,
                    mapping=profile_configuration.mapping,
                )
            )
        except SourceHashMismatch as exc:
            raise _APIError(409, "SOURCE_CHANGED", str(exc)) from exc
        except UnsupportedUploadType as exc:
            raise _APIError(415, "UNSUPPORTED_UPLOAD_TYPE", str(exc)) from exc
        except InvalidUploadError as exc:
            raise _APIError(400, "INVALID_UPLOAD", str(exc)) from exc
        except ValueError as exc:
            raise _APIError(422, "INVALID_PROFILE_INPUT", str(exc)) from exc
        return result

    return app


async def _read_upload(file: UploadFile, settings: Settings) -> InMemoryFile:
    filename = _upload_filename(file.filename)
    content = await file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise _APIError(
            413,
            "UPLOAD_TOO_LARGE",
            f"The uploaded file exceeds the {settings.max_upload_mb} MB limit.",
        )
    return InMemoryFile(filename, content, file.content_type)


def _upload_filename(value: str | None) -> str:
    name = PurePath((value or "").replace("\\", "/")).name.strip()
    if not name or name in {".", ".."}:
        raise _APIError(400, "INVALID_UPLOAD", "The uploaded filename is invalid.")
    return name


class _APIError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details


def _source_description(source) -> SourceDescription:
    return SourceDescription(
        filename=source.filename,
        format=source.suffix.removeprefix("."),
        sha256=source.sha256,
    )


def _match_zip(workbook: bytes, result: dict[str, Any]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as bundle:
        bundle.writestr("advisor_matches.xlsx", workbook)
        bundle.writestr(
            "result.json",
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True),
        )
    return output.getvalue()


def _error_response(
    request: Request,
    status: int,
    code: str,
    message: str,
    details: Any | None = None,
) -> JSONResponse:
    response = ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message,
            details=details,
            request_id=getattr(request.state, "request_id", None),
        )
    )
    return JSONResponse(status_code=status, content=response.model_dump(mode="json"))


def _configure_logging(level: str) -> None:
    logger.setLevel(level)
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )


app = create_app()
