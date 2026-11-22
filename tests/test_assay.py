"""Contract, process and native-engine acceptance controls."""

import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "src").resolve()
PACKAGE, = (path.name for path in SOURCE.iterdir() if (path / "engine.py").is_file())
CATALOGUE = json.loads((SOURCE / PACKAGE / "catalogue.json").read_text())
EXAMPLES = ROOT / "examples"
sys.path.insert(0, str(SOURCE))
PROCESSES = importlib.import_module(f"{PACKAGE}.process")


class CommandBounds(unittest.TestCase):
    def test_literal_arguments_and_separate_streams(self):
        with tempfile.TemporaryDirectory() as folder:
            command = [sys.executable, "-c", "import sys; print(sys.argv[1]); print('diagnostic', file=sys.stderr)",
                       "x y; printf literal"]
            result = PROCESSES.run(command, Path(folder))
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.stdout, b"x y; printf literal\n")
        self.assertEqual(result.stderr, b"diagnostic\n")

    def test_deadline(self):
        with tempfile.TemporaryDirectory() as folder:
            result = PROCESSES.run(
                [sys.executable, "-c", "import time; time.sleep(5)"], Path(folder), timeout=0.1,
            )
        self.assertEqual(result.unavailable, "deadline exceeded")

    def test_output_bound_across_streams(self):
        with tempfile.TemporaryDirectory() as folder:
            result = PROCESSES.run(
                [sys.executable, "-c", "import sys; print('x' * 200); print('y' * 200, file=sys.stderr)"],
                Path(folder), output_limit=128,
            )
        self.assertEqual(result.unavailable, "output limit exceeded")
        self.assertEqual(len(result.stdout) + len(result.stderr), 129)

    def test_failing_executable_exit_is_retained(self):
        with tempfile.TemporaryDirectory() as folder:
            result = PROCESSES.run([sys.executable, "-c", "raise SystemExit(7)"], Path(folder))
        self.assertEqual(result.exit_code, 7)
        self.assertIsNone(result.unavailable)


class ConsumerFixture:
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.cwd = Path(self.workspace.name)
        shutil.copytree(EXAMPLES, self.cwd, dirs_exist_ok=True)
        self.policy = json.loads((self.cwd / "policy.json").read_text())
        self.source_name = self.policy["sources"][0]

    def invoke(self, command, expected, *, env=None, options=()):
        child_env = dict(os.environ if env is None else env, PYTHONPATH=str(SOURCE))
        argv = [sys.executable, "-m", PACKAGE, command]
        if command in {"scan", "verify", "assess"}:
            argv += ["--policy", "policy.json"]
        completed = subprocess.run(
            [*argv, *options], cwd=self.cwd, env=child_env, capture_output=True, timeout=90,
        )
        self.assertEqual(completed.returncode, expected, (completed.stdout, completed.stderr))
        return json.loads(completed.stdout)

    def save_policy(self):
        (self.cwd / "policy.json").write_text(json.dumps(self.policy))

    def controlled_command(self, body):
        self.policy["requiredCommands"] = [[sys.executable, "-c", body]]
        self.save_policy()


class SourceAssay(ConsumerFixture, unittest.TestCase):
    def test_qualified_native_tools(self):
        receipt = self.invoke("doctor", 0)
        self.assertTrue(receipt["ready"])
        self.assertTrue(all(item["status"] == "qualified" for item in receipt["nativeTools"]))

    def test_catalogue_can_explain_every_rule(self):
        receipt = self.invoke("catalog", 0)
        self.assertEqual(receipt, CATALOGUE)
        for rule in receipt["rules"]:
            with self.subTest(rule=rule["id"]):
                self.assertEqual(self.invoke("explain", 0, options=[rule["id"]]), rule)

    def test_example_uses_real_behavior_and_native_checks(self):
        receipt = self.invoke("verify", 0)
        self.assertTrue(receipt["authoritative"])
        self.assertEqual(receipt["requiredCommands"][0]["status"], "Pass")
        self.assertTrue(receipt["sources"][0]["checks"])
        self.assertFalse(receipt["sources"][0]["findings"])
        self.assertEqual(set(row["path"] for row in receipt["inputs"]),
                         {"policy.json", *self.policy["sources"], *self.policy["testInputs"]})

    def test_native_fixtures(self):
        specimens = json.loads((ROOT / "tests" / "native-cases.json").read_text())
        expected_rules = {rule["id"] for rule in CATALOGUE["rules"]}
        self.assertEqual(expected_rules, {case["rule"] for case in specimens if "rule" in case})
        for case in specimens:
            with self.subTest(name=case["name"]):
                (self.cwd / self.source_name).write_text(case["source"])
                receipt = self.invoke("scan", case["exit"])
                findings = receipt["sources"][0]["findings"]
                if case.get("rule"):
                    self.assertIn(case["rule"], {item["ruleId"] for item in findings})
                else:
                    self.assertFalse(findings)
                if "lastCheck" in case:
                    observed = receipt["sources"][0]["checks"]
                    self.assertEqual(observed[-1]["arguments"][-1], case["lastCheck"])
                if case.get("requiredGap"):
                    self.assertTrue(any(case["requiredGap"] in gap for gap in receipt["missingEvidence"]))
                if case.get("guardBeforeNative"):
                    self.assertEqual(receipt["sources"][0]["checks"], [])

    def test_scan_does_not_run_behavior_commands(self):
        marker = self.cwd / "required-ran"
        self.controlled_command("from pathlib import Path; Path('required-ran').touch()")
        first = self.invoke("scan", 2)
        second = self.invoke("scan", 2)
        self.assertEqual(first, second)
        self.assertFalse(marker.exists())
        self.assertEqual(first["requiredCommands"][0]["status"], "NotRun")

    def test_failed_behavior_survives_missing_static_evidence(self):
        self.controlled_command("raise SystemExit(7)")
        receipt = self.invoke("verify", 1, env=dict(os.environ, PATH="/no-native-tool-bin"))
        self.assertFalse(receipt["authoritative"])
        self.assertEqual(receipt["requiredCommands"][0]["exitCode"], 7)
        self.assertTrue(receipt["missingEvidence"])

    def test_missing_behavior_is_inconclusive(self):
        self.policy["requiredCommands"] = []
        self.save_policy()
        self.assertIn("required behavior commands are absent", self.invoke("verify", 2)["missingEvidence"])

    def test_unavailable_command_is_inconclusive(self):
        self.policy["requiredCommands"] = [["./unavailable-command"]]
        self.save_policy()
        receipt = self.invoke("verify", 2)
        self.assertEqual(receipt["requiredCommands"][0]["status"], "Unavailable")

    def test_empty_scope_and_missing_file_are_distinct(self):
        (self.cwd / self.source_name).unlink()
        missing = self.invoke("verify", 2)
        self.assertEqual(missing["sources"][0]["status"], "incomplete")
        self.policy["sources"] = []
        self.save_policy()
        empty = self.invoke("verify", 2)
        self.assertIn("source scope is empty", empty["missingEvidence"])
        self.assertEqual(empty["sources"], [])

    def test_unsupported_utf8_and_symlink_scope(self):
        self.controlled_command("raise SystemExit(0)")
        source = self.cwd / self.source_name
        source.write_bytes(b"\xff")
        invalid = self.invoke("verify", 2)
        self.assertEqual(invalid["sources"][0]["status"], "incomplete")
        self.assertEqual(invalid["requiredCommands"][0]["status"], "NotRun")
        other = source.with_suffix(".other")
        source.rename(other)
        source.symlink_to(other)
        receipt = self.invoke("verify", 2)
        self.assertFalse(any(item["path"] == self.source_name for item in receipt["inputs"]))
        self.assertEqual(receipt["requiredCommands"][0]["status"], "NotRun")

    def test_behavior_command_changing_input_invalidates_receipt(self):
        self.controlled_command(f"from pathlib import Path; p = Path({self.source_name!r}); p.write_bytes(p.read_bytes() + b'\\n')")
        receipt = self.invoke("verify", 2)
        self.assertEqual(receipt["requiredCommands"][0]["status"], "Pass")
        self.assertIn(f"{self.source_name}: input changed or became unavailable", receipt["missingEvidence"])

    def test_invalid_policy_fails_closed(self):
        policy_path = self.cwd / "policy.json"
        policy_path.write_text('{"schemaVersion": 1, "schemaVersion": 1}')
        self.invoke("verify", 3)
        self.policy["sources"] = [f"../{self.source_name}"]
        self.save_policy()
        self.invoke("verify", 3)
        self.policy["sources"] = [self.source_name]
        self.policy["requiredCommands"] = ["echo not an argument array"]
        self.save_policy()
        self.invoke("verify", 3)

    def test_assessment_preserves_receipt_and_publication_failure(self):
        result = self.invoke("assess", 0, options=["--out", "report.json"])
        self.assertEqual(result, json.loads((self.cwd / "report.json").read_text()))
        self.assertEqual(result["receipt"]["verdict"], "Pass")
        original = (self.cwd / "policy.json").read_bytes()
        failed = self.invoke("scan", 3, options=["--out", "policy.json"])
        self.assertEqual(failed["observed"]["verdict"], "Inconclusive")
        self.assertEqual(original, (self.cwd / "policy.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
