"""Developer CLI for inspecting comparison-only normalization."""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from general_agent.advisor_matching import normalization as n

if __name__ == "__main__":
    value = sys.argv[2]
    functions = {"crd": n.crd, "email": n.email, "name": n.person_name, "firm": n.firm, "city": n.city, "state": n.state, "zip": n.zip_code}
    print(json.dumps({"field": sys.argv[1], "source": value, "normalized": functions[sys.argv[1]](value)}))
