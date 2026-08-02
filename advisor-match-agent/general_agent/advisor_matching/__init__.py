"""Deterministic advisor identity matching and review workflows."""

from general_agent.advisor_matching.matcher import run_matching
from general_agent.advisor_matching.profiler import profile_advisor_file
from general_agent.advisor_matching.source import SyntheticAdvisorReferenceSource

__all__ = ["SyntheticAdvisorReferenceSource", "profile_advisor_file", "run_matching"]
