import os
import shutil
import tempfile
from unittest.mock import patch

from oca_port.migrate_addon import MigrateAddon

from . import common


class TestMigrateAddon(common.CommonCase):
    def test_usual_tips(self):
        app = self._create_app(self.source2, self.target2)
        mig = MigrateAddon(app)
        tips = mig._print_tips()
        self.assertIn("1) Reduce the number of commits", tips)
        self.assertIn("2) Adapt the module", tips)
        self.assertIn("3) On a shell command", tips)
        self.assertIn("4) Create the PR against", tips)
        self.assertNotIn("5) ", tips)

    def test_blacklist_tips(self):
        app = self._create_app(self.source2, self.target2)
        mig = MigrateAddon(app)
        tips = mig._print_tips(blacklisted=True)
        self.assertIn("1) On a shell command", tips)
        self.assertIn("2) Create the PR against", tips)
        self.assertNotIn("3) ", tips)

    def test_adapted_tips(self):
        app = self._create_app(self.source2, self.target2)
        mig = MigrateAddon(app)
        tips = mig._print_tips(adapted=True)
        self.assertIn("1) Reduce the number of commits", tips)
        self.assertIn("2) Adapt the module", tips)
        self.assertIn("3) Include your changes", tips)
        self.assertIn("4) Create the PR against", tips)
        self.assertNotIn("5) ", tips)


FAKE_ODL = """#!/bin/sh
echo "$@" > "{log}"
for addon; do :; done
{action}
exit {exit_code}
"""


class TestMigrateAddonOdooLint(common.CommonCase):
    def setUp(self):
        super().setUp()
        self.app = self._create_app(self.source2, self.target2)
        self.app.repo.git.checkout("-b", "mig", self.source2)
        self.bin_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.bin_dir, "odl.log")

    def tearDown(self):
        shutil.rmtree(self.bin_dir)
        super().tearDown()

    def _install_fake_odl(self, action="", exit_code=1):
        path = os.path.join(self.bin_dir, "odl")
        with open(path, "w") as file_:
            file_.write(
                FAKE_ODL.format(log=self.log_path, action=action, exit_code=exit_code)
            )
        os.chmod(path, 0o755)

    def _run_odoo_lint(self):
        path = os.pathsep.join([self.bin_dir, os.environ.get("PATH", "")])
        with patch.dict(os.environ, {"PATH": path}):
            return MigrateAddon(self.app)._apply_odoo_lint()

    def _odl_args(self):
        with open(self.log_path) as file_:
            return file_.read().split()

    def test_fixes_committed(self):
        self._install_fake_odl(action='echo "# fixed" >> "$addon/__init__.py"')
        head = self.app.repo.head.commit
        self.assertTrue(self._run_odoo_lint())
        self.assertEqual(
            self._odl_args(),
            ["upgrade-check", "--target", "17.0", "--fix", self.addon],
        )
        commit = self.app.repo.head.commit
        self.assertEqual(commit.parents[0], head)
        self.assertEqual(commit.summary, f"[IMP] {self.addon}: odoo-lint upgrade fixes")
        self.assertFalse(self.app.repo.is_dirty(untracked_files=True))

    def test_unsafe_fixes(self):
        self.app.odoo_lint_unsafe_fixes = True
        self._install_fake_odl()
        self._run_odoo_lint()
        self.assertIn("--unsafe-fixes", self._odl_args())

    def test_nothing_to_fix(self):
        self._install_fake_odl(exit_code=0)
        head = self.app.repo.head.commit
        self.assertFalse(self._run_odoo_lint())
        self.assertEqual(self.app.repo.head.commit, head)

    def test_odl_error(self):
        self._install_fake_odl(exit_code=2)
        head = self.app.repo.head.commit
        self.assertFalse(self._run_odoo_lint())
        self.assertEqual(self.app.repo.head.commit, head)

    def test_odl_not_installed(self):
        with patch("oca_port.migrate_addon.ODOO_LINT_BIN", "odl-not-installed"):
            self.assertFalse(self._run_odoo_lint())
        self.assertFalse(os.path.exists(self.log_path))
