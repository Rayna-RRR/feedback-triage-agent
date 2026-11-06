# Observation-task PostgreSQL storage

Local development keeps the existing JSON task format. On Vercel, observation tasks
require PostgreSQL: configuration, connection or schema failures return 503, never
a successful redirect backed by instance-local /tmp. Stale forms and concurrent
writes return 409 and require a fresh review before resubmission.

This change covers observation tasks only. Legacy CLI/Web run outputs remain files.
It adds no account system, permissions, multi-tenancy, paid service provisioning,
classification policy changes or automatic production release.

## State and concurrency

One row stores the existing complete task state as JSONB, including imports and
their normalized feedback, human actions, merge/split rules and audit events.
The key is (namespace, task_id). Each committed change increments revision.

A mutation reads one revision and commits with UPDATE ... WHERE revision=expected.
The entire state and corresponding audit commit in the same database transaction.
A concurrent winner makes the stale write affect zero rows: the loser receives
409, with no overwrite or success message. Browser import/action forms also submit
the revision they displayed, so sequential submissions from stale pages cannot
overwrite newer human decisions. There is no automatic conflict retry.

Demo initialization builds a complete synthetic seed in temporary scratch space
and publishes it in one INSERT. Concurrent initializers use create-if-absent.
Existing database demo tasks and their human changes are never reset by a page
load. Normal task reads, lists and saves do not need files left by another instance.

Existing local JSON tasks remain readable and are not automatically uploaded.
This change does not recover tasks already lost from historical Vercel /tmp.

## Configuration and initialization

| Runtime | Backend | Namespace |
| --- | --- | --- |
| Local default | JSON at FEEDBACK_RISK_TASKS_DIR, or data/observation_tasks | File directories |
| Local PostgreSQL opt-in | FEEDBACK_RISK_STORAGE_BACKEND=postgresql | local, or explicit namespace |
| Vercel Production | PostgreSQL required | production by default |
| Vercel Preview | PostgreSQL required | preview_ + branch hash, or explicit preview_ / preview- namespace |

The database URL is read from FEEDBACK_RISK_DATABASE_URL, then DATABASE_URL, then
POSTGRES_URL. Local JSON does not switch backends merely because a URL exists.
Vercel rejects an explicit JSON override. Preview rejects a production namespace;
without a branch identity it requires an explicit isolated Preview namespace.

Use an existing PostgreSQL database first. If none is available, prepare a Neon
project/test branch through its console, using an available free option only.
Do not purchase resources or enable a paid plan as part of this setup.
Copy the console's pooled PostgreSQL URL including its TLS parameters directly
into the secret configuration. Do not paste credentials into chat, source, logs,
PR descriptions or command-line arguments.

Initialize the existing database once using its SQL editor:

- Run feedback_triage_agent/sql/observation_tasks.sql.
- The script creates only fta_observation_tasks if absent; it does not drop,
  delete or rewrite existing task data.

Alternatively, after installing the project and configuring the secret URL and
FEEDBACK_RISK_STORAGE_BACKEND=postgresql in the process environment:

```bash
python scripts/init_observation_storage.py
```

Minimum Vercel console setup for this PR:

1. Set the URL variable for **Preview** only, using a dedicated Neon test branch
   if available. An automatically derived per-branch namespace also isolates
   task records when sharing a test database.
2. Keep FEEDBACK_RISK_DB_NAMESPACE unset to derive the Preview namespace from
   VERCEL_GIT_COMMIT_REF, or set a preview_ namespace scoped to this PR branch.
3. Enable system environment variables so VERCEL_GIT_COMMIT_SHA,
   VERCEL_DEPLOYMENT_ID and the Preview branch identity are available.
4. Rebuild this PR's Preview after its variables/schema are ready, then repeat
   the isolated synthetic browser acceptance there. Production configuration
   and release remain a separate, explicitly authorized step.

No cloud database credentials were available during initial local implementation.
Console resource existence must not be inferred from that local configuration scan.

## Health and diagnostics

/healthz returns commit_sha, process_start_id, deployment_id, storage_backend,
storage_available and storage_status. Vercel commit_sha comes only from the actual
VERCEL_GIT_COMMIT_SHA; missing/invalid values are unknown. Local processes capture
their checkout's HEAD when starting. No main SHA is hardcoded.

503 means storage is unconfigured/unavailable, including a missing schema.
The endpoint does not emit connection strings, driver error text or task content.
Process identity is a random startup identifier (also regenerated after fork),
not a region. X-Request-ID is validated or generated and returned on responses.
Storage logs use an allowlist of those identities, task ID, operation, backend
and result. An ordinary browser refresh alone proves neither a new instance nor
a cold start.

## Verification

```bash
python -m pytest
# To enable real PostgreSQL tests, provide TEST_POSTGRES_DSN in the environment,
# or TEST_POSTGRES_DSN_FILE pointing to a restricted local secret file.
python -m pytest tests/test_postgres_observation.py tests/test_storage_runtime.py
python -m feedback_triage_agent.cli harness --output data/harness_output_ci --skip-pytest
```

Run pytest separately before using harness --skip-pytest. Without a test DSN,
the PostgreSQL module explicitly skips; do not report that as a database pass.
CI uses its own disposable PostgreSQL 16 service, not a Neon/production database.
Integration tests create random preview_test_ namespaces and delete only their
own records after completion. Use a disposable test database, never production.

The integration suite starts two independent application OS processes, routes
creation and reading to different processes, terminates/restarts one process,
and checks distinct startup IDs with shared state. It tests simultaneous revision
conflicts, stale browser form rejection and a real PostgreSQL AFTER UPDATE failure
that rolls back task state, revision and audit together. Split/merge, rejected
imports and atomic demo seeding have separate coverage.

Browser acceptance must use separate P0 and counterexample tasks. Local PostgreSQL,
local Vercel-mode simulation, cloud Preview and Production evidence must be reported
separately. Validation of this branch does not imply that Production was deployed.
