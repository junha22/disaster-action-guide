import importlib.util
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('backup_db', Path(__file__).with_name('backup_db.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BackupTests(unittest.TestCase):
    def setUp(self):
        os.umask(0o077)
        self.temp = tempfile.TemporaryDirectory(prefix='kirothon-backup-test-')
        self.base = Path(self.temp.name)
        self.data = self.base / 'data'
        self.data.mkdir(mode=0o700)
        self.root = self.base / 'backups'
        self.records = self.data / 'records.sqlite3'
        with sqlite3.connect(self.records) as conn:
            conn.execute('CREATE TABLE record(id INTEGER PRIMARY KEY, content TEXT)')
            conn.execute('INSERT INTO record(content) VALUES (?)', ('Korean 한글 test',))

    def tearDown(self):
        self.temp.cleanup()

    def test_missing_quota_and_restore_without_live_changes(self):
        before = module.file_hash(self.records)
        snapshot = module.backup(self.data, self.root)
        manifest = module.verify(snapshot)
        self.assertEqual(manifest['databases']['ai_quota.sqlite3']['status'], 'absent_at_backup')
        self.assertFalse((self.data / 'ai_quota.sqlite3').exists())
        result = module.restore_test(snapshot, self.base / 'rehearsals', self.data)
        self.assertEqual(result['restore_test'], 'passed')
        self.assertEqual(before, module.file_hash(self.records))
        self.assertEqual((self.root.stat().st_mode & 0o777), 0o700)
        self.assertEqual(((snapshot / 'manifest.json').stat().st_mode & 0o777), 0o600)

    def test_real_quota_included_without_counter_reset(self):
        quota = self.data / 'ai_quota.sqlite3'
        with sqlite3.connect(quota) as conn:
            conn.execute('CREATE TABLE usage_counters(period TEXT, bucket TEXT, calls INTEGER)')
            conn.execute("INSERT INTO usage_counters VALUES ('day', 'test', 59)")
        before = module.file_hash(quota)
        snapshot = module.backup(self.data, self.root)
        self.assertEqual(module.verify(snapshot)['databases'][quota.name]['status'], 'backed_up')
        result = module.restore_test(snapshot, self.base / 'rehearsals', self.data)
        self.assertIn(quota.name, result['databases'])
        self.assertEqual(module.file_hash(quota), before)

    def test_wal_data_is_in_backup(self):
        conn = sqlite3.connect(self.records)
        try:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('INSERT INTO record(content) VALUES (?)', ('WAL row',))
            conn.commit()
            snapshot = module.backup(self.data, self.root)
            self.assertEqual(module.verify(snapshot)['databases'][self.records.name]['tables']['record'], 2)
        finally:
            conn.close()

    def test_tamper_detected(self):
        snapshot = module.backup(self.data, self.root)
        with sqlite3.connect(snapshot / self.records.name) as conn:
            conn.execute("INSERT INTO record(content) VALUES ('tamper')")
        with self.assertRaises(ValueError):
            module.verify(snapshot)

    def test_restore_into_live_directory_refused(self):
        snapshot = module.backup(self.data, self.root)
        with self.assertRaises(ValueError):
            module.restore_test(snapshot, self.data / 'nested', self.data)

    def test_backup_inside_live_directory_refused(self):
        with self.assertRaises(ValueError):
            module.backup(self.data, self.data / 'nested')

    def test_missing_source_is_not_created(self):
        missing = self.base / 'missing.sqlite3'
        with self.assertRaises(ValueError):
            module.sqlite_copy(missing, self.base / 'copy.sqlite3')
        self.assertFalse(missing.exists())

    def test_symlink_source_refused(self):
        link = self.base / 'link.sqlite3'
        link.symlink_to(self.records)
        with self.assertRaises(ValueError):
            module.sqlite_copy(link, self.base / 'copy.sqlite3')


if __name__ == '__main__':
    unittest.main(verbosity=2)
