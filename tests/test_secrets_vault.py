import os
import stat
import tempfile
import unittest

import tests  # noqa: F401 (adds app/ to sys.path)
from cryptography.fernet import Fernet, InvalidToken

from secrets_vault import get_or_create_key, encrypt_value, decrypt_value, is_encrypted


class TestGetOrCreateKey(unittest.TestCase):
    def test_generates_key_with_restrictive_permissions(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".encryption_key")
            key = get_or_create_key(path)
            self.assertTrue(os.path.exists(path))
            mode = stat.S_IMODE(os.stat(path).st_mode)
            self.assertEqual(mode, 0o600)
            self.assertTrue(len(key) > 0)

    def test_reads_existing_key_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".encryption_key")
            first = get_or_create_key(path)
            second = get_or_create_key(path)
            self.assertEqual(first, second)


class TestEncryptDecrypt(unittest.TestCase):
    def setUp(self):
        self.key = Fernet.generate_key()

    def test_round_trip(self):
        plaintext = "my-secret-api-key-12345"
        stored = encrypt_value(plaintext, self.key)
        self.assertTrue(stored.startswith("enc:"))
        self.assertEqual(decrypt_value(stored, self.key), plaintext)

    def test_decrypt_plaintext_passthrough(self):
        self.assertEqual(decrypt_value("plain-value-not-encrypted", self.key), "plain-value-not-encrypted")

    def test_decrypt_empty_passthrough(self):
        self.assertEqual(decrypt_value("", self.key), "")

    def test_decrypt_with_wrong_key_raises(self):
        stored = encrypt_value("secret", self.key)
        wrong_key = Fernet.generate_key()
        with self.assertRaises(InvalidToken):
            decrypt_value(stored, wrong_key)

    def test_is_encrypted(self):
        stored = encrypt_value("secret", self.key)
        self.assertTrue(is_encrypted(stored))
        self.assertFalse(is_encrypted("plaintext"))
        self.assertFalse(is_encrypted(""))
        self.assertFalse(is_encrypted(None))


if __name__ == "__main__":
    unittest.main()
