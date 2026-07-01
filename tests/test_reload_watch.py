import os
import tempfile
import time
import unittest

import tests  # noqa: F401 (adds app/ to sys.path)
from reload_watch import get_mtime, has_changed


class TestGetMtime(unittest.TestCase):
    def test_missing_file_returns_none(self):
        self.assertIsNone(get_mtime('/nonexistent/path/file.txt'))

    def test_existing_file_returns_a_float(self):
        with tempfile.NamedTemporaryFile() as f:
            mtime = get_mtime(f.name)
            self.assertIsInstance(mtime, float)


class TestHasChanged(unittest.TestCase):
    def test_missing_file_unchanged_when_last_mtime_is_none(self):
        changed, mtime = has_changed('/nonexistent/path/file.txt', None)
        self.assertFalse(changed)
        self.assertIsNone(mtime)

    def test_unmodified_file_reports_unchanged(self):
        with tempfile.NamedTemporaryFile() as f:
            first_mtime = get_mtime(f.name)
            changed, mtime = has_changed(f.name, first_mtime)
            self.assertFalse(changed)
            self.assertEqual(mtime, first_mtime)

    def test_modified_file_reports_changed(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'file.txt')
            with open(path, 'w') as f:
                f.write('one')
            first_mtime = get_mtime(path)

            time.sleep(0.01)
            with open(path, 'w') as f:
                f.write('two')
            os.utime(path, (first_mtime + 1, first_mtime + 1))

            changed, mtime = has_changed(path, first_mtime)
            self.assertTrue(changed)
            self.assertNotEqual(mtime, first_mtime)

    def test_file_created_after_being_absent_reports_changed(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'file.txt')
            changed, mtime = has_changed(path, None)
            self.assertFalse(changed)  # still doesn't exist

            with open(path, 'w') as f:
                f.write('new')
            changed, mtime = has_changed(path, None)
            self.assertTrue(changed)
            self.assertIsNotNone(mtime)


if __name__ == "__main__":
    unittest.main()
