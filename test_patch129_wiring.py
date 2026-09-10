"""test_patch129_wiring.py — Victory Intelligence is actually attached to app.py.

victory_routes.py can be perfect and still be dead code if nobody registers it.
This file reads app.py and proves the wiring exists.

LESSON APPLIED (twice learned the hard way): a wiring test must never match on
prose. test_patch119_wiring was defeated by the word "return" inside its own
patch comment, and test_patch127 counted a `lead_data.pop` that lived in a
comment. So every assertion here runs against app.py with comment lines and
docstring-free source only — code, not commentary.
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "app.py")


def code_only(text):
    """Drop full-line comments and inline comments. Crude but sufficient: we
    are looking for the presence of statements, not parsing Python."""
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "#" in line and '"' not in line and "'" not in line:
            line = line.split("#", 1)[0]
        out.append(line)
    return "\n".join(out)


with open(APP, encoding="utf-8") as f:
    RAW = f.read()
CODE = code_only(RAW)


class TestPatch129Wiring(unittest.TestCase):

    def test_module_is_imported(self):
        self.assertIn("import victory_routes as _vi_routes", CODE)

    def test_routes_are_registered_with_the_admin_gate(self):
        # the gate must be passed in — a register() call without it would mean
        # an open door onto Victory's footage index
        self.assertRegex(
            CODE, r"_vi_routes\.register\(\s*app\s*,\s*_admin_secret_ok\s*,")

    def test_boot_is_called(self):
        self.assertIn("_vi_routes.boot()", CODE)

    def test_wiring_is_inside_a_try(self):
        # Victory Intelligence must not be able to stop the sales machine
        i = CODE.index("import victory_routes as _vi_routes")
        head = CODE[max(0, i - 200):i]
        self.assertIn("try:", head, "the import must sit inside a try block")
        tail = CODE[i:i + 700]
        self.assertIn("except Exception", tail)

    def test_wiring_appears_before_main(self):
        self.assertLess(CODE.index("_vi_routes.register"),
                        CODE.index('if __name__ == "__main__":'))

    def test_registration_happens_exactly_once(self):
        self.assertEqual(len(re.findall(r"_vi_routes\.register\(", CODE)), 1)

    def test_the_helpers_it_passes_actually_exist(self):
        self.assertIn("def _admin_secret_ok(", CODE)
        self.assertIn("def _report_error(", CODE)

    def test_supporting_modules_are_present_on_disk(self):
        for m in ("victory_index.py", "victory_ingest.py", "victory_routes.py"):
            self.assertTrue(os.path.exists(os.path.join(HERE, m)), m)

    def test_source_folder_ships_with_the_app(self):
        # Railway deploys the repo; the ingest reads from here, so it has to be
        # in the tree rather than on someone's desktop.
        base = os.path.join(HERE, "victory_source", "VWC26")
        for f in ("event.json", "sessions.json", "clips.json", "quotes.json"):
            self.assertTrue(os.path.exists(os.path.join(base, f)), f)

    def test_no_admin_secret_value_is_hardcoded_near_the_patch(self):
        i = CODE.index("import victory_routes as _vi_routes")
        window = CODE[i - 400:i + 900]
        self.assertNotIn("UPLOAD_SECRET =", window)
        self.assertNotIn("mwm-media-2026", window)


class TestPatch130Wiring(unittest.TestCase):
    """Phase 2: the mailer and the #dev notifier are actually attached."""

    def test_the_mailer_is_passed_in(self):
        self.assertRegex(CODE, r"_vi_routes\.register\([^)]*send_email\s*=\s*_vi_send_email")

    def test_the_notifier_is_passed_in(self):
        self.assertRegex(CODE, r"_vi_routes\.register\([^)]*notify\s*=\s*_vi_notify")

    def test_both_helpers_are_defined(self):
        self.assertIn("def _vi_send_email(", CODE)
        self.assertIn("def _vi_notify(", CODE)

    def test_links_are_sent_as_info_not_as_michael(self):
        # a login link should not look like it came from Michael personally
        i = CODE.index("def _vi_send_email(")
        window = CODE[i:i + 1400]
        self.assertIn("info@mwmcreations.com", window)
        self.assertNotIn("MICHAEL_EMAIL", window)

    def test_the_mailer_reports_failure_rather_than_assuming_success(self):
        i = CODE.index("def _vi_send_email(")
        window = CODE[i:i + 1800]
        self.assertIn("return False", window)
        self.assertIn("_report_error", window)

    def test_the_auth_modules_are_present_on_disk(self):
        for m in ("victory_auth.py", "victory_store.py", "victory_page.py"):
            self.assertTrue(os.path.exists(os.path.join(HERE, m)), m)


if __name__ == "__main__":
    unittest.main(verbosity=2)
