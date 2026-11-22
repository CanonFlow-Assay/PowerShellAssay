"""Native source is data while scanning a declared file."""

import unittest

import test_assay


class StaticExecutionBoundary(test_assay.ConsumerFixture, unittest.TestCase):
    def test_inspection_never_executes_the_target_script(self):
        marker = self.cwd / "script-executed"
        (self.cwd / self.source_name).write_text(f"[System.IO.File]::WriteAllText('{marker}', 'exercised')\n")
        receipt = self.invoke("scan", 2)
        self.assertTrue(receipt["sources"][0]["checks"])
        self.assertFalse(marker.exists())
