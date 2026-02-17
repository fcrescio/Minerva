from __future__ import annotations

import unittest

from minerva.runplan import RunPlan, RunPlanValidationError


class RunPlanTests(unittest.TestCase):
    def test_merge_semantics_scalars_lists_and_tokens(self) -> None:
        plan = RunPlan.from_mapping(
            {
                "global": {
                    "mode": "hourly",
                    "args": ["--global"],
                    "actions": ["fetch"],
                    "tokens": {"openrouter": "global-token"},
                    "secrets": {"telegram": "global-secret"},
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


if __name__ == "__main__":
    unittest.main()
