from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from minerva.runplan import RunPlan, RunPlanValidationError, render_cron


class RunPlanTests(unittest.TestCase):

    def test_from_toml_parses_valid_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_path = Path(tmpdir) / "plan.toml"
            plan_path.write_text(
                """
[global]
mode = "hourly"

[[unit]]
name = "u"
schedule = "0 * * * *"
actions = ["fetch"]
""".strip(),
                encoding="utf-8",
            )

            plan = RunPlan.from_toml(plan_path)

        self.assertEqual(plan.global_config.mode, "hourly")
        self.assertEqual(len(plan.units), 1)
        self.assertEqual(plan.units[0].name, "u")

    def test_from_toml_invalid_document_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_path = Path(tmpdir) / "bad.toml"
            plan_path.write_text("[[unit]\nname='oops'", encoding="utf-8")

            with self.assertRaises(Exception):
                RunPlan.from_toml(plan_path)

    def test_merge_semantics_scalars_lists_and_tokens(self) -> None:
        plan = RunPlan.from_mapping(
            {
                "global": {
                    "mode": "hourly",
                    "args": ["--global"],
                    "actions": ["fetch"],
                    "tokens": {"openrouter": "global-token"},
                    "secrets": {"telegram": "global-secret"},
                    "action": {"fetch": {"args": ["--global-fetch"]}},
                },
                "unit": [
                    {
                        "name": "u1",
                        "schedule": "0 * * * *",
                        "mode": "daily",
                        "args": ["--unit"],
                        "actions": ["summarize"],
                        "tokens": {"openrouter": "unit-token"},
                        "secrets": {"chat": "unit-secret"},
                        "action": {"fetch": {"args": ["--unit-fetch"]}},
                    }
                ],
            },
            file_path="plan.toml",
        )

        merged = plan.merged_unit(plan.units[0])
        self.assertEqual(merged.mode, "daily")
        self.assertEqual(merged.args, ["--global", "--unit"])
        self.assertEqual(merged.actions, ["fetch", "summarize"])
        self.assertEqual(merged.tokens["openrouter"], "unit-token")
        self.assertEqual(merged.secrets["telegram"], "global-secret")
        self.assertEqual(merged.secrets["chat"], "unit-secret")
        self.assertEqual(merged.action_args["fetch"], ["--global-fetch", "--unit-fetch"])


    def test_action_args_parse_and_merge_with_unit_only_action(self) -> None:
        plan = RunPlan.from_mapping(
            {
                "global": {
                    "actions": ["fetch"],
                    "action": {"fetch": {"args": ["--global"]}},
                },
                "unit": [
                    {
                        "name": "u2",
                        "schedule": "0 * * * *",
                        "actions": ["summarize"],
                        "action": {
                            "fetch": {"args": ["--unit"]},
                            "summarize": {"args": ["--provider", "openrouter"]},
                        },
                    }
                ],
            }
        )

        merged = plan.merged_unit(plan.units[0])
        self.assertEqual(merged.action_args["fetch"], ["--global", "--unit"])
        self.assertEqual(merged.action_args["summarize"], ["--provider", "openrouter"])


    def test_actions_and_action_args_accept_summarise_alias(self) -> None:
        plan = RunPlan.from_mapping(
            {
                "global": {
                    "actions": ["summarise"],
                    "action": {"summarise": {"args": ["--global"]}},
                },
                "unit": [
                    {
                        "name": "u3",
                        "schedule": "0 * * * *",
                        "actions": ["summarize"],
                        "action": {"summarise": {"args": ["--unit"]}},
                    }
                ],
            }
        )

        merged = plan.merged_unit(plan.units[0])
        self.assertEqual(merged.actions, ["summarize", "summarize"])
        self.assertEqual(merged.action_args["summarize"], ["--global", "--unit"])

    def test_duplicate_unit_name_validation(self) -> None:
        with self.assertRaises(RunPlanValidationError) as ctx:
            RunPlan.from_mapping(
                {
                    "unit": [
                        {"name": "dup", "schedule": "0 * * * *", "actions": ["a"]},
                        {"name": "dup", "schedule": "5 * * * *", "actions": ["b"]},
                    ]
                },
                file_path="/tmp/plan.toml",
            )

        self.assertIn("/tmp/plan.toml", str(ctx.exception))
        self.assertIn("unit='dup'", str(ctx.exception))
        self.assertIn("key='name'", str(ctx.exception))

    def test_invalid_cron_and_empty_actions_validation(self) -> None:
        with self.assertRaises(RunPlanValidationError) as ctx:
            RunPlan.from_mapping(
                {
                    "unit": [
                        {
                            "name": "broken",
                            "schedule": "* * *",
                            "actions": [],
                        }
                    ]
                },
                file_path="/tmp/plan.toml",
            )

        message = str(ctx.exception)
        self.assertIn("key='schedule'", message)
        self.assertIn("key='actions'", message)

    def test_render_cron_quotes_values_and_adds_unit_comment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_path = Path(tmpdir) / "plan with spaces.toml"
            plan_path.write_text(
                """
[[unit]]
name = "team alpha"
schedule = "*/5 * * * *"
actions = ["fetch"]
""".strip()
            )

            cron = render_cron(plan_path, system_cron=True)

        self.assertIn("# unit: team alpha", cron)
        self.assertIn("minerva-run unit 'team alpha' --plan ", cron)
        self.assertIn("plan with spaces.toml'", cron)
        self.assertIn("*/5 * * * * root", cron)

    def test_render_cron_user_crontab_omits_root(self) -> None:
        cron = render_cron("/tmp/plan.toml", system_cron=False)
        self.assertIn("0 * * * * /usr/local/bin/minerva-run unit hourly --plan /tmp/plan.toml", cron)
        self.assertNotIn(" root /usr/local/bin/minerva-run", cron)


if __name__ == "__main__":
    unittest.main()
