"""
Parse Control-M job definitions exported via the BMC Automation API
(`ctm deploy` JSON) or via legacy XML.

The parser is deliberately lenient: Control-M exports vary between EM/SaaS
versions and customer customisation. We extract a normalised dict and let the
LLM agent fill in the gaps via tool calls.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Union
from xml.etree import ElementTree as ET


def _flatten_aapi(node: dict, parent_path: str = "") -> Iterable[Dict[str, Any]]:
    """
    A Control-M Automation-API JSON file is a tree:
        { "Folder1": {"Type": "Folder", "Job1": {...}, "Job2": {...} } }
    Walk it and yield every leaf job dict with its folder path attached.
    """
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        if not isinstance(value, dict):
            continue
        type_str = str(value.get("Type", ""))
        if type_str.startswith("Folder") or type_str == "SimpleFolder":
            yield from _flatten_aapi(value, parent_path=f"{parent_path}/{key}".strip("/"))
        elif type_str.startswith("Job"):
            yield {
                "_name": key,
                "_folder": parent_path,
                "_source": "aapi-json",
                **value,
            }
        else:
            # Unknown wrapper — descend in case it contains jobs
            yield from _flatten_aapi(value, parent_path=f"{parent_path}/{key}".strip("/"))


def _parse_xml(text: str) -> List[Dict[str, Any]]:
    """Parse legacy Control-M EM XML export (<JOB> elements)."""
    jobs: List[Dict[str, Any]] = []
    root = ET.fromstring(text)
    for job_el in root.iter("JOB"):
        d: Dict[str, Any] = {"_source": "xml"}
        d.update({k: v for k, v in job_el.attrib.items()})
        for child in job_el:
            if child.tag in ("INCOND", "OUTCOND", "VARIABLE"):
                d.setdefault(child.tag.lower() + "s", []).append(dict(child.attrib))
            else:
                d[child.tag.lower()] = (child.text or "").strip()
        d.setdefault("_name", d.get("jobname") or d.get("application") or "unnamed_job")
        d.setdefault("_folder", d.get("application", ""))
        if "Type" not in d and "tasktype" in d:
            d["Type"] = d["tasktype"]
        jobs.append(d)
    return jobs


def parse_controlm_export(payload: Union[str, dict, Path]) -> List[Dict[str, Any]]:
    """
    Accepts:
      - dict (already-parsed Automation-API JSON)
      - str containing JSON or XML
      - Path to a .json or .xml file
    Returns: list of normalised job dicts.
    """
    if isinstance(payload, Path):
        text = payload.read_text()
        if payload.suffix.lower() == ".xml":
            return _parse_xml(text)
        return parse_controlm_export(text)

    if isinstance(payload, dict):
        return list(_flatten_aapi(payload))

    text = payload.strip()
    if text.startswith("<"):
        return _parse_xml(text)
    return list(_flatten_aapi(json.loads(text)))


def extract_dependencies(job: dict) -> Dict[str, List[str]]:
    """Pull Control-M IN/OUT conditions, which we map to Airflow upstream tasks."""
    in_conds, out_conds = [], []
    for k in ("InConditions", "incond", "incondition"):
        v = job.get(k)
        if isinstance(v, list):
            in_conds.extend(c.get("Name") or c.get("name") for c in v if isinstance(c, dict))
    for k in ("OutConditions", "outcond", "outcondition"):
        v = job.get(k)
        if isinstance(v, list):
            out_conds.extend(c.get("Name") or c.get("name") for c in v if isinstance(c, dict))
    # Also handle the AAPI-flat form: keys named "InCondition1", "OutCondition1" etc.
    for k, v in job.items():
        if not isinstance(v, dict):
            continue
        t = str(v.get("Type", ""))
        if t == "InCondition" and v.get("Name"):
            in_conds.append(v["Name"])
        elif t == "OutCondition" and v.get("Name"):
            out_conds.append(v["Name"])
    return {
        "upstream_conditions": [c for c in in_conds if c],
        "produced_conditions": [c for c in out_conds if c],
    }
