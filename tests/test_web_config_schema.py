"""CONFIG_SCHEMA sanity: no blank select options (the field macro renders
its own '-- Select --' empty option), env-var-shaped field keys, and the
collapsed-categories set referencing real categories."""
import re
import unittest

import tests  # noqa: F401 (adds app/ to sys.path)
from web_config_schema import CONFIG_SCHEMA, COLLAPSED_CATEGORIES

ENV_VAR_SHAPE = re.compile(r'^[A-Z][A-Z0-9_]*$')


class TestConfigSchema(unittest.TestCase):
    def test_no_select_has_a_blank_option(self):
        # A blank entry would double up with the macro's own '-- Select --'
        # empty option (the old FORCE_SCREEN bug).
        for category, fields in CONFIG_SCHEMA.items():
            for name, cfg in fields.items():
                if cfg['type'] == 'select':
                    self.assertNotIn('', cfg['options'], f"{category}/{name} has a blank option")

    def test_field_keys_look_like_env_vars(self):
        for fields in CONFIG_SCHEMA.values():
            for name in fields:
                self.assertRegex(name, ENV_VAR_SHAPE)

    def test_no_field_appears_in_two_categories(self):
        seen = {}
        for category, fields in CONFIG_SCHEMA.items():
            for name in fields:
                self.assertNotIn(name, seen, f"{name} in both {seen.get(name)} and {category}")
                seen[name] = category

    def test_collapsed_categories_exist(self):
        for category in COLLAPSED_CATEGORIES:
            self.assertIn(category, CONFIG_SCHEMA)


if __name__ == "__main__":
    unittest.main()
