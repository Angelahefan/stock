"""
Control-M job type registry.

Each entry maps a normalised Control-M job type to:
  - the Airflow operator we render
  - the Jinja template filename
  - a list of Control-M field names we expect to extract
  - the Airflow provider package required (for requirements check)

Source for the type names:
  https://docs.bmc.com/xwiki/bin/view/Main/Documentation/ControlM/Automation-API/
  (JobTypes section of the deploy JSON schema)

Adding a new job type = add an entry + a template. Nothing else needs to change.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass(frozen=True)
class ControlMJobType:
    name: str                  # canonical name used by templates / agent
    aliases: tuple             # Control-M "Type" / "SubApplication" strings that map here
    airflow_operator: str      # FQN, e.g. airflow.providers.ssh.operators.ssh.SSHOperator
    template: str              # filename in templates/
    expected_fields: tuple     # fields the agent should extract from the source job
    provider_pkg: str = ""     # pip package needed (informational)
    notes: str = ""


JOB_TYPE_REGISTRY: Dict[str, ControlMJobType] = {
    j.name: j for j in [
        ControlMJobType(
            name="command",
            aliases=("Job:Command", "Command", "OS"),
            airflow_operator="airflow.operators.bash.BashOperator",
            template="command.py.j2",
            expected_fields=("command", "host", "run_as", "env"),
            notes="Plain shell command. Maps to BashOperator (local) or SSHOperator if remote host.",
        ),
        ControlMJobType(
            name="embedded_script",
            aliases=("Job:EmbeddedScript", "EmbeddedScript"),
            airflow_operator="airflow.operators.bash.BashOperator",
            template="embedded_script.py.j2",
            expected_fields=("script", "interpreter", "run_as", "env"),
            notes="Inline script body. We materialise it via heredoc inside BashOperator.",
        ),
        ControlMJobType(
            name="file_watcher",
            aliases=("Job:FileWatcher", "FileWatcher", "AFT:FileWatcher"),
            airflow_operator="airflow.sensors.filesystem.FileSensor",
            template="file_watcher.py.j2",
            expected_fields=("path", "min_size", "stable_seconds", "timeout"),
            provider_pkg="apache-airflow-providers-ftp",
            notes="Watches a path. For S3 paths, swap to S3KeySensor (template handles both).",
        ),
        ControlMJobType(
            name="file_transfer",
            aliases=("Job:FileTransfer", "FileTransfer", "AFT", "MFT", "B2B"),
            airflow_operator="airflow.providers.sftp.operators.sftp.SFTPOperator",
            template="file_transfer.py.j2",
            expected_fields=("source_host", "source_path", "dest_host", "dest_path", "protocol"),
            provider_pkg="apache-airflow-providers-sftp",
            notes="MFT/AFT/B2B → SFTPOperator or S3CopyObjectOperator depending on protocol.",
        ),
        ControlMJobType(
            name="database",
            aliases=("Job:Database:SQLScript", "Job:Database:EmbeddedQuery", "Database"),
            airflow_operator="airflow.providers.common.sql.operators.sql.SQLExecuteQueryOperator",
            template="database.py.j2",
            expected_fields=("connection", "sql", "sql_file", "db_type", "params"),
            provider_pkg="apache-airflow-providers-common-sql",
            notes="Maps Control-M DB connection profile → Airflow Connection ID.",
        ),
        ControlMJobType(
            name="sap",
            aliases=("Job:SAP:R3", "Job:SAP:BW", "SAP"),
            airflow_operator="airflow.operators.bash.BashOperator",
            template="sap.py.j2",
            expected_fields=("sap_system", "abap_program", "variant", "step_user", "language"),
            notes="No mainstream Airflow SAP provider. We shell out to `sapcontrol` / RFC wrapper.",
        ),
        ControlMJobType(
            name="web_services",
            aliases=("Job:WebServices", "Job:WebServices:REST", "WebServices"),
            airflow_operator="airflow.providers.http.operators.http.HttpOperator",
            template="web_services.py.j2",
            expected_fields=("url", "method", "headers", "body", "auth_type"),
            provider_pkg="apache-airflow-providers-http",
        ),
        ControlMJobType(
            name="hadoop",
            aliases=("Job:Hadoop:Spark", "Job:Hadoop:HDFSCommands", "Hadoop"),
            airflow_operator="airflow.providers.apache.spark.operators.spark_submit.SparkSubmitOperator",
            template="hadoop.py.j2",
            expected_fields=("application", "spark_conf", "args", "master"),
            provider_pkg="apache-airflow-providers-apache-spark",
        ),
        ControlMJobType(
            name="python",
            aliases=("Job:Python", "Python"),
            airflow_operator="airflow.operators.python.PythonOperator",
            template="python.py.j2",
            expected_fields=("script", "module", "callable", "args"),
            notes="If `script` is a path on disk we exec it via BashOperator (python <path>).",
        ),
        ControlMJobType(
            name="aws",
            aliases=("Job:AWS:Lambda", "Job:AWS:Glue", "Job:AWS:Batch", "AWS"),
            airflow_operator="airflow.providers.amazon.aws.operators.lambda_function.LambdaInvokeFunctionOperator",
            template="aws.py.j2",
            expected_fields=("aws_service", "function_name", "payload", "region", "aws_conn_id"),
            provider_pkg="apache-airflow-providers-amazon",
        ),
        ControlMJobType(
            name="application_integrator",
            aliases=("Job:ApplicationIntegrator", "Job:AI"),
            airflow_operator="airflow.providers.http.operators.http.HttpOperator",
            template="application_integrator.py.j2",
            expected_fields=("ai_job_type", "endpoint", "params"),
            notes="Generic AI plugin. Modelled as REST → HttpOperator.",
        ),
        ControlMJobType(
            name="generic",
            aliases=("*",),
            airflow_operator="airflow.operators.bash.BashOperator",
            template="generic.py.j2",
            expected_fields=("raw",),
            notes="Fallback. Wraps the original Control-M command line in a BashOperator and "
                  "leaves a TODO for the operator to review.",
        ),
    ]
}


def resolve_type(controlm_type: str) -> ControlMJobType:
    """Map a raw Control-M `Type` string to a registry entry, falling back to `generic`."""
    if not controlm_type:
        return JOB_TYPE_REGISTRY["generic"]
    raw = controlm_type.strip()
    for entry in JOB_TYPE_REGISTRY.values():
        if raw in entry.aliases:
            return entry
        for alias in entry.aliases:
            if alias != "*" and raw.lower().startswith(alias.lower()):
                return entry
    return JOB_TYPE_REGISTRY["generic"]


def list_supported_types() -> List[str]:
    return [name for name in JOB_TYPE_REGISTRY if name != "generic"]
