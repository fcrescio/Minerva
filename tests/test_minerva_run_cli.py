from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "docker" / "minerva-run.sh"


class MinervaRunCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.bin_dir = self.tmp_path / "bin"
        self.bin_dir.mkdir()
        self.data_dir = self.tmp_path / "data"
        self.data_dir.mkdir()
        prompts_dir = self.data_dir / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "hourly.txt").write_text("hourly prompt", encoding="utf-8")
        (prompts_dir / "daily.txt").write_text("daily prompt", encoding="utf-8")

        self.log_file = self.tmp_path / "calls.log"
        self.run_log_file = self.tmp_path / "run.log"

        self._write_mock_tool("fetch-todos")
        self._write_mock_tool("summarize-todos")
        self._write_mock_tool("publish-summary")
        self._write_mock_tool("generate-podcast")

        self.base_env = os.environ.copy()
        self.base_env["PATH"] = f"{self.bin_dir}:{self.base_env.get('PATH', '')}"
        self.base_env["PYTHONPATH"] = str(REPO_ROOT / "src")
        self.base_env["MINERVA_DATA_DIR"] = str(self.data_dir)
        self.base_env["MINERVA_LOG_PATH"] = str(self.run_log_file)
        self.base_env["TEST_LOG_FILE"] = str(self.log_file)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_mock_tool(self, name: str) -> None:
        script = textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            printf '%s|%s\\n' '{name}' "$*" >> "$TEST_LOG_FILE"

            output=''
            speech_output=''
            topic_file=''
            while [[ $# -gt 0 ]]; do
              case "$1" in
                --output)
                  output="$2"
                  shift 2
                  ;;
                --speech-output)
                  speech_output="$2"
                  shift 2
                  ;;
                --topic-history-file)
                  topic_file="$2"
                  shift 2
                  ;;
                *)
                  shift
                  ;;
              esac
            done

            if [[ '{name}' == 'fetch-todos' && "${{MOCK_DISABLE_FETCH_OUTPUT:-0}}" == '1' ]]; then
              exit 0
            fi

            for path in "$output" "$speech_output" "$topic_file"; do
              if [[ -n "$path" ]]; then
                mkdir -p "$(dirname "$path")"
                : > "$path"
              fi
            done
            """
        )
        path = self.bin_dir / name
        path.write_text(script, encoding="utf-8")
        path.chmod(0o755)

    def _run(self, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        run_env = dict(self.base_env)
        if env:
            run_env.update(env)
        return subprocess.run(
            ["bash", str(SCRIPT), *args],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            env=run_env,
            check=False,
        )

    def test_validate_command_valid_and_invalid_toml(self) -> None:
        plan = self.tmp_path / "plan.toml"
        plan.write_text(
            textwrap.dedent(
                """
                [[unit]]
                name = "hourly"
                schedule = "0 * * * *"
                actions = ["fetch"]
                """
            ).strip(),
            encoding="utf-8",
        )
        result = self._run("validate", "--plan", str(plan))
        self.assertEqual(result.returncode, 0)
        self.assertIn("Run plan is valid", result.stdout)

        bad = self.tmp_path / "bad.toml"
        bad.write_text("[[unit]\nname='oops'", encoding="utf-8")
        bad_result = self._run("validate", "--plan", str(bad))
        self.assertNotEqual(bad_result.returncode, 0)
        self.assertIn("TOML", bad_result.stderr)

    def test_render_cron_command(self) -> None:
        plan = self.tmp_path / "cron-plan.toml"
        plan.write_text(
            textwrap.dedent(
                """
                [[unit]]
                name = "worker one"
                schedule = "*/10 * * * *"
                actions = ["fetch"]
                """
            ).strip(),
            encoding="utf-8",
        )

        result = self._run("render-cron", "--plan", str(plan), "--system-cron")
        self.assertEqual(result.returncode, 0)
        self.assertIn("# unit: worker one", result.stdout)
        self.assertIn("*/10 * * * * root", result.stdout)

    def test_unit_command_construction_and_override_args(self) -> None:
        plan = self.tmp_path / "unit-plan.toml"
        plan.write_text(
            textwrap.dedent(
                """
                [global]
                mode = "hourly"
                actions = ["fetch", "summarize", "publish"]

                [global.action.summarize]
                args = ["--global-action"]

                [[unit]]
                name = "u"
                schedule = "0 * * * *"
                action = { summarize = { args = ["--unit-action"] } }
                """
            ).strip(),
            encoding="utf-8",
        )

        result = self._run("unit", "u", "--plan", str(plan), "--", "--cli-override")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        calls = self.log_file.read_text(encoding="utf-8")
        self.assertIn("fetch-todos|", calls)
        self.assertIn("summarize-todos|", calls)
        self.assertIn("publish-summary|", calls)
        self.assertIn("--cli-override", calls)

    def test_default_plan_hourly_and_daily_regression(self) -> None:
        missing_plan = self.tmp_path / "does-not-exist.toml"

        hourly = self._run("hourly", "--plan", str(missing_plan))
        self.assertEqual(hourly.returncode, 0, msg=hourly.stderr)
        daily = self._run("daily", "--plan", str(missing_plan))
        self.assertEqual(daily.returncode, 0, msg=daily.stderr)

        lines = [line for line in self.log_file.read_text(encoding="utf-8").splitlines() if line]
        first_hourly = [line.split("|", 1)[0] for line in lines[:3]]
        self.assertEqual(first_hourly, ["fetch-todos", "summarize-todos", "publish-summary"])
        self.assertIn("generate-podcast", [line.split("|", 1)[0] for line in lines])

    def test_action_order_and_prerequisite_skip(self) -> None:
        plan = self.tmp_path / "skip-plan.toml"
        plan.write_text(
            textwrap.dedent(
                """
                [[unit]]
                name = "skip"
                schedule = "0 * * * *"
                actions = ["fetch", "summarize", "publish"]
                """
            ).strip(),
            encoding="utf-8",
        )

        result = self._run("unit", "skip", "--plan", str(plan), env={"MOCK_DISABLE_FETCH_OUTPUT": "1"})
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        run_log = self.run_log_file.read_text(encoding="utf-8")
        self.assertIn("Todo dump not created; skipping downstream actions", run_log)
        calls = self.log_file.read_text(encoding="utf-8")
        self.assertIn("fetch-todos|", calls)
        self.assertNotIn("summarize-todos|", calls)
        self.assertNotIn("publish-summary|", calls)


if __name__ == "__main__":
    unittest.main()
