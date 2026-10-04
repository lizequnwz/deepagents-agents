# Coding connector setup and authority

Connectors run in the application, outside model-controlled shell commands.
Credentials are corporation-scoped server settings and are not sent into coding
containers. Responses and connector errors redact configured credential values.
The trusted-local corporation header is a namespace, not authentication.

## Public documentation

Approve exact public website hostnames when registering a project. Without
approved domains, the model receives no documentation tools. Fetch accepts
public HTTPS only, validates all DNS results, pins the selected public address
and verifies TLS/SNI/peer identity. Redirects must remain within the approved
domains. Private/loopback/link-local addresses, arbitrary ports, ambient proxy
and TLS logging are rejected.

One attempt can fetch six pages, perform two searches and make twelve total
requests, including redirects. Response bounds are 512 KiB per request and
two MiB total, with at most 50,000 extracted text characters per page. Limits
and provenance persist across question resume. Immutable evidence records source
URL, retrieval time and content hash; retrieved text cannot grant authority.

Set `BRAVE_SEARCH_API_KEY` only if domain-scoped search is intended. Search goes
through the fixed public Brave endpoint and filters results to the approved
website. The key stays in the broker and is redacted from retained evidence.
Documentation access does not enable container internet access.

## GitHub

Configure tokens in server-only `.env` or the process environment:

```dotenv
GITHUB_TOKENS_JSON={"A123456":"REPLACE_WITH_GITHUB_TOKEN"}
```

Use a token restricted to the intended repository and capabilities. Configure
read permissions for repository metadata/content and issues/pull requests.
Draft delivery additionally needs repository content and pull-request write
permission; workflows may require additional permission under GitHub's policy.
Token creation and scopes are operator actions. Do not put real tokens into
source, task messages or editor settings.

In the workbench's **GitHub** section, explicitly connect owner/repository.
The broker pins its repository ID and uses `api.github.com` with API version
`2026-03-10`. GitHub Enterprise hosts are not supported. Agent tools are limited
to repository, issue and PR reads; issue text cannot authorize a write.

After a local change, **Prepare delivery review** reads the remote base and
freezes the exact source revision, complete UTF-8 diff/modes, validation evidence,
base commit, new `codex/` branch, title, body and remote actions. Preparation
creates no remote resource. Touched remote files must match the reviewed
preimages; unrelated remote files remain in the existing base tree. Delivery
rejects binary/oversized proposals, links/submodules, more than 100 touched files,
more than five MiB of file versions, or a diff beyond 200,000 characters.

Only **Publish this draft PR** (or its exact digest-bound API action) starts
publication. It creates a Git tree and commit, a new branch and a draft PR;
it does not overwrite a branch or merge. Base, source and verification drift
invalidate review. Publishing can trigger repository workflows. Each mutation
has a durable intent and receipt. Timeout, interrupted publication or ambiguous
remote response produces an uncertain result; inspect its journal and GitHub
before taking a new action. The application never automatically retries it.

Routes:

- `GET/POST /projects/{id}/github` for status/connection; issue/PR reads below it.
- `POST /changes/{id}/deliveries` for a concrete delivery review.
- `GET /sessions/{id}/deliveries` and `GET /deliveries/{id}` for proposals/receipts.
- `POST /deliveries/{id}/publish` with `expected_digest` for one reviewed delivery.

No live branch or PR was created during implementation. Deterministic tests
use mocked API receipts, including uncertainty and restart recovery.

## Snowflake

Configure a reviewed profile per corporation:

```dotenv
SNOWFLAKE_CONNECTIONS_JSON={"A123456":{"account":"org-account","token":"REPLACE_WITH_BEARER_TOKEN","token_type":"OAUTH","role":"DEV_READER","warehouse":"DEV_WH","database":"APP","schema":"PUBLIC","tables":["APP.PUBLIC.EVENTS"]}}
```

This first connector accepts `org-account.snowflakecomputing.com` style account
hostnames. Region-qualified, PrivateLink, government and custom domains are
unsupported. `token_type` accepts `OAUTH`, `PROGRAMMATIC_ACCESS_TOKEN`, or an
operator-provided `KEYPAIR_JWT`; token refresh/signing is not implemented.
Credential provisioning and expiration management remain operator actions.
Use a dedicated read role and appropriate warehouse/resource controls.

Review the token-free profile in **Snowflake reads**, then click **Enable these
Snowflake reads**. This binds the project to its exact account, role, warehouse
and allowed table profile. Changing configuration invalidates that approval.
Disable or revise the profile after pending project tasks finish.

Reads use the SQL API with explicit role/warehouse/database/schema and a
ten-second statement timeout. Supported operations are schema inspection and
bounded `SELECT` of explicit simple column names from at most 50 approved
fully qualified tables. Structured equality filters use typed bindings;
null uses `IS NULL`. There are no arbitrary SQL strings, expressions, UDFs,
procedures, joins, DDL/DML, deployments or table changes.

Each rows request selects at most 20 columns and returns at most 100 rows;
eight bounded equality filters are supported. Schema inspection returns at
most 100 columns. Transfer is limited to one MiB and one result partition.
Truncation is explicit. Query admission allows one active read per corporation
and 20 requests per minute. Reads can incur warehouse costs even when bounded.
No claim of a fixed monetary cost ceiling is made.

The broker submits once, records its request ID and any statement handle,
polls for a finite duration, and attempts cancellation on failure or Stop when
the handle is known. Every query has durable intent/status/provenance; model
reads also freeze result evidence outside repository source. A restart marks
unfinished reads interrupted with cancellation unconfirmed and does not submit
them again. If the submit response was lost, the ten-second server statement
timeout bounds a query whose handle the application never received.

Routes:

- `GET/POST /projects/{id}/snowflake` for displayed profile and digest-bound enable.
- `GET /projects/{id}/snowflake/schema?table=APP.PUBLIC.EVENTS` for schema.
- `POST /projects/{id}/snowflake/rows` with table, columns, limit and filters.
- `GET /projects/{id}/snowflake/reads` for durable query receipts.

No Snowflake query was sent during implementation. Compiler/scope, typed
bindings, polling, cancellation, redaction, receipts and restart behavior are
tested with mocked responses. Snowpark/dbt/Streamlit source tasks can use the
normal coding workflow where locked offline dependencies support them; live
account execution, data changes and deployment remain separate capabilities.
