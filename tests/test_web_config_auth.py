"""Flask test_client()-based auth/session/CSRF tests. Sets
WEB_CONFIG_SECRET_KEY/WEB_CONFIG_PASSWORD_HASH in the environment BEFORE
importing web_config, since those are read once at module import time.
"""
import os
import unittest

# Force (not setdefault) these — a real app/.env on a dev machine may already
# be loaded into os.environ by the time this module imports (e.g. via another
# test file importing config.py, which calls load_dotenv()), and that real
# WEB_CONFIG_PASSWORD_HASH must never leak into what these tests check
# against.
os.environ['WEB_CONFIG_SECRET_KEY'] = 'test-secret-key-0123456789abcdef'
os.environ['WEB_CONFIG_USERNAME'] = 'testadmin'

from werkzeug.security import generate_password_hash  # noqa: E402
os.environ['WEB_CONFIG_PASSWORD_HASH'] = generate_password_hash('test-password')

import tests  # noqa: F401,E402 (adds app/ to sys.path)
import web_config  # noqa: E402

PROTECTED_HTML_ROUTES = [
    ('GET', '/schedule'),
    ('GET', '/preview'),
]
# GET routes hit login_required directly -> 401. POST routes are ALSO
# CSRF-protected, and the CSRF check (before_request) runs before
# login_required, so a request with no established session/token at all
# is rejected at the CSRF layer (400) before auth is even checked — still
# correctly denied, just via a different status code.
PROTECTED_API_GET_ROUTES = [
    ('GET', '/api/status'), ('GET', '/api/font_sample/Inter'), ('GET', '/api/preview_image'),
]
PROTECTED_API_POST_ROUTES = [('POST', '/api/refresh'), ('POST', '/api/restart')]


def get_csrf_token(client):
    client.get('/')
    with client.session_transaction() as sess:
        return sess['csrf_token']


def login(client, username='testadmin', password='test-password'):
    token = get_csrf_token(client)
    return client.post('/login', data={'username': username, 'password': password, 'csrf_token': token})


class TestUnauthenticatedAccess(unittest.TestCase):
    def setUp(self):
        self.client = web_config.app.test_client()

    def test_index_shows_login_form_not_config(self):
        resp = self.client.get('/')
        self.assertIn(b'name="password"', resp.data)
        self.assertNotIn(b'Save Configuration', resp.data)

    def test_protected_html_routes_redirect(self):
        for method, path in PROTECTED_HTML_ROUTES:
            resp = self.client.open(path, method=method)
            self.assertEqual(resp.status_code, 302, f"{method} {path} should redirect when unauthenticated")

    def test_protected_api_get_routes_return_401(self):
        for method, path in PROTECTED_API_GET_ROUTES:
            resp = self.client.open(path, method=method)
            self.assertEqual(resp.status_code, 401, f"{method} {path} should 401 when unauthenticated")

    def test_protected_api_post_routes_rejected(self):
        # No CSRF token established yet -> rejected at the CSRF layer (400),
        # never reaching the view/login_required. Still correctly denied.
        for method, path in PROTECTED_API_POST_ROUTES:
            resp = self.client.open(path, method=method)
            self.assertEqual(resp.status_code, 400, f"{method} {path} should be CSRF-rejected when unauthenticated")
            self.assertFalse(resp.get_json()['success'])

    def test_save_config_post_redirects(self):
        resp = self.client.post('/save', data={})
        self.assertEqual(resp.status_code, 302)


class TestLoginFlow(unittest.TestCase):
    def test_valid_login_grants_access(self):
        with web_config.app.test_client() as client:
            resp = login(client)
            self.assertEqual(resp.status_code, 302)
            index_resp = client.get('/')
            self.assertIn(b'Save Configuration', index_resp.data)

    def test_invalid_password_denied(self):
        with web_config.app.test_client() as client:
            resp = login(client, password='wrong-password')
            self.assertEqual(resp.status_code, 302)
            index_resp = client.get('/')
            self.assertNotIn(b'Save Configuration', index_resp.data)

    def test_logout_clears_session(self):
        # Logout is a POST with a CSRF token (a GET link could be triggered
        # cross-site); login() clears the session, so re-render to get one.
        with web_config.app.test_client() as client:
            login(client)
            client.get('/')
            with client.session_transaction() as sess:
                token = sess['csrf_token']
            client.post('/logout', data={'csrf_token': token})
            index_resp = client.get('/')
            self.assertNotIn(b'Save Configuration', index_resp.data)

    def test_logout_get_is_rejected(self):
        with web_config.app.test_client() as client:
            login(client)
            resp = client.get('/logout')
            self.assertEqual(resp.status_code, 405)  # method not allowed — POST only


class TestAuthBugRegression(unittest.TestCase):
    """These are the tests that would have failed against the pre-Phase-3
    code, where auth was a bare unsigned `logged_in=true` cookie."""

    def test_raw_logged_in_cookie_grants_nothing(self):
        with web_config.app.test_client() as client:
            client.set_cookie('logged_in', 'true')
            resp = client.get('/')
            self.assertNotIn(b'Save Configuration', resp.data)
            self.assertIn(b'name="password"', resp.data)

    def test_tampered_session_cookie_denied(self):
        with web_config.app.test_client() as client:
            login(client)
            real_cookie = client.get_cookie('session')
            self.assertIsNotNone(real_cookie)
            tampered_value = real_cookie.value[:-1] + ('a' if real_cookie.value[-1] != 'a' else 'b')
            client.set_cookie('session', tampered_value)
            resp = client.get('/')
            self.assertNotIn(b'Save Configuration', resp.data)


class TestCSRF(unittest.TestCase):
    def test_login_without_csrf_token_rejected(self):
        with web_config.app.test_client() as client:
            client.get('/')  # establishes session + csrf_token, not sent below
            resp = client.post('/login', data={'username': 'testadmin', 'password': 'test-password'})
            self.assertEqual(resp.status_code, 302)
            index_resp = client.get('/')
            self.assertNotIn(b'Save Configuration', index_resp.data)

    def test_save_without_csrf_token_rejected(self):
        with web_config.app.test_client() as client:
            login(client)
            resp = client.post('/save', data={})
            self.assertEqual(resp.status_code, 302)

    def test_api_restart_with_header_csrf_token_accepted_or_fails_gracefully(self):
        # Confirms the CSRF check itself passes with a correct header token;
        # the actual systemctl call will fail in this test environment
        # (no sudo/systemctl access), which is expected and fine — we're
        # only checking it's not rejected at the CSRF layer (400).
        with web_config.app.test_client() as client:
            login(client)
            client.get('/')  # login() clears the session (incl. csrf_token); this
                              # render regenerates one via the context processor
            with client.session_transaction() as sess:
                token = sess['csrf_token']
            resp = client.post('/api/restart', headers={'X-CSRF-Token': token})
            self.assertNotEqual(resp.status_code, 400)


class TestApiStatusWebConfigUptime(unittest.TestCase):
    def test_web_config_uptime_present_and_nonnegative(self):
        with web_config.app.test_client() as client:
            login(client)
            resp = client.get('/api/status')
            self.assertEqual(resp.status_code, 200)
            web_config_status = resp.get_json()['web_config']
            self.assertIn('uptime_seconds', web_config_status)
            self.assertIn('uptime_formatted', web_config_status)
            self.assertGreaterEqual(web_config_status['uptime_seconds'], 0)


class TestScreenPreview(unittest.TestCase):
    """The Preview tab: /preview (the picker page) and /api/preview_image
    (the actual render), which reuses tools/preview_render.py's
    SCREEN_RENDERERS — the same code path the CLI tool uses."""

    def test_preview_page_lists_all_screens(self):
        import html as html_module
        with web_config.app.test_client() as client:
            login(client)
            resp = client.get('/preview')
            self.assertEqual(resp.status_code, 200)
            page = html_module.unescape(resp.data.decode())
            for label in web_config.PREVIEW_SCREEN_LABELS.values():
                self.assertIn(label, page)

    def test_every_offered_screen_renders_a_png(self):
        with web_config.app.test_client() as client:
            login(client)
            for screen in web_config.PREVIEW_SCREEN_LABELS:
                resp = client.get(f'/api/preview_image?screen={screen}')
                self.assertEqual(resp.status_code, 200, screen)
                self.assertEqual(resp.mimetype, 'image/png', screen)
                self.assertTrue(resp.data.startswith(b'\x89PNG'), screen)

    def test_unknown_screen_404s(self):
        with web_config.app.test_client() as client:
            login(client)
            resp = client.get('/api/preview_image?screen=ha_screen')
            self.assertEqual(resp.status_code, 404)
            self.assertFalse(resp.get_json()['success'])

    def test_default_screen_is_combined(self):
        with web_config.app.test_client() as client:
            login(client)
            no_param = client.get('/api/preview_image').data
            explicit = client.get('/api/preview_image?screen=combined').data
            self.assertEqual(no_param, explicit)

    def test_toggles_change_the_rendered_image(self):
        with web_config.app.test_client() as client:
            login(client)
            plain = client.get('/api/preview_image?screen=combined').data
            disrupted = client.get('/api/preview_image?screen=combined&disruption=1').data
            self.assertNotEqual(plain, disrupted)


class TestFontSample(unittest.TestCase):
    def test_known_font_returns_png(self):
        with web_config.app.test_client() as client:
            login(client)
            resp = client.get('/api/font_sample/Inter')
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.mimetype, 'image/png')
            self.assertTrue(resp.data.startswith(b'\x89PNG'))

    def test_unknown_font_404s(self):
        with web_config.app.test_client() as client:
            login(client)
            resp = client.get('/api/font_sample/Comic%20Sans')
            self.assertEqual(resp.status_code, 404)


class TestMqttAuth(unittest.TestCase):
    """Regression: the web UI's MQTT publishes (refresh button, config_reload
    ping) must decrypt a vault-encrypted MQTT_PASSWORD before handing it to
    the broker — passing the enc: ciphertext through got 'Not authorized'
    back from the broker."""

    def test_encrypted_password_is_decrypted(self):
        import tempfile
        from unittest.mock import patch
        from secrets_vault import get_or_create_key, encrypt_value
        with tempfile.TemporaryDirectory() as td:
            key_path = os.path.join(td, 'key')
            encrypted = encrypt_value('broker-pw', get_or_create_key(key_path))
            with patch.dict(os.environ, {'MQTT_USERNAME': 'u', 'MQTT_PASSWORD': encrypted}), \
                 patch.object(web_config, 'SECRETS_KEY_PATH', key_path):
                self.assertEqual(web_config._mqtt_auth(),
                                 {'username': 'u', 'password': 'broker-pw'})

    def test_plaintext_password_passes_through(self):
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, {'MQTT_USERNAME': 'u', 'MQTT_PASSWORD': 'plain-pw'}), \
                 patch.object(web_config, 'SECRETS_KEY_PATH', os.path.join(td, 'key')):
                self.assertEqual(web_config._mqtt_auth(),
                                 {'username': 'u', 'password': 'plain-pw'})

    def test_no_credentials_returns_none(self):
        from unittest.mock import patch
        env = {k: v for k, v in os.environ.items()
               if k not in ('MQTT_USERNAME', 'MQTT_PASSWORD')}
        with patch.dict(os.environ, env, clear=True):
            self.assertIsNone(web_config._mqtt_auth())


if __name__ == "__main__":
    unittest.main()
