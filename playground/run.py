#!/usr/bin/env python3
"""Run the repository's declared playground checks and retain their evidence."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'PowerShellAssay'
PACKAGE = 'powershell_assay'
POLICY = 'examples/policy.json'
SNAPSHOT = None
NATIVE_CACHE = 'powershell'
EXITS = {"Pass": 0, "Inconclusive": 2, "Fail": 1, "ToolFailure": 3}


def interpreter():
    if PACKAGE == "contract_assay":
        locked = Path.home() / ".cache/canonflow-portfolio/contracts-locked/bin/python"
        if locked.is_file():
            return str(locked)
    return sys.executable


def run(args):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    if NATIVE_CACHE:
        native = Path.home() / ".cache/canonflow-source-assays" / NATIVE_CACHE
        env["PATH"] = os.pathsep.join((str(native), os.environ.get("PATH", "")))
    try:
        result = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    except (OSError, UnicodeError, subprocess.TimeoutExpired) as error:
        return {"argv": args, "exitCode": None, "error": str(error)}
    return {"argv": args, "exitCode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def json_result(args):
    result = run(args)
    try:
        payload = json.loads(result.get("stdout", ""))
    except ValueError:
        payload = None
    return result, payload if isinstance(payload, dict) else None


def worst(verdicts):
    return max(verdicts, key=tuple(EXITS).index)


def doctor(cli):
    command, payload = json_result([*cli, "doctor"])
    if payload is None or command["exitCode"] not in (0, 2):
        verdict = "ToolFailure"
    elif command["exitCode"] == 2 or payload.get("ready") is False:
        verdict = "Inconclusive"
    else:
        verdict = "Pass"
    return {"verdict": verdict, "command": command}


def catalogue(cli):
    command, payload = json_result([*cli, "catalog"])
    rules = payload.get("rules") if payload is not None else None
    if command["exitCode"] != 0 or not isinstance(rules, list):
        return {"verdict": "ToolFailure", "command": command, "explanations": []}
    if not rules:
        return {"verdict": "Inconclusive", "command": command, "explanations": []}
    if any(not isinstance(rule, dict) or not isinstance(rule.get("id"), str) or not rule["id"]
           for rule in rules):
        return {"verdict": "ToolFailure", "command": command, "explanations": []}

    ids = [rule["id"] for rule in rules]
    if len(ids) != len(set(ids)):
        return {"verdict": "ToolFailure", "command": command, "explanations": []}

    explanations = []
    for rule_id in ids:
        execution, explanation = json_result([*cli, "explain", rule_id])
        outcome = ("Pass" if execution["exitCode"] == 0 and explanation is not None
                   and explanation.get("id") == rule_id else "ToolFailure")
        explanations.append({"id": rule_id, "verdict": outcome, "command": execution})
    return {"verdict": worst(row["verdict"] for row in explanations),
            "command": command, "explanations": explanations}


def unit_tests(python):
    command = run([python, "-m", "unittest", "discover", "-s", "tests", "-v"])
    stderr = command.get("stderr", "")
    count = re.search(r"^Ran (\d+) tests? in ", stderr, re.MULTILINE)
    skips = re.search(r"\bskipped=(\d+)\b", stderr)
    total = int(count.group(1)) if count else None
    skipped = int(skips.group(1)) if skips else 0
    if total is None or skipped > total or command["exitCode"] not in (0, 1):
        verdict = "ToolFailure"
    elif command["exitCode"] == 1:
        verdict = "Fail"
    elif total == skipped:
        verdict = "Inconclusive"
    else:
        verdict = "Pass"
    return {"verdict": verdict, "total": total, "skipped": skipped, "command": command}


def compare_verdict(cli, mode, args):
    command, receipt = json_result([*cli, mode, *args])
    observed = receipt.get("verdict") if receipt is not None else None
    if not isinstance(observed, str) or observed not in EXITS or EXITS[observed] != command["exitCode"]:
        verdict = "ToolFailure"
    elif mode == "scan":
        verdict = {"Pass": "Fail", "Inconclusive": "Pass"}.get(observed, observed)
    else:
        verdict = observed
    return {"verdict": verdict, "observedVerdict": observed, "command": command}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", default=POLICY, help="Reviewed policy for the showcase")
    if SNAPSHOT is not None:
        parser.add_argument("--snapshot", default=SNAPSHOT, help="Snapshot for the showcase")
    options = parser.parse_args()

    python = interpreter()
    cli = [python, "-m", PACKAGE]
    args = ([options.snapshot] if SNAPSHOT is not None else []) + ["--policy", options.policy]
    sections = {
        "doctor": doctor(cli),
        "00-rule-matrix": catalogue(cli),
        "unit-tests": unit_tests(python),
        "01-domain-showcase": compare_verdict(cli, "verify", args),
        "02-inconclusive-control": compare_verdict(cli, "scan", args),
    }
    verdict = worst(section["verdict"] for section in sections.values())
    print(json.dumps({"schemaVersion": "canonflow.assay.playground-receipt/v2",
                      "repository": REPOSITORY, "sections": sections, "verdict": verdict}, indent=2))
    return EXITS[verdict]


if __name__ == "__main__":
    raise SystemExit(main())
