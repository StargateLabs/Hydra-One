"""Declarative update policy: every app says how it may update, what proves it, and what is preserved."""
import unittest

from serve.update_policy import (
    POLICIES,
    PRESERVED_PATHS,
    assert_preserved,
    policy_for,
    policy_summary,
)


class UpdatePolicyTests(unittest.TestCase):
    PROTECTED = (
        "pytorch", "strata", "transformers", "unsloth", "soup", "whisper.cpp",
        "browser", "hermes", "environment:Strata", "environment:Unsloth",
        "environment:AirLLM", "environment:Audio generativo", "environment:Open WebUI",
        "environment:Visuale", "runtime:node", "runtime:uv", "runtime:git", "runtime:npm",
    )

    def test_every_protected_app_has_a_policy(self):
        for identifier in self.PROTECTED:
            with self.subTest(identifier=identifier):
                policy = policy_for(identifier)
                self.assertEqual(policy.id, identifier)

    def test_explicitly_blocked_apps_are_not_automatic(self):
        for identifier in ("pytorch", "strata", "transformers", "unsloth", "soup",
                           "runtime:node", "runtime:git", "runtime:npm"):
            with self.subTest(identifier=identifier):
                self.assertFalse(policy_for(identifier).automatic)

    def test_vendor_environments_allow_only_safe_leaves(self):
        for identifier in ("environment:Strata", "environment:Unsloth", "environment:AirLLM",
                           "environment:Audio generativo", "environment:Open WebUI",
                           "environment:Visuale"):
            with self.subTest(identifier=identifier):
                policy = policy_for(identifier)
                self.assertTrue(policy.safe_leaf_only)
                self.assertTrue(policy.reason)

    def test_unknown_component_fails_closed(self):
        policy = policy_for("something-new")
        self.assertFalse(policy.automatic)
        self.assertEqual(policy.reason, "unknown_component_policy")
        self.assertEqual(policy.validation, "explicit")

    def test_preserved_paths_are_the_hydra_and_user_boundary(self):
        self.assertEqual(PRESERVED_PATHS, ("mods", "HYDRA", "data"))
        for path in ("mods/serve/update_center.py", "HYDRA/recovery/assets.zip",
                     "data/automatic-updates.json"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                assert_preserved([path])

    def test_preserved_path_check_allows_live_app_files(self):
        assert_preserved(["serve/server.py", "output/updates/candidates/x", "tools/hip/table.txt"])

    def test_preserved_path_check_rejects_escapes_and_absolute_paths(self):
        for path in ("../mods/x", "/mods/x", "C:/mods/x", "mods/../serve/server.py"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                assert_preserved([path])

    def test_summary_exposes_every_policy(self):
        rows = policy_summary()
        self.assertEqual(len(rows), len(POLICIES))
        self.assertTrue(any(row["id"] == "strata" and row["automatic"] is False for row in rows))
        self.assertTrue(all("preserve" in row for row in rows))


if __name__ == "__main__":
    unittest.main()
