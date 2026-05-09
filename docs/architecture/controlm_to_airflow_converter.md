# Control-M → Airflow Converter (agentic DAG)

## What this is

A reusable agent that converts BMC Control-M job exports into Apache Airflow
DAG files. Shipped as:

1. A pure-Python library at `agents/controlm_converter/` — usable from any
   Python script, notebook, or CI pipeline.
2. An Airflow orchestrator DAG at `scripts/dags/controlm_to_airflow_converter.py`
   that reads a folder of exports, fans out per-file with dynamic task
   mapping, and writes generated DAGs to disk.

Every generated DAG lands with `is_paused_upon_creation=True` — operator
review is mandatory before unpausing.

## Why agentic + per-type templates

Control-M ships **a lot** of job types, and customer environments customise
them further (Application Integrator plugins, custom job-type strings). A
flat `if/else` mapper rots fast.

Two-layer design:

- **Heuristic first**: `job_types.py::resolve_type` matches the registry by
  alias and field copy. ~90% of well-formed exports never hit the LLM.
- **LLM fallback** (`agent.py`): only invoked when the heuristic can't pick a
  type, or expected fields are missing. Uses `gemini-2.5-flash` (NOT lite —
  see `feedback_no_gemini_lite_fn_calls`) with a single tool call
  `submit_classification`. The model never writes DAG control flow; it only
  fills slot variables. The Jinja templates own structure.

Adding a new Control-M job type is a 2-line change:

1. Add an entry to `JOB_TYPE_REGISTRY` in `job_types.py`.
2. Drop a Jinja template in `agents/controlm_converter/templates/`.

No central edit, no agent retraining.

## Supported Control-M job types

| Control-M | Airflow operator | Template |
|---|---|---|
| `Job:Command`, `OS` | `BashOperator` (or `SSHOperator` if remote host) | `command.py.j2` |
| `Job:EmbeddedScript` | `BashOperator` (heredoc) | `embedded_script.py.j2` |
| `Job:FileWatcher`, `AFT:FileWatcher` | `FileSensor` / `S3KeySensor` | `file_watcher.py.j2` |
| `Job:FileTransfer`, `AFT`, `MFT`, `B2B` | `SFTPOperator` | `file_transfer.py.j2` |
| `Job:Database:SQLScript` / `EmbeddedQuery` | `SQLExecuteQueryOperator` | `database.py.j2` |
| `Job:SAP:R3` / `BW` | `BashOperator` → `sap_runner` wrapper | `sap.py.j2` |
| `Job:WebServices(:REST)` | `HttpOperator` | `web_services.py.j2` |
| `Job:Hadoop:Spark` / `HDFSCommands` | `SparkSubmitOperator` | `hadoop.py.j2` |
| `Job:Python` | `PythonOperator` (or `BashOperator` if script path) | `python.py.j2` |
| `Job:AWS:Lambda` / `Glue` / `Batch` | `LambdaInvokeFunctionOperator` | `aws.py.j2` |
| `Job:ApplicationIntegrator` | `HttpOperator` (generic plugin → REST) | `application_integrator.py.j2` |
| anything else | `BashOperator` with TODO marker | `generic.py.j2` |

## Dependency translation

Control-M wires jobs together via `OutCondition` → `InCondition` name
matches. `api.py::_build_edges` reproduces this in Airflow:
producer.OutConditions ∩ consumer.InConditions ⇒ `producer >> consumer`.

Time-window dependencies (`From`, `Until`) are NOT auto-translated — they
land in the operator-review TODOs. Airflow's natural model is schedule +
data-aware datasets, and shoehorning Control-M time windows usually masks
a deeper migration choice.

## Usage

### As a library

```python
from pathlib import Path
from agents.controlm_converter import convert_folder

results = convert_folder(
    Path("./exports/nightly_batch.json"),
    output_dir=Path("./generated_dags"),
)
for r in results:
    print(r["dag_id"], "->", r["path"], "ok=", r["ok"])
```

### As an Airflow DAG

1. Drop your Control-M exports (`.json` from Automation API or `.xml` from
   legacy EM) into `${CONTROLM_INPUT_DIR}` (default
   `/opt/airflow/data/controlm_in`).
2. Trigger `controlm_to_airflow_converter` from the Airflow UI. Override
   `input_path` / `output_dir` / `model` via DAG params if needed.
3. Generated DAG files appear under `${CONTROLM_OUTPUT_DIR}` grouped by
   source filename. They land paused.
4. Review each DAG (search for `TODO`), fix Connection IDs, then unpause.

### Single job (handy for unit tests)

```python
from agents.controlm_converter import convert_job
out = convert_job({"_name": "x", "Type": "Job:Command", "Command": "echo hi"})
print(out["source"])
```

## Validation

Every generated DAG goes through `validator.py::validate_dag_source`:

1. `compile()` — pure-Python syntax check.
2. If `airflow` CLI is on PATH, `airflow dags list --subdir` for a real parse.

Failures are surfaced in the orchestrator DAG's `summarise` task and never
silently dropped.

## Files

```
agents/controlm_converter/
  __init__.py
  api.py             # convert_job, convert_folder
  agent.py           # LLM classifier (heuristic + gemini-2.5-flash fallback)
  job_types.py       # registry of supported types
  parser.py          # AAPI JSON + legacy XML
  renderer.py        # Jinja per-task + DAG header rendering
  validator.py       # syntax + airflow-parse checks
  templates/
    _dag_header.py.j2
    command.py.j2
    embedded_script.py.j2
    file_watcher.py.j2
    file_transfer.py.j2
    database.py.j2
    sap.py.j2
    web_services.py.j2
    hadoop.py.j2
    python.py.j2
    aws.py.j2
    application_integrator.py.j2
    generic.py.j2

scripts/dags/controlm_to_airflow_converter.py   # the orchestrator DAG
```

## Known gaps / TODOs for v2

- Cyclic resource semaphores (`ControlResource`) — currently dropped on the floor.
- `RerunSpecificTimes`, calendar-based scheduling — emitted as `schedule=None`,
  must be set by hand.
- Variables: AAPI `%%PARM` substitutions are pass-through strings; should map
  to Airflow Variables / Jinja templating.
- LLM batch mode: today we call the model once per unclassified job.
  Batched calls (10–20 jobs per request) would cut cost ~5×.
