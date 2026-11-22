"""Evidence contract shared by the source Assays. Native inspection is product-specific."""

from __future__ import annotations

import argparse
import hashlib
from importlib.resources import files
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

from . import adapter
from .process import Execution, run

RESOURCE = files(__package__)
RECEIPT = "source-assay-receipt/1"
EXIT = {"Pass": 0, "Fail": 1, "Inconclusive": 2, "ToolFailure": 3}
FILE_LIMIT = 1024 * 1024


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False) + "\n"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def strict_json(data):
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result

    def reject_constant(_):
        raise ValueError("nonfinite JSON number")

    return json.loads(data.decode("utf-8"), object_pairs_hook=unique, parse_constant=reject_constant)


def read_regular(path):
    if any(part.is_symlink() for part in (path, *path.parents)) or not path.is_file():
        raise ValueError("input must be a regular file with no symlink components")
    with path.open("rb") as stream:
        data = stream.read(FILE_LIMIT + 1)
    if len(data) > FILE_LIMIT:
        raise ValueError("input exceeds 1 MiB")
    return data


def policy_paths(names, maximum, key):
    if not isinstance(names, list) or len(names) > maximum:
        raise ValueError(f"{key} must be a bounded array")
    for name in names:
        if not isinstance(name, str) or not name or len(name) > 512 or "\\" in name:
            raise ValueError(f"invalid {key} path")
        if any(ord(char) < 32 for char in name) or any(
            part in ("", ".", "..") for part in name.split("/")
        ):
            raise ValueError(f"{key} requires canonical project-relative paths")
    if len(set(names)) != len(names):
        raise ValueError(f"{key} must be unique")
    return names


def load_policy(data, catalogue):
    value = strict_json(data)
    if not isinstance(value, dict) or set(value) != {
        "schemaVersion", "profile", "sources", "testInputs", "requiredCommands"
    }:
        raise ValueError("policy requires schemaVersion, profile, sources, testInputs, requiredCommands")
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
        raise ValueError("unsupported policy version")
    if value["profile"] != catalogue["profile"]:
        raise ValueError("unsupported profile")

    sources = policy_paths(value["sources"], 32, "sources")
    inputs = policy_paths(value["testInputs"], 64, "testInputs")
    if set(sources).intersection(inputs):
        raise ValueError("source paths are already bound and must not be repeated as testInputs")
    if any(Path(name).suffix.lower() not in catalogue["sourceExtensions"] for name in sources):
        raise ValueError("source extension is outside the profile")

    commands = value["requiredCommands"]
    if not isinstance(commands, list) or len(commands) > 16:
        raise ValueError("requiredCommands must be a bounded array")
    for argv in commands:
        if not isinstance(argv, list) or not 1 <= len(argv) <= 64 or not argv[0] or any(
            not isinstance(arg, str) or "\0" in arg or len(arg) > 4096 for arg in argv
        ):
            raise ValueError("commands require literal executable and argument arrays")
    return value


def fingerprint(executable, additional_files):
    identities = {}
    for file in (executable, *(executable.parent / name for name in additional_files)):
        with file.open("rb") as stream:
            identities[file.name] = hashlib.file_digest(stream, "sha256").hexdigest()
    return identities


def native_environment(scratch):
    return {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.defpath,
        "HOME": str(scratch),
        "XDG_CACHE_HOME": str(scratch / "cache"),
        "XDG_CONFIG_HOME": str(scratch / "config"),
        "TMPDIR": str(scratch),
        "TERM": "dumb",
        "POWERSHELL_TELEMETRY_OPTOUT": "1",
        "POWERSHELL_UPDATECHECK": "Off",
        "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
    }


def observe(policy_file, policy, policy_bytes):
    initial = {policy_file: policy_bytes}
    missing = []
    for name in [*policy["sources"], *policy["testInputs"]]:
        path = policy_file.parent / name
        try:
            initial[path] = read_regular(path)
        except (OSError, ValueError):
            missing.append(f"{name}: declared input unavailable")
    return initial, missing


def producer_files(catalogue):
    return ("__init__.py", "__main__.py", "engine.py", "process.py", "adapter.py", "catalogue.json",
            *catalogue["nativeFiles"])


def producer_hash(catalogue):
    payloads = {name: digest(RESOURCE.joinpath(name).read_bytes()) for name in producer_files(catalogue)}
    return digest(canonical(payloads).encode())


def probe(catalogue, scratch, env):
    paths = {}
    identities = []
    missing = []
    for spec in catalogue["tools"]:
        name = spec["name"]
        executable = shutil.which(name)
        identity = {"name": name, "qualifiedVersion": spec["version"], "status": "unavailable"}
        identities.append(identity)
        if executable is None:
            missing.append(f"{name}: executable unavailable")
            continue
        try:
            path = Path(executable).resolve(strict=True)
            hashes = fingerprint(path, spec.get("identityFiles", []))
        except OSError:
            missing.append(f"{name}: executable identity unavailable")
            continue
        result = run([str(path), *spec["versionArgs"]], scratch, env=env)
        identity["identityFiles"] = hashes
        identity["probe"] = result.evidence()
        match = re.search(spec["versionPattern"], result.stdout.decode("utf-8", errors="replace"))
        if result.unavailable or result.exit_code != 0 or not match:
            missing.append(f"{name}: version probe unavailable")
            continue
        identity["version"] = match[1]
        if match[1] != spec["version"]:
            identity["status"] = "unsupported"
            missing.append(f"{name}: version differs from the qualified baseline")
            continue
        identity["status"] = "qualified"
        paths[name] = path
    return paths, identities, missing


class Inspection:
    def __init__(self, name, contents, rules, paths, scratch, env):
        self.name = name
        self.contents = contents
        self.rules = rules
        self.paths = paths
        self.scratch = scratch
        self.env = env
        self.checks = []
        self.findings = []
        self.gaps = []
        self.failures = []

    def call(self, tool, arguments, exits=(0, 1)) -> Execution | None:
        if tool not in self.paths:
            self.gaps.append(f"{tool}: qualified native evidence unavailable")
            return None
        result = run([str(self.paths[tool]), *arguments], self.scratch, source=self.contents, env=self.env)
        self.checks.append({"tool": tool, "arguments": arguments, **result.evidence()})
        if result.unavailable:
            self.gaps.append(f"{tool}: {result.unavailable}")
            return None
        if result.exit_code not in exits:
            self.failures.append(f"{tool}: unexpected native exit code")
            return None
        return result

    def finding(self, rule_id, line=1, column=1, native_id=None):
        rule = self.rules[rule_id]
        self.findings.append({
            "ruleId": rule_id, "severity": rule["severity"], "message": rule["title"],
            "line": line, "column": column, "nativeId": native_id,
        })

    def report(self):
        return {
            "path": self.name,
            "status": "incomplete" if self.gaps or self.failures else "evaluated",
            "checks": self.checks,
            "findings": sorted(self.findings, key=lambda item: (item["line"], item["column"], item["ruleId"])),
        }


def test_commands(command, policy, root, inputs_available, missing):
    commands = policy["requiredCommands"]
    if not commands:
        missing.append("required behavior commands are absent")
    if commands and not policy["testInputs"]:
        missing.append("required behavior command inputs are undeclared")
    if command == "scan":
        missing.append("scan does not execute required behavior commands")

    tests = []
    for argv in commands:
        if command == "scan" or not inputs_available or not policy["testInputs"] or not policy["sources"]:
            tests.append({"argv": argv, "status": "NotRun"})
            continue
        result = run(argv, root)
        status = "Unavailable" if result.unavailable else ("Pass" if result.exit_code == 0 else "Fail")
        tests.append({"argv": argv, "status": status, **result.evidence()})
    if any(test["status"] in ("NotRun", "Unavailable") for test in tests):
        missing.append("required behavior command evidence incomplete")
    return tests


def audit(command, policy_file, catalogue, producer):
    policy_bytes = read_regular(policy_file)
    policy = load_policy(policy_bytes, catalogue)
    root = policy_file.parent
    initial, missing = observe(policy_file, policy, policy_bytes)
    inputs_available = not missing
    failures = []
    sources = []
    if not policy["sources"]:
        missing.append("source scope is empty")
    rules = {rule["id"]: rule for rule in catalogue["rules"]}
    with tempfile.TemporaryDirectory(prefix="source-assay-") as directory:
        scratch = Path(directory)
        env = native_environment(scratch)
        for name in catalogue["nativeFiles"]:
            (scratch / name).write_bytes(RESOURCE.joinpath(name).read_bytes())
        tools, native, gaps = probe(catalogue, scratch, env)
        missing.extend(gaps)
        for name in sorted(policy["sources"]):
            data = initial.get(root / name)
            target = Inspection(name, data, rules, tools, scratch, env)
            try:
                if data is None:
                    raise ValueError("unavailable source")
                if not data.decode("utf-8").strip() or b"\x00" in data or data.startswith(b"\xef\xbb\xbf"):
                    raise ValueError("unsupported source text")
            except ValueError:
                inputs_available = False
                target.gaps.append("expected nonempty UTF-8 source without a BOM or NUL")
            else:
                adapter.inspect(target)
            sources.append(target.report())
            missing.extend(f"{name}: {reason}" for reason in target.gaps)
            failures.extend(f"{name}: {reason}" for reason in target.failures)

    tests = test_commands(command, policy, root, inputs_available, missing)
    for path, before in initial.items():
        try:
            unchanged = read_regular(path) == before
        except (OSError, ValueError):
            unchanged = False
        if not unchanged:
            missing.append(f"{path.relative_to(root)}: input changed or became unavailable")
    for identity in native:
        name = identity["name"]
        if name in tools:
            spec = next(spec for spec in catalogue["tools"] if spec["name"] == name)
            try:
                unchanged = fingerprint(tools[name], spec.get("identityFiles", [])) == identity["identityFiles"]
            except OSError:
                unchanged = False
            if not unchanged:
                missing.append(f"{name}: native identity changed or became unavailable")
    try:
        unchanged = producer_hash(catalogue) == producer["sha256"]
    except OSError:
        unchanged = False
    if not unchanged:
        missing.append("producer changed or became unavailable")

    blocked = any(
        finding["severity"] == "blocking"
        for source in sources for finding in source["findings"]
    ) or any(test["status"] == "Fail" for test in tests)
    if failures:
        verdict = "ToolFailure"
    elif blocked:
        verdict = "Fail"
    else:
        verdict = "Inconclusive" if missing else "Pass"
    result = {
        "schemaVersion": RECEIPT, "producer": producer, "product": catalogue["product"],
        "command": command, "profile": policy["profile"], "verdict": verdict,
        "authoritative": not (missing or failures), "nativeTools": native,
        "sources": sources, "requiredCommands": tests,
        "missingEvidence": sorted(set(missing)), "toolFailures": sorted(set(failures)),
        "inputs": [
            {"path": path.relative_to(root).as_posix(), "sha256": digest(data)}
            for path, data in sorted(initial.items())
        ],
    }
    protected = [policy_file, *(root / name for name in [*policy["sources"], *policy["testInputs"]])]
    for identity in native:
        if identity["name"] in tools:
            tool = tools[identity["name"]]
            protected.extend(tool.parent / name for name in identity["identityFiles"])
    launched = Path(os.path.abspath(sys.argv[0]))
    if launched.is_file():
        protected.append(launched)
    if isinstance(RESOURCE, Path):
        protected.extend(RESOURCE / name for name in producer_files(catalogue))
    return result, protected


def publish(result, output, inputs):
    if any(part.is_symlink() for part in (output, *output.parents)):
        raise ValueError("receipt output cannot traverse a symlink")
    if output.exists() and (not output.is_file() or output.stat().st_nlink != 1):
        raise ValueError("receipt output must be a single-link regular file")
    if any(output == item or (output.exists() and item.exists() and output.samefile(item)) for item in inputs):
        raise ValueError("receipt output overlaps a declared input")
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as stream:
        staged = Path(stream.name)
        try:
            stream.write(canonical(result).encode())
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()
            staged.replace(output)
        finally:
            staged.unlink(missing_ok=True)


def emit(value):
    print(canonical(value), end="")


def failure(message):
    return {"schemaVersion": RECEIPT, "verdict": "ToolFailure", "authoritative": False, "error": message}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        emit(failure("invalid command line"))
        raise SystemExit(EXIT["ToolFailure"])


def main():
    try:
        catalogue = strict_json(RESOURCE.joinpath("catalogue.json").read_bytes())
        producer = {"name": catalogue["assay"], "version": "0.1.0", "sha256": producer_hash(catalogue)}
        parser = Parser(description=catalogue["assay"] + " bounded source verification")
        commands = parser.add_subparsers(dest="command", required=True)
        commands.add_parser("catalog")
        commands.add_parser("doctor")
        explain = commands.add_parser("explain")
        explain.add_argument("rule")
        for name in ("scan", "verify", "assess"):
            child = commands.add_parser(name)
            child.add_argument("--policy", required=True, type=Path)
            child.add_argument("--out", type=Path)
        args = parser.parse_args()
        if args.command == "catalog":
            emit(catalogue)
            return 0
        if args.command == "explain":
            rule = next((rule for rule in catalogue["rules"] if rule["id"] == args.rule), None)
            emit(rule or failure("unknown rule"))
            return 0 if rule else EXIT["ToolFailure"]
        if args.command == "doctor":
            with tempfile.TemporaryDirectory(prefix="source-assay-doctor-") as directory:
                scratch = Path(directory)
                _, native, missing = probe(catalogue, scratch, native_environment(scratch))
            emit({"producer": producer, "scope": "readiness", "python": sys.version.split()[0],
                  "ready": not missing, "nativeTools": native, "missingEvidence": missing})
            return EXIT["Inconclusive"] if missing else 0

        policy = Path(os.path.abspath(args.policy))
        receipt, inputs = audit(args.command, policy, catalogue, producer)
        result = receipt
        if args.command == "assess":
            result = {"schemaVersion": "source-assay-assessment/1", "verdict": receipt["verdict"],
                      "authoritative": receipt["authoritative"], "receipt": receipt}
        if args.out:
            try:
                publish(result, Path(os.path.abspath(args.out)), inputs)
            except (OSError, ValueError):
                result = {**failure("receipt output could not be written"), "observed": result}
        emit(result)
        return EXIT[result["verdict"]]
    except (KeyError, OSError, RecursionError, TypeError, ValueError):
        emit(failure("invalid policy or unsupported producer input"))
        return EXIT["ToolFailure"]
