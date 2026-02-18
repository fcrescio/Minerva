from __future__ import annotations

import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from minerva.tools.runplan_env import UnitLookupError, derive_unit_exports


REPO_ROOT = Path(__file__).resolve().parents[1]


class RunplanEnvTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", "-m", "minerva.tools.runplan_env", *args],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
            env={"PYTHONPATH": str(REPO_ROOT / "src")},
        )

    def test_derive_unit_exports_merges_global_and_unit_values(self) -> None:
        plan = self.tmp_path / "plan.toml"
        plan.write_text(
            textwrap.dedent(
                """
                [global.env]
                only_global = "a"

                [global.paths]
                state_dir = "/global/state"

                [global.options]
                summary_args = "--global-summary"

                [global.action.summarize]
                args = ["--g"]

                [[unit]]
                name = "u"
                schedule = "0 * * * *"
                mode = "hourly"
                actions = ["fetch"]

                [unit.env]
                only_unit = "b"

                [unit.options]
                summary_args = "--unit-summary"

                [unit.action.summarize]
                args = ["--u"]
                """
            ).strip(),
            encoding="utf-8",
        )

        lines = derive_unit_exports(plan, "u")

        self.assertIn("apply_if_unset ONLY_GLOBAL a", lines)
        self.assertIn("apply_if_unset ONLY_UNIT b", lines)
        self.assertIn("apply_if_unset MINERVA_STATE_DIR /global/state", lines)
        self.assertIn("apply_if_unset MINERVA_SUMMARY_ARGS --unit-summary", lines)
        self.assertIn("apply_if_unset MINERVA_ACTION_SUMMARIZE_ARGS '--g --u'", lines)
        self.assertIn("export MINERVA_SELECTED_ACTIONS=fetch", lines)
        self.assertIn("export MINERVA_SELECTED_MODE=hourly", lines)

    def test_derive_unit_exports_missing_unit_raises_lookup_error(self) -> None:
        with self.assertRaises(UnitLookupError):
            derive_unit_exports(self.tmp_path / "missing-plan.toml", "unknown")

    def test_load_unit_validation_error_emits_shell_error_contract(self) -> None:
        plan = self.tmp_path / "bad.toml"
        plan.write_text("[[unit]\nname='oops'", encoding="utf-8")

        result = self._run_cli("load-unit", "--plan", str(plan), "--unit", "oops")

        self.assertEqual(result.returncode, 0)
        self.assertIn("echo 'Run plan validation failed' >&2", result.stdout)
        self.assertIn("exit 2", result.stdout)

    def test_list_validate_and_render_cron_outputs(self) -> None:
        plan = self.tmp_path / "ok.toml"
        plan.write_text(
            textwrap.dedent(
                """
                [[unit]]
                name = "w"
                schedule = "*/5 * * * *"
                actions = ["fetch"]
                """
            ).strip(),
            encoding="utf-8",
        )

        list_result = self._run_cli("list-units", "--plan", str(plan))
        self.assertEqual(list_result.returncode, 0)
        self.assertIn("name\tschedule\tenabled\tmode", list_result.stdout)
        self.assertIn("w\t*/5 * * * *\tTrue\tw", list_result.stdout)

        validate_result = self._run_cli("validate", "--plan", str(plan))
        self.assertEqual(validate_result.returncode, 0)
        self.assertIn("Run plan is valid", validate_result.stdout)

        cron_result = self._run_cli("render-cron", "--plan", str(plan), "--system-cron")
        self.assertEqual(cron_result.returncode, 0)
        self.assertIn("# unit: w", cron_result.stdout)
        self.assertIn("*/5 * * * * root", cron_result.stdout)


if __name__ == "__main__":
    unittest.main()
