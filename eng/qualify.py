"""Retain actual native and independent package evidence for the current checkout."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from package import ROOT, package


def qualified_run(name, argv, cwd, out, env, expected):
    completed = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, timeout=300)
    stdout = out / f"{name}.stdout"
    stderr = out / f"{name}.stderr"
    stdout.write_bytes(completed.stdout)
    stderr.write_bytes(completed.stderr)
    (out / f"{name}.json").write_text(json.dumps({
        "command": [str(arg) for arg in argv],
        "cwd": str(cwd),
        "exitCode": completed.returncode,
        "stdoutSha256": hashlib.sha256(completed.stdout).hexdigest(),
        "stderrSha256": hashlib.sha256(completed.stderr).hexdigest(),
    }, indent=2) + "\n")
    if completed.returncode != expected:
        print(completed.stdout.decode(errors="replace"))
        print(completed.stderr.decode(errors="replace"), file=sys.stderr)
        raise RuntimeError(f"{name}: expected exit {expected}, received {completed.returncode}")
    return completed.stdout


def main():
    out = ROOT / "artifacts" / "qualification"
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    qualified_run("tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                  ROOT, out, env, 0)
    tests = (out / "tests.stderr").read_text()
    count = int(re.search(r"Ran (\d+) tests?", tests)[1])
    archive = package()
    original = archive.read_bytes()
    if package().read_bytes() != original:
        raise RuntimeError("archive is not deterministic")
    with tempfile.TemporaryDirectory(prefix="source-assay-consumer-") as directory:
        consumer = Path(directory)
        shutil.copytree(ROOT / "examples", consumer, dirs_exist_ok=True)
        installed = consumer / archive.name
        installed.write_bytes(original)
        cli = [sys.executable, installed.name]
        ready = json.loads(qualified_run("archive-doctor", [*cli, "doctor"], consumer, out, env, 0))
        scan = json.loads(qualified_run("archive-scan", [*cli, "scan", "--policy", "policy.json"],
                                       consumer, out, env, 2))
        verified = json.loads(qualified_run(
            "archive-verify", [*cli, "verify", "--policy", "policy.json", "--out", "receipt.json"],
            consumer, out, env, 0,
        ))
        if not verified["authoritative"] or verified != json.loads((consumer / "receipt.json").read_text()):
            raise RuntimeError("independent consumer receipt does not match")
        if ready["producer"] != verified["producer"] or scan["producer"] != verified["producer"]:
            raise RuntimeError("producer identity changed across independent invocations")
        rejected = json.loads(qualified_run(
            "archive-output-alias",
            [*cli, "scan", "--policy", "policy.json", "--out", installed.name],
            consumer, out, env, 3,
        ))
        if rejected["observed"]["verdict"] != "Inconclusive" or installed.read_bytes() != original:
            raise RuntimeError("receipt output altered the loaded archive")
        (out / "receipt.json").write_bytes((consumer / "receipt.json").read_bytes())

    result = {
        "status": "Pass", "unitTests": count,
        "nativeSpecimens": len(json.loads((ROOT / "tests" / "native-cases.json").read_text())),
        "archive": archive.name, "archiveSha256": hashlib.sha256(original).hexdigest(),
        "producer": verified["producer"],
        "nativeVersions": {tool["name"]: tool["version"] for tool in verified["nativeTools"]},
        "scanExit": 2, "verifyExit": 0,
    }
    if (ROOT / ".git").exists() and shutil.which("git"):
        head = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True, timeout=5)
        state = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                               capture_output=True, text=True, timeout=5)
        if head.returncode == 0 and state.returncode == 0:
            result["checkout"] = {"commit": head.stdout.strip(), "dirty": bool(state.stdout)}
    (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
