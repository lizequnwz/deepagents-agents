from __future__ import annotations

import os

import pytest


@pytest.mark.live
@pytest.mark.skipif(
    not os.getenv("RUN_LIVE_ADVISOR_MATCH_SMOKE"),
    reason="live provider smoke is explicitly opt-in",
)
def test_live_graph_smoke_is_opt_in() -> None:
    pytest.skip("Run the documented API smoke manually with configured credentials.")
