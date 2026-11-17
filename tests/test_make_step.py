"""
scripts/make_step.py: the wrapper that gives every make step its semantic context
(purpose, command, context, digest, log file, history), and keeps make's exit codes.
"""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "make_step.py"
sys.path.insert(0, str(SCRIPT.parent))
import make_step  # noqa: E402

MAKEFILE = textwrap.dedent("""\
    ##@ Test tiers (what to run when)

    test-unit: $(STAMP) ## Unit tier: in-process, any socket use fails
    \t@echo unit

    ##@ Housekeeping

    clean: ## Remove caches
    """)


class TestMakefileContext(unittest.TestCase):
    def test_purpose_and_section_come_from_the_makefile(self):
        with tempfile.TemporaryDirectory() as tmp:
            makefile = Path(tmp, "Makefile")
            makefile.write_text(MAKEFILE, encoding="utf-8")
            self.assertEqual(make_step.makefile_target("test-unit", makefile),
                             ("Test tiers (what to run when)", "Unit tier: in-process, any socket use fails"))
            self.assertEqual(make_step.makefile_target("clean", makefile), ("Housekeeping", "Remove caches"))
            self.assertEqual(make_step.makefile_target("missing", makefile), ("", ""))
        self.assertEqual(make_step.makefile_target("x", Path("/nonexistent/Makefile")), ("", ""))

    def test_the_real_makefile_describes_every_wrapped_target(self):
        makefile = SCRIPT.parent.parent / "Makefile"
        text = makefile.read_text(encoding="utf-8")
        import re
        targets = set(re.findall(r"^([a-z][\w-]*):(?!=)", text, re.M))          # targets, not VAR := value
        self.assertGreater(len(targets), 40)
        for target in sorted(targets):
            with self.subTest(target=target):
                self.assertTrue(make_step.makefile_target(target, makefile)[1], f"{target} has no ## description")


class TestDigest(unittest.TestCase):
    def test_known_lines_become_a_digest(self):
        lines = ["============ 312 passed, 79 deselected in 12.31s ============\n",
                 "TOTAL      6410     39   1898     57  98.7%\n",
                 "[!] Quality gate failed (--fail-on error): 4 error(s).\n",
                 "[*] Links proposed             : 16\n",
                 "  [OK] Expected links found: 7/7\n", "  [X] Expected links found: 0/1\n", "  [OK] Expected links found: 4/4\n",
                 "  Site health: 0/10 healthy pages\n", "  Site health: 10/10 healthy pages\n",
                 "report: build/eval/report.md\n", "[+] HTML report: /abs/build/report/audit.html\n",
                 "  corpus-a: links/cold random seed 1 (3.1s)\n", "  corpus-a: ranking random seed 1 (1.0s)\n",
                 "  corpus-b: ranking skipped (no popularity layer)\n",
                 '{"corpus": "a", "task": "crawl", "documents": 3, "crawled": 3, "coverage": 1.0}\n']
        found, outputs = make_step.digest(lines)
        self.assertEqual(found["tests"], "312 passed, 79 deselected in 12.31s")
        self.assertEqual(found["coverage"], "98.7% of src/ covered")
        self.assertEqual(found["quality gate"], "failed (--fail-on error): 4 error(s).")
        self.assertEqual(found["links proposed"], "16")
        self.assertEqual(found["benchmark sites"], "2 found every expected link, 1 with missing or unexpected links")
        self.assertEqual(found["site health (last of 2)"], "10/10 healthy pages")     # repeated values say so
        self.assertEqual(outputs, ["build/eval/report.md", "/abs/build/report/audit.html"])
        self.assertEqual(found["evaluation runs"], "2 (links 1, ranking 1)")             # skipped tasks not counted
        self.assertEqual(found["crawl fidelity"], "1 site(s) at coverage 1.0")

    def test_failure_tail_prefers_explanatory_lines(self):
        lines = [f"line {i}\n" for i in range(50)] + ["E   AssertionError: boom\n", "tail\n"]
        self.assertEqual(make_step.relevant_tail(lines), ["E   AssertionError: boom"])
        self.assertEqual(make_step.relevant_tail(["a\n", "b\n"]), ["a", "b"])


class TestRunStep(unittest.TestCase):
    def _run(self, tmp, *command, extra=(), env=None):
        Path(tmp, "Makefile").write_text(MAKEFILE, encoding="utf-8")
        result = subprocess.run([sys.executable, str(SCRIPT), "--target", "test-unit", *extra, "--", *command],
                                cwd=tmp, capture_output=True, text=True, env=dict(os.environ, **(env or {})))
        return result

    def test_success_frames_the_output_and_records_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp, sys.executable, "-c", "print('=== 3 passed in 0.10s ===')",
                               extra=["--step", "1/2 unit", "--context", "ARGS=-x"], env={"SEO_MAGUS_RUN_ID": "r-42"})
            history = [json.loads(l) for l in Path(tmp, "build/logs/history.jsonl").read_text().splitlines()]
            log = Path(tmp, history[0]["log"]).read_text(encoding="utf-8")
        self.assertEqual(result.returncode, 0)
        out = result.stdout
        self.assertIn("==> make test-unit  [1/2 unit]  (run r-42)", out)
        self.assertIn("purpose : Unit tier: in-process, any socket use fails", out)
        self.assertIn("settings: ARGS=-x", out)
        self.assertIn("<== make test-unit [1/2 unit]: OK in", out)
        self.assertIn("tests           : 3 passed in 0.10s", out)
        self.assertEqual((history[0]["run"], history[0]["exit"], history[0]["digest"]["tests"]),
                         ("r-42", 0, "3 passed in 0.10s"))
        self.assertIn("=== 3 passed in 0.10s ===", log)                   # the full output is in the log file

    def test_failure_keeps_the_exit_code_and_explains(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp, sys.executable, "-c",
                               "import sys; print('FAILED tests/test_x.py::test_y - boom'); sys.exit(3)")
        self.assertEqual(result.returncode, 3)                            # make must stop on it
        self.assertIn("FAILED (exit 3)", result.stdout)
        self.assertIn("| FAILED tests/test_x.py::test_y - boom", result.stdout)
        self.assertIn('hint            : rerun only the failures: make test-unit ARGS="--lf"', result.stdout)

    def test_no_log_mode_and_unknown_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp, sys.executable, "-c", "print('ok')", extra=["--no-log"])
            self.assertFalse(Path(tmp, "build").exists())
            missing = self._run(tmp, "definitely-not-a-command-xyz")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(missing.returncode, 127)
        self.assertIn("could not start", missing.stdout)

    def test_history_and_last(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = subprocess.run([sys.executable, str(SCRIPT), "history"], cwd=tmp, capture_output=True, text=True)
            self._run(tmp, sys.executable, "-c", "print('TOTAL  10  0  100%')")
            history = subprocess.run([sys.executable, str(SCRIPT), "history", "--limit", "5"], cwd=tmp,
                                     capture_output=True, text=True)
            last = subprocess.run([sys.executable, str(SCRIPT), "last"], cwd=tmp, capture_output=True, text=True)
        self.assertIn("No make run recorded yet", empty.stdout)
        self.assertIn("test-unit", history.stdout)
        self.assertIn("coverage: 100% of src/ covered", history.stdout)
        self.assertIn("Last step: make test-unit", last.stdout)
        self.assertIn("TOTAL  10  0  100%", last.stdout)


if __name__ == "__main__":
    unittest.main()
