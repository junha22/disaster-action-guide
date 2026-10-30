import io
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
import zipfile

import deploy


def fixture(root, label):
    for name in ('backend/app', 'frontend/src', 'frontend/public'):
        (root / name).mkdir(parents=True)
    (root / 'backend/app/main.py').write_text('VERSION = ' + repr(label))
    (root / 'backend/app/models.py').write_text('VERSION = 1')
    (root / 'backend/app/database.py').write_text('VERSION = 1')
    (root / 'backend/requirements.lock').write_text('fixed')
    (root / 'frontend/src/App.tsx').write_text(label)
    (root / 'frontend/package.json').write_text('{}')
    (root / 'frontend/package-lock.json').write_text('{}')
    (root / 'frontend/index.html').write_text(label)
    return root


class DeployTests(unittest.TestCase):
    def setUp(self):
        os.umask(0o077)
        self.temp = tempfile.TemporaryDirectory(prefix='kirothon-deploy-test-')
        self.base = Path(self.temp.name)
        self.live = fixture(self.base / 'live', 'old')
        self.stage = fixture(self.base / 'candidate', 'new')
        self.web = self.base / 'web'
        self.web.mkdir()
        (self.web / 'index.html').write_text('old web')
        (self.stage / 'frontend/dist').mkdir()
        (self.stage / 'frontend/dist/index.html').write_text('new web')
        (self.stage / 'frontend/dist/assets').mkdir()
        (self.stage / 'frontend/dist/assets/new.js').write_text('new js')
        self.release = self.base / 'release'
        self.release.mkdir()
        self.commands = []

    def tearDown(self):
        self.temp.cleanup()

    def run_command(self, args, **kwargs):
        self.commands.append(args)
        return ''

    def test_allowed_and_forbidden(self):
        for name in ('backend/app/main.py', 'frontend/src/App.tsx', '.kiro/steering/data-policy.md'):
            self.assertTrue(deploy.allowed(name))
        for name in ('../escape.py', '/backend/app/main.py', 'backend/app/.env',
                     'frontend/src/key.pem', 'backend/.venv/config.py', 'data/a.db',
                     'frontend/node_modules/index.js', 'backend/app/records.sqlite3',
                     'frontend/src/../outside.ts', 'frontend\\src\\App.tsx'):
            self.assertFalse(deploy.allowed(name))

    def test_pack_excludes_operational_files(self):
        (self.live / 'backend/.env').write_text('secret')
        (self.live / 'backend/app/private.pem').write_text('private')
        out = self.base / 'source.zip'
        deploy.pack(self.live, out)
        with zipfile.ZipFile(out) as z:
            self.assertNotIn('backend/.env', z.namelist())
            self.assertNotIn('backend/app/private.pem', z.namelist())
        target = self.base / 'extracted'
        target.mkdir()
        deploy.extract(out, target)
        self.assertTrue((target / 'backend/app/main.py').is_file())

    def test_zip_traversal_rejected(self):
        out = self.base / 'bad.zip'
        with zipfile.ZipFile(out, 'w') as z:
            z.writestr('../escape', 'bad')
        with self.assertRaises(ValueError):
            deploy.extract(out, self.base / 'extract')
        self.assertFalse((self.base / 'escape').exists())

    def test_zip_symlink_rejected(self):
        out = self.base / 'bad.zip'
        with zipfile.ZipFile(out, 'w') as z:
            item = zipfile.ZipInfo('backend/app/main.py')
            item.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(item, '/etc/passwd')
        with self.assertRaises(ValueError):
            deploy.extract(out, self.base / 'extract')

    def test_dependency_change_rejected_before_build(self):
        (self.stage / 'backend/requirements.lock').write_text('changed')
        with self.assertRaises(ValueError):
            deploy.prepare(self.stage, self.live, self.run_command)
        self.assertEqual(self.commands, [])

    def test_schema_change_rejected_before_build(self):
        (self.stage / 'backend/app/models.py').write_text('VERSION = 2')
        with self.assertRaises(ValueError):
            deploy.prepare(self.stage, self.live, self.run_command)
        self.assertEqual(self.commands, [])

    def test_r2_schema_check_runs_before_frontend(self):
        (self.stage / 'backend/app/schema_check.py').write_text('')
        python = self.live / 'backend/.venv/bin/python'
        python.parent.mkdir(parents=True)
        python.touch()
        (self.live / 'frontend/node_modules').mkdir()
        deploy.prepare(self.stage, self.live, self.run_command)
        self.assertEqual(self.commands[0][:3], [str(python), '-m', 'app.schema_check'])
        self.assertEqual(len(self.commands), 3)

    def test_r2_schema_failure_prevents_frontend_and_live_changes(self):
        (self.stage / 'backend/app/schema_check.py').write_text('')
        python = self.live / 'backend/.venv/bin/python'
        python.parent.mkdir(parents=True)
        python.touch()
        def fail(args, **kwargs):
            self.commands.append(args)
            raise RuntimeError('schema incompatible')
        with self.assertRaisesRegex(RuntimeError, 'schema incompatible'):
            deploy.prepare(self.stage, self.live, fail)
        self.assertEqual(len(self.commands), 1)
        self.assertEqual((self.live / 'backend/app/main.py').read_text(), "VERSION = 'old'")

    def test_apply_preserves_env_and_db(self):
        secret = self.live / 'backend/.env'
        secret.write_text('unchanged env')
        database = self.base / 'records.sqlite3'
        database.write_bytes(b'unchanged database')
        result = deploy.apply(self.stage, self.live, self.web, self.release,
                              self.run_command, lambda: True)
        self.assertEqual(result['deployment'], 'passed')
        self.assertEqual(secret.read_text(), 'unchanged env')
        self.assertEqual(database.read_bytes(), b'unchanged database')
        self.assertEqual((self.web / 'index.html').read_text(), 'new web')
        self.assertEqual((self.web / 'assets').stat().st_mode & 0o777, 0o755)

    def test_failed_health_restores_old_code(self):
        answers = iter((False, True))
        with self.assertRaisesRegex(RuntimeError, 'DEPLOY_FAILED_ROLLED_BACK'):
            deploy.apply(self.stage, self.live, self.web, self.release,
                         self.run_command, lambda: next(answers))
        self.assertEqual((self.live / 'backend/app/main.py').read_text(), "VERSION = 'old'")
        self.assertEqual((self.live / 'frontend/src/App.tsx').read_text(), 'old')
        self.assertEqual((self.web / 'index.html').read_text(), 'old web')

    def test_protected_file_in_managed_tree_blocks_apply(self):
        (self.live / 'backend/app/production.db').write_text('live data')
        with self.assertRaises(ValueError):
            deploy.apply(self.stage, self.live, self.web, self.release,
                         self.run_command, lambda: True)
        self.assertEqual(self.commands, [])

    def test_embedded_key_prevents_packaging(self):
        (self.live / 'backend/app/key.py').write_text('key="AKIA' + 'Z' * 16 + '"')
        with self.assertRaises(ValueError):
            deploy.pack(self.live, self.base / 'secret.zip')


if __name__ == '__main__':
    unittest.main(verbosity=2)
