"""Print the authoritative serialized dashboard schema without opening storage."""

import json

from data_analytics_agent.dashboard.schemas import DashboardView

if __name__ == "__main__":
    print(json.dumps(DashboardView.model_json_schema(mode="serialization")))
