# PowerShellAssay playground

The example policy selects a worker script for native PowerShell parser inspection and configures a Python-driven behavior test for the sample pipeline.

Install the pinned PowerShell version and put it on `PATH`.
[Repository setup](../README.md)

```sh
python3 playground/run.py
```

The v2 receipt preserves command arguments, exits, and raw logs for
readiness, catalogue explanations, source tests, the showcase verification,
and the provisional scan control. The scan control expects
`Inconclusive` with exit `2`. The wrapper propagates a failed or
incomplete showcase and refuses a contradictory receipt and process exit.

For the native receipt alone, run each command independently.

```sh
PYTHONPATH=src python3 -m powershell_assay scan --policy examples/policy.json
PYTHONPATH=src python3 -m powershell_assay verify --policy examples/policy.json
```

A `Pass` from `verify` covers the selected script and its configured behavior command. The example `scan` reports `Inconclusive` with exit `2` and records the behavior command as `NotRun`.
