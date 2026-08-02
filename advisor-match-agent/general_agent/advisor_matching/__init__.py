"""Deterministic advisor identity matching and review workflows."""

from general_agent.advisor_matching.matcher import run_matching
from general_agent.advisor_matching.profiler import inspect_advisor_upload
from general_agent.advisor_matching.source import SyntheticAdvisorReferenceSource

__all__ = ["SyntheticAdvisorReferenceSource", "inspect_advisor_upload", "run_matching"]
