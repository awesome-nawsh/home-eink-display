import os
import tempfile
import unittest
from unittest import mock

import tests  # noqa: F401 (adds app/ to sys.path)
from web_config_env import read_env_file, build_env_updates, atomic_write_env_file

SCHEMA = {
    'Core Settings': {
        'API_KEY': {'type': 'password', 'label': 'API Key', 'required': True},
        'BUS_STOP_CODE_A': {'type': 'text', 'label': 'Bus Stop Code', 'required': True},
    },
    'Flags': {
        'SHOW_JOURNEY_TIME': {'type': 'checkbox', 'label': 'Journey Time', 'required': False},
    },
}


def fake_encrypt(value):
    return f"enc:{value}"


class TestReadEnvFile(unittest.TestCase):
    def test_missing_file_returns_empty_dict(self):
        self.assertEqual(read_env_file('/nonexistent/path/.env'), {})

    def test_reads_existing_values(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, '.env')
            with open(path, 'w') as f:
                f.write("# a comment\nBUS_STOP_CODE_A=11331\nAPI_KEY=enc:abc123\n")
            config = read_env_file(path)
            self.assertEqual(config['BUS_STOP_CODE_A'], '11331')
            self.assertEqual(config['API_KEY'], 'enc:abc123')


class TestBuildEnvUpdates(unittest.TestCase):
    def test_checkbox_true_when_present(self):
        to_set, to_unset = build_env_updates({'SHOW_JOURNEY_TIME': 'true'}, SCHEMA, fake_encrypt)
        self.assertEqual(to_set['SHOW_JOURNEY_TIME'], 'true')

    def test_checkbox_false_when_absent(self):
        to_set, to_unset = build_env_updates({}, SCHEMA, fake_encrypt)
        self.assertEqual(to_set['SHOW_JOURNEY_TIME'], 'false')

    def test_password_field_encrypted_when_present(self):
        to_set, to_unset = build_env_updates({'API_KEY': 'plaintext-key'}, SCHEMA, fake_encrypt)
        self.assertEqual(to_set['API_KEY'], 'enc:plaintext-key')

    def test_blank_password_field_omitted_not_unset(self):
        to_set, to_unset = build_env_updates({'API_KEY': ''}, SCHEMA, fake_encrypt)
        self.assertNotIn('API_KEY', to_set)
        self.assertNotIn('API_KEY', to_unset)

    def test_blank_non_password_field_is_unset(self):
        to_set, to_unset = build_env_updates({'BUS_STOP_CODE_A': ''}, SCHEMA, fake_encrypt)
        self.assertIn('BUS_STOP_CODE_A', to_unset)

    def test_non_blank_text_field_is_set(self):
        to_set, to_unset = build_env_updates({'BUS_STOP_CODE_A': '11331'}, SCHEMA, fake_encrypt)
        self.assertEqual(to_set['BUS_STOP_CODE_A'], '11331')


class TestAtomicWriteEnvFile(unittest.TestCase):
    def test_writes_new_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, '.env')
            atomic_write_env_file(path, {'BUS_STOP_CODE_A': '11331'}, [])
            with open(path) as f:
                content = f.read()
            self.assertIn('BUS_STOP_CODE_A=11331', content)

    def test_preserves_comments_and_updates_existing_key(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, '.env')
            with open(path, 'w') as f:
                f.write("# a comment\nBUS_STOP_CODE_A=old_value\nOTHER_KEY=unchanged\n")
            atomic_write_env_file(path, {'BUS_STOP_CODE_A': 'new_value'}, [])
            with open(path) as f:
                content = f.read()
            self.assertIn('# a comment', content)
            self.assertIn('BUS_STOP_CODE_A=new_value', content)
            self.assertIn('OTHER_KEY=unchanged', content)
            self.assertNotIn('old_value', content)

    def test_unset_removes_key(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, '.env')
            with open(path, 'w') as f:
                f.write("BUS_STOP_CODE_A=11331\nA_HEADER=My Stop\n")
            atomic_write_env_file(path, {}, ['A_HEADER'])
            with open(path) as f:
                content = f.read()
            self.assertIn('BUS_STOP_CODE_A=11331', content)
            self.assertNotIn('A_HEADER', content)

    def test_temp_file_cleaned_up_on_failure(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, '.env')
            with mock.patch('os.replace', side_effect=OSError('simulated failure')):
                with self.assertRaises(OSError):
                    atomic_write_env_file(path, {'KEY': 'value'}, [])
            leftover = [f for f in os.listdir(d) if f.startswith('.env_')]
            self.assertEqual(leftover, [])


if __name__ == "__main__":
    unittest.main()
