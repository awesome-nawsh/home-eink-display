import unittest

import tests  # noqa: F401 (adds app/ to sys.path)
from boot_checks import format_checklist_lines

# check_network/check_internet/check_lta_api/check_home_assistant are
# intentionally NOT unit-tested here — they hit real sockets/HTTP and are
# integration-only, exercised by actually booting the app on the Pi.


class TestFormatChecklistLines(unittest.TestCase):
    def test_all_ok(self):
        results = [("Network", True), ("Internet", True)]
        self.assertEqual(format_checklist_lines(results), ["Network: OK", "Internet: OK"])

    def test_mixed_results(self):
        results = [("Network", True), ("Home Assistant", False)]
        self.assertEqual(format_checklist_lines(results), ["Network: OK", "Home Assistant: FAIL"])

    def test_empty_results(self):
        self.assertEqual(format_checklist_lines([]), [])


if __name__ == "__main__":
    unittest.main()
