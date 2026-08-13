# Advisor Match

Advisor Match is a purpose-built, stateless service for matching advisor input
files against an authoritative reference and generating placeholder profile
reports from validated CRDs. FastAPI exposes synchronous REST operations and a
two-tab Streamlit UI guides users through explicit forms.

The service has no conversations, graph checkpoints, database, repository, or
pod-local workflow storage. Each request contains the complete source bytes and
configuration it needs. Matching, validation, firm handling, candidate
generation, decisions, workbook generation, and profile rendering remain
deterministic Python. LangChain is used only for bounded structured column
mapping.

## API

| Endpoint | Purpose |
|---|---|
| `POST /advisor-match/mapping` | Profile a multipart CSV/XLSX and propose match columns. |
| `POST /advisor-match/match` | Revalidate the resent file and return a ZIP containing `advisor_matches.xlsx` and `result.json`. |
| `POST /advisor-profile/mapping` | Profile a multipart CSV/XLSX and propose its CRD column. |
| `POST /advisor-profile/generate` | Revalidate the resent file and return placeholder report HTML as JSON. |
| `GET /health` | Return process and API version status. |

Configured operations use multipart parts named `file` and `configuration`.
FastAPI handles uploads with its native spooled-file support, and the API
rejects files above the configured 50 MB default. Mapping responses include a
SHA-256 that must be resent in the next operation, preventing a changed file
from being processed against a stale form configuration.

## Run locally

Copy `.env.example` to `.env`, configure the OpenAI `MODEL_NAME` and
credentials, then run:

```bash
uv sync --locked --all-groups
./scripts/start.sh
```

`API_HOST` and `APP_HOST` may be loopback addresses for development or pod
addresses for deployment. Logs are written to stdout/stderr.

For EKS, deploy the API and Streamlit as separate workloads. API replicas need
no session affinity because every configured request resends its file and
configuration. Set the ingress body limit slightly above `MAX_UPLOAD_MB` for
multipart overhead, and set its response timeout above the longest synchronous
matching request.

## Important files

- `advisor_match/api.py` — the stateless FastAPI app factory and routes.
- `advisor_match/mapping.py` — bounded structured mapping calls.
- `advisor_match/advisor_service.py` — deterministic match/profile services.
- `advisor_match/advisor_matching/` — schemas, policy, normalization, matching,
  profiling/loading, reference adapter, workbook, and profile rendering.
- `streamlit_app.py` — ephemeral Advisor Matching and Profile Generation tabs.
- `notebooks/advisor_match_stateless_workflow.ipynb` — interactive API-first
  upload, mapping, matching, profile, preview, and download workflow.
- `docs/contracts/` — behavior and output contracts.

## Run the interactive notebook

Start the API, then launch the checked-in Jupyter notebook:

```bash
uv sync --locked --all-groups
uv run uvicorn advisor_match.api:app --host 127.0.0.1 --port 8001
# In another terminal:
uv run jupyter lab notebooks/advisor_match_stateless_workflow.ipynb
```

The notebook can also launch a local API from its kernel. It keeps uploaded
bytes in kernel memory and creates download files only under the ignored
`notebook_outputs/` directory.

Matching policy: `docs/contracts/matching-policy.yaml` (policy version 5).

## Validate

```bash
uv sync --locked --all-groups
uv run pytest
uv run python scripts/generate_advisor_match_fixtures.py
git diff --check
```

The live mapping-provider smoke test is opt-in. Profile reports intentionally
contain no fetched or simulated profile data.
