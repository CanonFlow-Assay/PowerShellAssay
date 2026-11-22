from pathlib import Path
import subprocess
import unittest


class SampleWorker(unittest.TestCase):
    def invoke(self, label):
        return subprocess.run(
            ["pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-File", "./Invoke-SampleWorker.ps1",
             "-WorkerPath", str(Path("sample worker.py").resolve()), "-Label", label],
            capture_output=True, text=True, timeout=10,
        )

    def test_preserves_words_in_paths_and_arguments(self):
        result = self.invoke("two words")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "two words\n")

    def test_preserves_the_exact_native_failure_code(self):
        result = self.invoke("reject")
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(result.stdout, "reject\n")


if __name__ == "__main__":
    unittest.main()
