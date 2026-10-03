"""fit_bus_rows(): how many bus rows fit in the left column before the rest
are summarised as a "+N more" line instead of being drawn off the panel."""
import unittest

import tests  # noqa: F401 (adds app/ to sys.path)
from config import BUS_BOX_Y_OFFSET, BUS_SECTION_BOTTOM, JOURNEY_HEADER_GAP
from render.bus_train import fit_bus_rows


def services(n):
    return [(str(100 + i), [5], ['SEA']) for i in range(n)]


class TestFitBusRows(unittest.TestCase):
    def test_few_services_all_fit(self):
        self.assertEqual(fit_bus_rows(services(3), BUS_BOX_Y_OFFSET), 3)

    def test_four_services_fill_the_column_exactly(self):
        self.assertEqual(fit_bus_rows(services(4), BUS_BOX_Y_OFFSET), 4)

    def test_overflow_keeps_four_rows_plus_more_line(self):
        self.assertEqual(fit_bus_rows(services(8), BUS_BOX_Y_OFFSET), 4)

    def test_overflow_reserves_room_for_more_line(self):
        # With 6px less room the 4th row still fits on its own (see the
        # exact-fit test) but not with the "+N more" line beneath it.
        self.assertEqual(fit_bus_rows(services(8), BUS_BOX_Y_OFFSET, bottom=BUS_SECTION_BOTTOM - 6), 3)
        self.assertEqual(fit_bus_rows(services(4), BUS_BOX_Y_OFFSET, bottom=BUS_SECTION_BOTTOM - 6), 4)

    def test_journey_lines_take_extra_space(self):
        rows = services(4)
        journeys = {s[0]: {'total_time': 20, 'arrival_time': '08:00'} for s in rows}
        self.assertEqual(fit_bus_rows(rows, BUS_BOX_Y_OFFSET + JOURNEY_HEADER_GAP, journeys), 3)

    def test_empty(self):
        self.assertEqual(fit_bus_rows([], BUS_BOX_Y_OFFSET), 0)


if __name__ == "__main__":
    unittest.main()
