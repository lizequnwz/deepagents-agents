"""Strict user-facing requests; models never register physical repository roots."""

from typing import Literal
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CodingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectCreate(CodingRequest):
    root: str = Field(min_length=1, max_length=4096)
    name: str = Field(min_length=1, max_length=120)
    checks: dict[str, str] = Field(default_factory=dict)
    documentation_domains: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("documentation_domains")
    @classmethod
    def validate_domains(cls, domains: list[str]) -> list[str]:
        approved = []
        for domain in domains:
            domain = domain.strip().lower()
            if not re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", domain):
                raise ValueError("Documentation approval requires exact public hostnames, without URLs or wildcards.")
            if domain not in approved:
                approved.append(domain)
        return approved

    @field_validator("checks")
    @classmethod
    def validate_checks(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 10 or any(
            not name.strip() or len(name) > 80 or not command.strip()
            or len(command) > 4096 or "\x00" in command
            for name, command in value.items()
        ):
            raise ValueError("Approve at most ten named, bounded check commands.")
        return value


class TaskCreate(CodingRequest):
    message: str = Field(min_length=1, max_length=20000)
    mode: Literal["plan", "implement", "review"] = "plan"
    plan_id: str | None = None
    parent_id: str | None = None


class ApplyRequest(CodingRequest):
    expected_revision: str = Field(min_length=1, max_length=128)
    paths: list[str] | None = Field(default=None, max_length=5000)


class DecisionResponse(CodingRequest):
    response: Literal["approve", "reject"]


class SteeringRequest(CodingRequest):
    message: str = Field(min_length=1, max_length=4000)


class SetupRequest(CodingRequest):
    kind: Literal["python", "node"]
    manifest_identity: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")


class InputResponse(CodingRequest):
    message: str = Field(min_length=1, max_length=20000)


class GitHubConnect(CodingRequest):
    owner: str = Field(min_length=1, max_length=39, pattern=r"^[A-Za-z0-9][A-Za-z0-9-]*$")
    repository: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")


class DeliveryPrepare(CodingRequest):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=10000)
    base: str | None = Field(default=None, min_length=1, max_length=200)


class DeliveryPublish(CodingRequest):
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class DocumentOpen(CodingRequest):
    path: str = Field(min_length=1, max_length=1024)
    content: str = Field(max_length=200000)
    version: int = Field(strict=True, ge=1, le=2**31 - 1)


class DocumentUpdate(CodingRequest):
    content: str = Field(max_length=200000)
    version: int = Field(strict=True, ge=1, le=2**31 - 1)


class InlineRequest(CodingRequest):
    version: int = Field(strict=True, ge=1, le=2**31 - 1)
    offset_utf16: int = Field(strict=True, ge=0, le=200000)
    request_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class InlineCancel(CodingRequest):
    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class InlineAcceptance(CodingRequest):
    suggestion_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class SnowflakeEnable(CodingRequest):
    enabled: bool = Field(strict=True)
    expected_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class SnowflakeRead(CodingRequest):
    table: str = Field(min_length=1, max_length=386)
    columns: list[str] = Field(min_length=1, max_length=20)
    limit: int = Field(strict=True, ge=1, le=100, default=20)
    filters: dict[str, str | int | float | bool | None] = Field(default_factory=dict, max_length=8)
