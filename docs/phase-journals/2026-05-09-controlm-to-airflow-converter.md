# 2026-05-09 — Control-M → Airflow agentic converter

## What shipped

Reusable agent + Airflow orchestrator DAG that converts BMC Control-M job
exports to Airflow DAGs.

- `agents/controlm_converter/` — library (parser, registry, agent, renderer, validator, api)
- `agents/controlm_converter/templates/*.py.j2` — one Jinja template per
  supported Control-M job type + DAG header
- `scripts/dags/controlm_to_airflow_converter.py` — Airflow DAG that runs
  the converter over a folder, fanning out per-file via dynamic task mapping
- `docs/architecture/controlm_to_airflow_converter.md` — architecture, usage,
  type table, gaps

## Why this matters now

Tied to the Control-M SaaS pivot (see `project_controlm_saas_pivot`). To make
DATAP.AI a credible AI-governance overlay for Control-M / Helix Control-M, we
need a story for Airflow shops migrating IN, and Control-M shops looking at
Airflow as a downstream target. Same engine, two flow directions.

Also doubles as a demo asset: convert a customer's nightly-batch folder live
in 5 minutes, with TODO markers visible. Sells the "we understand your
batch landscape" angle without implying we replace Control-M.

## Design decisions

**Heuristic-first, LLM-fallback.** A flat registry handles ~90% of well-formed
exports for free. The LLM only steps in for unknown `Type` strings or
missing fields. Cost stays near zero at typical migration scale (~thousands
of jobs per customer), and the agent has a tiny, supervised job
(submit one tool call, no DAG-flow synthesis).

**Per-type Jinja snippets, not one mega-template.** New job type = drop a
`.j2` + add a registry row. No central edit. Keeps the LLM out of structural
decisions.

**Folder = DAG.** Control-M folders are the unit of co-scheduling. One
generated DAG per folder preserves operator mental model during migration.

**`is_paused_upon_creation=True` on every generated DAG.** Non-negotiable.
Migrated DAGs must not auto-run; operator review is required.

**`gemini-2.5-flash`, NOT lite.** Per `feedback_no_gemini_lite_fn_calls` —
lite drops responses after function-call rounds. Default model wired
through `CONTROLM_CONVERTER_MODEL` env var.

## Alternatives considered

- **Pure-LLM end-to-end DAG synthesis.** Rejected. Non-deterministic, hard
  to review at scale, would need a custom validator anyway. The agent's
  scope is intentionally narrow.
- **One-shot Python translator (no LLM).** Works for canonical exports;
  collapses on Application Integrator plugins and customer custom types.
  The hybrid covers both worlds.
- **Use the existing Astronomer / GCP migration tools.** Closed-source +
  vendor lock-in. We need this in our agent stack to plug into the broader
  governance product.

## Verification

Offline smoke test (no LLM, no Airflow runtime) round-trips a 6-job synthetic
folder covering Database, FileWatcher, FileTransfer, WebServices, Hadoop, and
an unknown `Job:Mainframe:Cobol` (correctly fell through to `generic`):

```
parsed 6 jobs
  ExtractCustomers     -> database
  WatchDrop            -> file_watcher
  TransferToS3         -> file_transfer
  CallAPI              -> web_services
  RunSpark             -> hadoop
  WeirdLegacy          -> generic
--- syntax OK, total lines: 97
```

Generated DAG passes `compile()`. The `airflow dags list --subdir` deep parse
will run automatically when the DAG executes inside the Airflow container.

## Files added

- `agents/controlm_converter/__init__.py`
- `agents/controlm_converter/api.py`
- `agents/controlm_converter/agent.py`
- `agents/controlm_converter/job_types.py`
- `agents/controlm_converter/parser.py`
- `agents/controlm_converter/renderer.py`
- `agents/controlm_converter/validator.py`
- `agents/controlm_converter/templates/_dag_header.py.j2`
- `agents/controlm_converter/templates/command.py.j2`
- `agents/controlm_converter/templates/embedded_script.py.j2`
- `agents/controlm_converter/templates/file_watcher.py.j2`
- `agents/controlm_converter/templates/file_transfer.py.j2`
- `agents/controlm_converter/templates/database.py.j2`
- `agents/controlm_converter/templates/sap.py.j2`
- `agents/controlm_converter/templates/web_services.py.j2`
- `agents/controlm_converter/templates/hadoop.py.j2`
- `agents/controlm_converter/templates/python.py.j2`
- `agents/controlm_converter/templates/aws.py.j2`
- `agents/controlm_converter/templates/application_integrator.py.j2`
- `agents/controlm_converter/templates/generic.py.j2`
- `scripts/dags/controlm_to_airflow_converter.py`
- `docs/architecture/controlm_to_airflow_converter.md`

No DDL. No env vars required (defaults work). Optional env:
`CONTROLM_INPUT_DIR`, `CONTROLM_OUTPUT_DIR`, `CONTROLM_CONVERTER_MODEL`.

## Pending

- LLM-side: batched classification (10–20 jobs/request) — saves ~5× cost on
  large migrations. Plumbed in `agent.py::classify_batch` but currently
  serial.
- Airflow Connection auto-creation: today we leave Connection IDs as TODOs.
  Could pull from Control-M ConnectionProfiles and emit a companion
  `connections.json` for `airflow connections import`.
- Unit tests: only smoke test landed. Real fixture pack covering each
  job type would harden against template regressions.
- Calendar / time-window translation (`RerunSpecificTimes`, `From`, `Until`).

## Related

- Memory: `project_controlm_saas_pivot` — strategy context
- Memory: `feedback_no_gemini_lite_fn_calls` — model choice rationale
- Architecture doc: `docs/architecture/controlm_to_airflow_converter.md`
