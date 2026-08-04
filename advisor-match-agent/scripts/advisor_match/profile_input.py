"""Developer CLI for bounded advisor-input profiling."""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from general_agent.advisor_matching.profiler import inspect_advisor_upload
from general_agent.config import Settings

if __name__ == "__main__":
    print(json.dumps(inspect_advisor_upload(Path(sys.argv[1]), Settings(project_root=Path.cwd(), model_name="developer")), indent=2, default=str))
