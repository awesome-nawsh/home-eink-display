"""Font registry: every entry's files exist, unknown names fall back, and
the web schema's DISPLAY_FONT options stay in sync with the registry."""
import os
import unittest

import tests  # noqa: F401 (adds app/ to sys.path)
from render.common import FONT_REGISTRY, resolve_font_pair, picdir
from web_config_schema import CONFIG_SCHEMA


class TestFontRegistry(unittest.TestCase):
    def test_every_registry_entry_exists_on_disk(self):
        for name, files in FONT_REGISTRY.items():
            for f in files:
                path = os.path.join(picdir, f)
                self.assertTrue(os.path.exists(path), f"{name}: missing font file {f}")

    def test_resolve_returns_absolute_pair(self):
        regular, bold = resolve_font_pair('Inter')
        self.assertTrue(regular.endswith('Inter-Regular.ttf'))
        self.assertTrue(bold.endswith('Inter-Bold.ttf'))
        self.assertTrue(os.path.isabs(regular))

    def test_unknown_name_falls_back_without_raising(self):
        regular, bold = resolve_font_pair('Comic Sans')
        self.assertIn('AtkinsonHyperlegibleNext-Regular.otf', regular)
        self.assertIn('AtkinsonHyperlegibleNext-Bold.otf', bold)

    def test_schema_options_match_registry(self):
        options = CONFIG_SCHEMA['Display & Fonts']['DISPLAY_FONT']['options']
        self.assertEqual(list(options), list(FONT_REGISTRY.keys()))

    def test_every_bundled_family_ships_its_license(self):
        for family_dir in ('Inter', 'IBMPlexSans', 'NotoSans',
                           'Bitter', 'Literata', 'Lexend', 'FiraSans'):
            self.assertTrue(os.path.exists(os.path.join(picdir, family_dir, 'OFL.txt')),
                            f"{family_dir}/OFL.txt missing")


if __name__ == "__main__":
    unittest.main()
