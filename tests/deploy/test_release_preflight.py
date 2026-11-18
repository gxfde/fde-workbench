"""Public CLI tests; isolated real Git repositories, no application imports."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

CLI = Path(__file__).resolve().parents[2] / "scripts/deploy/release_preflight.py"


class ReleasePreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fde-preflight-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_TERMINAL_PROMPT="0")
        self.git("init", "--quiet")
        self.git("config", "user.name", "fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "core.autocrlf", "false")
        self.git("config", "core.hooksPath", str(self.root / "no-hooks"))
        for name in ("compose.yaml", "server/Dockerfile", "server/requirements.lock",
                     "server/pyproject.toml", "server/alembic.ini", "server/migrations/env.py"):
            self.write(name, "# synthetic input\n")
        self.write("server/alembic.ini", "[alembic]\nscript_location = migrations\n")
        self.write(".gitignore", ".env\n")
        self.migration("one", "one", None)
        self.migration("two", "two", "one")
        self.commit()

    def write(self, name, text):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))

    def migration(self, filename, revision, parent):
        self.write(f"server/migrations/versions/{filename}.py",
                   f"revision = {revision!r}\ndown_revision = {parent!r}\n"
                   "branch_labels = None\ndepends_on = None\n")

    def git(self, *args):
        proc = subprocess.run(["git", "-C", str(self.root), *args], env=self.env,
                              capture_output=True, text=True, timeout=20)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout.strip()

    def commit(self):
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "synthetic fixture")
        self.head = self.git("rev-parse", "HEAD")

    def check(self, expected=None, tree=None, extra=()):
        proc = subprocess.run([sys.executable, str(CLI), "--tree", str(tree or self.root),
                               "--expected-commit", expected or self.head, *extra],
                              env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.stderr, "", proc.stderr)
        return proc.returncode, json.loads(proc.stdout)

    def test_clean_matching_single_head_candidate(self):
        code, data = self.check()
        self.assertEqual(code, 0, data)
        self.assertEqual(data["status"], "candidate_consistent")
        self.assertEqual(data["live_status"], "not_checked")
        self.assertEqual(data["observed_commit"], self.head)
        self.assertEqual(data["migration_heads"], ["two"])
        self.assertEqual(data["errors"], [])
        self.assertEqual(data["input_sha256"]["compose.yaml"],
                         "e3e11e0feb192233452ccc2efab76fe4014f30f69c2f9c9923324e1a451c33b2")


    def rejected(self, expected_code, *, exit_code=1, **kwargs):
        code, data = self.check(**kwargs)
        self.assertEqual(code, exit_code, data)
        self.assertEqual(data["status"], "rejected")
        self.assertEqual(data["errors"], [expected_code])
        self.assertEqual(data["input_sha256"], {})
        self.assertEqual(data["live_status"], "not_checked")
        return data

    def test_wrong_external_commit(self):
        self.rejected("commit_mismatch", expected="0" * 40)

    def test_unstaged_change(self):
        self.write("compose.yaml", "changed\n")
        self.rejected("dirty_tree")

    def test_staged_change(self):
        self.write("compose.yaml", "changed\n")
        self.git("add", "compose.yaml")
        self.rejected("dirty_tree")

    def test_untracked_change(self):
        self.write("unexpected.txt", "untracked\n")
        self.rejected("dirty_tree")

    def test_ignored_secret_never_in_report(self):
        self.write(".env", "SYNTHETIC_SENTINEL_NOT_A_CREDENTIAL")
        code, data = self.check()
        self.assertEqual(code, 0, data)
        self.assertNotIn("SYNTHETIC_SENTINEL", json.dumps(data))
        self.assertNotIn(".env", data["input_sha256"])

    def test_missing_parent(self):
        self.migration("two", "two", "absent")
        self.commit()
        self.rejected("missing_migration_parent")

    def test_duplicate_revision(self):
        self.migration("three", "two", "one")
        self.commit()
        self.rejected("duplicate_migration_revision")

    def test_multiple_heads_then_merge(self):
        self.migration("three", "three", "one")
        self.commit()
        self.rejected("migration_head_count")
        self.migration("merge", "merged", ("two", "three"))
        self.commit()
        code, data = self.check()
        self.assertEqual(code, 0, data)
        self.assertEqual(data["migration_heads"], ["merged"])

    def test_disconnected_cycle_even_with_one_valid_head(self):
        self.migration("cycle_a", "cycle_a", "cycle_b")
        self.migration("cycle_b", "cycle_b", "cycle_a")
        self.commit()
        self.rejected("migration_cycle")

    def test_metadata_expression_not_executed_or_disclosed(self):
        self.write("server/migrations/versions/two.py",
                   "revision = secret('SYNTHETIC_SECRET')\ndown_revision = 'one'\n")
        self.commit()
        data = self.rejected("invalid_migration_metadata")
        self.assertNotIn("SYNTHETIC_SECRET", json.dumps(data))

    def test_migration_body_not_executed(self):
        target = self.root / "executed.txt"
        self.write("server/migrations/versions/two.py",
                   "revision: str = 'two'\ndown_revision = 'one'\n"
                   f"def upgrade():\n    open({str(target)!r}, 'w').write('not allowed')\n")
        self.commit()
        code, data = self.check()
        self.assertEqual(code, 0, data)
        self.assertFalse(target.exists())

    def test_nonliteral_dependency_is_not_silently_ignored(self):
        self.write("server/migrations/versions/two.py",
                   "revision='two'\ndown_revision='one'\ndepends_on='one'\n")
        self.commit()
        self.rejected("unsupported_migration_metadata")

    def test_duplicate_metadata_assignment(self):
        self.write("server/migrations/versions/two.py",
                   "revision='two'\ndown_revision='one'\nrevision='other'\n")
        self.commit()
        self.rejected("duplicate_metadata")

    def test_missing_required_input(self):
        self.git("rm", "server/requirements.lock")
        self.commit()
        self.rejected("untracked_input")

    def test_non_root_directory(self):
        self.rejected("not_repository_root", exit_code=2, tree=self.root / "server")

    def test_invalid_expected_commit_is_not_echoed(self):
        data = self.rejected("invalid_expected_commit", exit_code=2,
                             expected="SYNTHETIC_SECRET_ARGUMENT")
        self.assertNotIn("SYNTHETIC_SECRET_ARGUMENT", json.dumps(data))

    def test_unknown_argument_is_structured_and_redacted(self):
        data = self.rejected("invalid_arguments", exit_code=2,
                             extra=("--unknown", "SYNTHETIC_SECRET_ARGUMENT"))
        self.assertNotIn("SYNTHETIC_SECRET_ARGUMENT", json.dumps(data))

    def test_assume_unchanged_cannot_hide_change(self):
        self.git("update-index", "--assume-unchanged", "compose.yaml")
        self.write("compose.yaml", "hidden change\n")
        self.rejected("hidden_index_changes")

    def test_skip_worktree_cannot_hide_change(self):
        self.git("update-index", "--skip-worktree", "compose.yaml")
        self.write("compose.yaml", "hidden change\n")
        self.rejected("hidden_index_changes")

    def test_hardlinked_input_rejected(self):
        source = self.root / "source.txt"
        source.write_bytes(b"# synthetic input\n")
        target = self.root / "compose.yaml"
        target.unlink()
        os.link(source, target)
        self.commit()
        self.rejected("linked_input")

    def test_no_migrations_rejected(self):
        self.git("rm", "-r", "server/migrations/versions")
        self.commit()
        self.rejected("missing_migrations")

    def test_git_filters_not_executed(self):
        marker = self.root / "filter-executed.txt"
        self.write(".gitattributes", "compose.yaml filter=sentinel\n")
        self.commit()
        self.git("config", "filter.sentinel.clean", f'echo BAD > "{marker.as_posix()}"')
        self.write("compose.yaml", "changed to force clean filter\n")
        self.rejected("unsafe_git_filters", exit_code=2)
        self.assertFalse(marker.exists())



    def test_conditional_metadata_reassignment_rejected(self):
        self.write("server/migrations/versions/two.py",
                   "revision='two'\ndown_revision='one'\n"
                   "if True:\n    down_revision='missing'\n")
        self.commit()
        self.rejected("unsupported_migration_metadata")

    def test_augmented_metadata_assignment_rejected(self):
        self.write("server/migrations/versions/two.py",
                   "revision='two'\ndown_revision='one'\nrevision += '_changed'\n")
        self.commit()
        self.rejected("unsupported_migration_metadata")

    def test_submodule_cannot_load_another_repository_configuration(self):
        self.git("update-index", "--add", "--cacheinfo", f"160000,{self.head},nested")
        self.git("commit", "--quiet", "-m", "synthetic gitlink")
        self.head = self.git("rev-parse", "HEAD")
        self.rejected("unsupported_submodules", exit_code=2)

    def test_git_missing_returns_safe_error(self):
        self.env["PATH"] = str(self.root / "empty-path")
        self.rejected("git_unavailable", exit_code=2)

    def test_replace_objects_cannot_disguise_different_tree(self):
        original = self.head
        self.write("compose.yaml", "different committed input\n")
        self.commit()
        replacement = self.head
        self.git("replace", original, replacement)
        self.git("update-ref", "HEAD", original)
        self.rejected("dirty_tree", expected=original)

    def test_nested_merge_cannot_hide_top_level_heads(self):
        self.migration("three", "three", "one")
        self.migration("nested/merge", "merge", ("two", "three"))
        self.commit()
        self.rejected("unsupported_nested_migrations")

    def test_alembic_alternate_loading_configuration_rejected(self):
        for setting in ("script_location = elsewhere", "version_locations = other",
                        "recursive_version_locations = true", "sourceless = true"):
            with self.subTest(setting=setting):
                base = "[alembic]\n"
                if not setting.startswith("script_location"):
                    base += "script_location = migrations\n"
                self.write("server/alembic.ini", base + setting + "\n")
                self.commit()
                self.rejected("unsupported_alembic_configuration")

    def test_promisor_configuration_never_invokes_transport(self):
        marker = self.root / "transport-executed.txt"
        self.git("config", "core.sshCommand", f'echo BAD > "{marker.as_posix()}"')
        self.git("config", "remote.sentinel.url", "ssh://example.invalid/synthetic")
        self.git("config", "remote.sentinel.promisor", "true")
        self.git("config", "extensions.partialClone", "sentinel")
        self.rejected("unsupported_partial_clone", exit_code=2)
        self.assertFalse(marker.exists())

    def test_config_include_is_refused_before_reading_target(self):
        # Git would error with the secret-bearing invalid section if it read this.
        self.write(".env", "[SYNTHETIC_SECRET_DO_NOT_PARSE\n")
        self.git("config", "include.path", "../.env")
        data = self.rejected("unsafe_git_includes", exit_code=2)
        self.assertNotIn("SYNTHETIC_SECRET", json.dumps(data))

    def test_conditional_include_is_refused(self):
        self.git("config", 'includeIf.gitdir:*/.path', "../.env")
        self.rejected("unsafe_git_includes", exit_code=2)

    def test_git_auxiliary_file_redirects_refused(self):
        for key in ("core.excludesFile", "core.attributesFile"):
            with self.subTest(key=key):
                self.git("config", key, ".env")
                self.rejected("unsafe_git_paths", exit_code=2)
                self.git("config", "--unset", key)

    def test_standard_linked_worktree_supported(self):
        with tempfile.TemporaryDirectory(prefix="fde-linked-") as directory:
            linked = Path(directory) / "candidate"
            self.git("worktree", "add", "--detach", str(linked), self.head)
            code, data = self.check(tree=linked)
            self.assertEqual(code, 0, data)
            self.git("worktree", "remove", str(linked))

    def test_namespace_mutation_and_metadata_rebinding_refused(self):
        for suffix in ("del revision", "globals()['revision'] = 'changed'",
                       "globals().update(revision='changed')", "from other import revision",
                       "def revision():\n    pass", "revision, other = ('changed', 1)"):
            with self.subTest(suffix=suffix):
                self.write("server/migrations/versions/two.py",
                           "revision='two'\ndown_revision='one'\n" + suffix + "\n")
                self.commit()
                self.rejected("unsupported_migration_metadata")

    def test_help_is_documented_text_exception(self):
        proc = subprocess.run([sys.executable, str(CLI), "--help"], env=self.env,
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stderr, "")
        self.assertIn("--expected-commit", proc.stdout)

    def test_symlink_cycle_returns_structured_error(self):
        cycle = self.root / "cycle"
        try:
            cycle.symlink_to(cycle, target_is_directory=True)
        except OSError as error:
            if os.name != "nt":
                raise
            self.skipTest(f"host cannot create directory symlink: {type(error).__name__}")
        self.rejected("input_unavailable", exit_code=2, tree=cycle)

    def test_ignored_migration_cannot_change_runtime_graph(self):
        self.write(".gitignore", ".env\nserver/migrations/versions/hidden.py\n")
        self.commit()
        self.write("server/migrations/versions/hidden.py",
                   "revision='hidden'\ndown_revision=None\n")
        self.rejected("untracked_migration")

    def test_deep_indented_filter_cannot_evade_config_check(self):
        marker = self.root / "filter-executed.txt"
        self.write(".gitattributes", "compose.yaml filter=sentinel\n")
        self.commit()
        with (self.root / ".git/config").open("a", encoding="utf-8") as config:
            config.write('\n[branch "sentinel"]\n  remote = local\n    [filter "sentinel"]\n'
                         f'      clean = echo BAD > "{marker.as_posix()}"\n')
        self.write("compose.yaml", "force clean filter\n")
        self.rejected("unsafe_git_filters", exit_code=2)
        self.assertFalse(marker.exists())

    def test_deep_indented_include_cannot_evade_config_check(self):
        self.write(".env", "[SYNTHETIC_SECRET_INVALID\n")
        with (self.root / ".git/config").open("a", encoding="utf-8") as config:
            config.write('\n[branch "sentinel"]\n  remote = local\n    [include]\n      path = ../.env\n')
        self.rejected("unsafe_git_includes", exit_code=2)

    def test_valueless_boolean_followed_by_deeper_section(self):
        with (self.root / ".git/config").open("a", encoding="utf-8") as config:
            config.write('\n[branch "sentinel"]\n  rebase\n    [include]\n      path = ../.env\n')
        self.rejected("unsafe_git_includes", exit_code=2)

    def test_alembic_ignored_filenames_cannot_hide_multiple_heads(self):
        self.migration("three", "three", "one")
        for filename in ("__init__merge", ".#merge"):
            with self.subTest(filename=filename):
                self.migration(filename, "merge", ("two", "three"))
                self.commit()
                try:
                    self.rejected("migration_head_count")
                finally:
                    self.git("rm", f"server/migrations/versions/{filename}.py")

    def test_inactive_worktree_config_is_not_loaded(self):
        with tempfile.TemporaryDirectory(prefix="fde-linked-config-") as directory:
            linked = Path(directory) / "candidate"
            self.git("worktree", "add", "--detach", str(linked), self.head)
            admin = Path((linked / ".git").read_text().strip().removeprefix("gitdir: "))
            (admin / "config.worktree").write_text("[core]\nworktree = /obsolete/path\n")
            try:
                code, data = self.check(tree=linked)
                self.assertEqual(code, 0, data)
                self.git("config", "extensions.worktreeConfig", "true")
                self.rejected("unsafe_git_paths", exit_code=2, tree=linked)
            finally:
                (admin / "config.worktree").unlink()
                self.git("worktree", "remove", str(linked))


if __name__ == "__main__":
    unittest.main()
