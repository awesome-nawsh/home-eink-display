import unittest

import tests  # noqa: F401 (adds app/ to sys.path)
from config import _resolve_force_screen
from scheduler import SCREEN_NAMES


class TestResolveForceScreen(unittest.TestCase):
    def test_empty_returns_none(self):
        self.assertIsNone(_resolve_force_screen(''))

    def test_none_returns_none(self):
        self.assertIsNone(_resolve_force_screen(None))

    def test_whitespace_only_returns_none(self):
        self.assertIsNone(_resolve_force_screen('   '))

    def test_valid_screen_names_pass_through(self):
        for name in SCREEN_NAMES:
            self.assertEqual(_resolve_force_screen(name), name)

    def test_invalid_name_returns_none(self):
        self.assertIsNone(_resolve_force_screen('not_a_real_screen'))

    def test_strips_surrounding_whitespace(self):
        self.assertEqual(_resolve_force_screen(f'  {SCREEN_NAMES[0]}  '), SCREEN_NAMES[0])


if __name__ == "__main__":
    unittest.main()
