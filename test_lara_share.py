"""test_lara_share.py — LARA opening a client folder.

Every function takes the Drive service as an argument, so these run against a
fake and touch no network. What they defend is the set of things that would be
expensive to get wrong:

  * `anyone` is never anything but reader
  * nothing outside _CLIENTS is ever touched
  * an unset root id refuses instead of widening what LARA may act on
  * success is read back from the API, never inferred from a call that did
    not raise
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lara_share as ls

ROOT = "ROOT_CLIENTS"


class FakeExec(object):
    def __init__(self, value=None, raises=None):
        self._v = value
        self._raises = raises

    def execute(self):
        if self._raises:
            raise self._raises
        return self._v


class FakeFiles(object):
    def __init__(self, drive):
        self.d = drive

    def get(self, fileId=None, fields=None, supportsAllDrives=None):
        if fileId in self.d.missing:
            return FakeExec(raises=RuntimeError("not found"))
        node = self.d.tree.get(fileId)
        if node is None:
            return FakeExec(raises=RuntimeError("not found"))
        return FakeExec({"id": fileId, "name": node.get("name", ""),
                         "parents": node.get("parents", [])})


class FakePerms(object):
    def __init__(self, drive):
        self.d = drive

    def list(self, fileId=None, fields=None, supportsAllDrives=None):
        if fileId in self.d.unreadable:
            return FakeExec(raises=RuntimeError("nope"))
        return FakeExec({"permissions": list(self.d.perms.get(fileId, []))})

    def create(self, fileId=None, body=None, fields=None, supportsAllDrives=None):
        self.d.created.append((fileId, dict(body or {})))
        if self.d.create_raises:
            return FakeExec(raises=self.d.create_raises)
        if not self.d.create_is_a_lie:
            self.d.perms.setdefault(fileId, []).append(
                {"id": "p%d" % len(self.d.created), "type": body["type"],
                 "role": body["role"]})
        return FakeExec({"id": "p1"})

    def delete(self, fileId=None, permissionId=None, supportsAllDrives=None):
        self.d.deleted.append((fileId, permissionId))
        if self.d.delete_raises:
            return FakeExec(raises=self.d.delete_raises)
        if not self.d.delete_is_a_lie:
            self.d.perms[fileId] = [p for p in self.d.perms.get(fileId, [])
                                    if p.get("id") != permissionId]
        return FakeExec({})


class FakeDrive(object):
    """A Drive with a parent tree and a permission table."""

    def __init__(self):
        self.tree = {
            ROOT: {"name": "_CLIENTS", "parents": []},
            "irise": {"name": "IRISE EXPO", "parents": [ROOT]},
            "aug": {"name": "08. AUGUST 2026", "parents": ["irise"]},
            "deep": {"name": "deeper", "parents": ["aug"]},
            "outside": {"name": "MY TAXES", "parents": ["SOMEWHERE_ELSE"]},
            "SOMEWHERE_ELSE": {"name": "personal", "parents": []},
            "orphan": {"name": "orphan", "parents": []},
            "loopa": {"name": "a", "parents": ["loopb"]},
            "loopb": {"name": "b", "parents": ["loopa"]},
        }
        self.perms = {
            "irise": [{"id": "o1", "type": "user", "role": "owner",
                       "emailAddress": "michael@mwmcreations.com"}],
            "aug": [{"id": "o2", "type": "user", "role": "owner",
                     "emailAddress": "michael@mwmcreations.com"},
                    {"id": "a2", "type": "anyone", "role": "reader"}],
            "outside": [{"id": "o3", "type": "user", "role": "owner",
                         "emailAddress": "michael@mwmcreations.com"}],
        }
        self.missing = set()
        self.unreadable = set()
        self.created = []
        self.deleted = []
        self.create_raises = None
        self.delete_raises = None
        self.create_is_a_lie = False    # API says ok, nothing changes
        self.delete_is_a_lie = False

    def files(self):
        return FakeFiles(self)

    def permissions(self):
        return FakePerms(self)


class TestExtractFolderId(unittest.TestCase):
    ID = "1dMOhYXIq3AAsXu2Qx5XBPG3Hx4nZWTbR"

    def test_a_bare_id(self):
        self.assertEqual(ls.extract_folder_id(self.ID), self.ID)

    def test_a_drive_url(self):
        self.assertEqual(
            ls.extract_folder_id("https://drive.google.com/drive/folders/" + self.ID),
            self.ID)

    def test_a_slack_wrapped_url(self):
        # EDDIE posts links wrapped like <url|text>; accepting what he wrote is
        # the difference between LARA acting and asking someone to retype it
        txt = "<https://drive.google.com/drive/folders/%s|drive.google.com/…>" % self.ID
        self.assertEqual(ls.extract_folder_id(txt), self.ID)

    def test_an_open_url(self):
        self.assertEqual(
            ls.extract_folder_id("https://drive.google.com/open?id=" + self.ID), self.ID)

    def test_a_sentence_around_it(self):
        self.assertEqual(
            ls.extract_folder_id("lara please open " + self.ID + " for the client"),
            self.ID)

    def test_nothing_to_find(self):
        for t in ("", None, "lara open the irise folder", "short", "1234"):
            self.assertEqual(ls.extract_folder_id(t), "", repr(t))


class TestIsUnderRoot(unittest.TestCase):
    def setUp(self):
        self.d = FakeDrive()

    def test_a_direct_child(self):
        self.assertTrue(ls.is_under_root(self.d, "irise", ROOT))

    def test_a_grandchild(self):
        self.assertTrue(ls.is_under_root(self.d, "aug", ROOT))
        self.assertTrue(ls.is_under_root(self.d, "deep", ROOT))

    def test_the_root_itself(self):
        self.assertTrue(ls.is_under_root(self.d, ROOT, ROOT))

    def test_something_outside(self):
        self.assertFalse(ls.is_under_root(self.d, "outside", ROOT))

    def test_an_orphan(self):
        self.assertFalse(ls.is_under_root(self.d, "orphan", ROOT))

    def test_a_missing_file(self):
        self.d.missing.add("ghost")
        self.assertFalse(ls.is_under_root(self.d, "ghost", ROOT))

    def test_a_parent_loop_terminates(self):
        self.assertFalse(ls.is_under_root(self.d, "loopa", ROOT))

    def test_no_root_means_no(self):
        self.assertFalse(ls.is_under_root(self.d, "aug", ""))
        self.assertFalse(ls.is_under_root(self.d, "", ROOT))


class TestOpenLink(unittest.TestCase):
    def setUp(self):
        self.d = FakeDrive()
        self.audits = []

    def _audit(self, **kw):
        self.audits.append(kw)

    def test_it_opens_a_closed_client_folder(self):
        ok, msg = ls.open_link(self.d, "irise", ROOT, audit=self._audit)
        self.assertTrue(ok, msg)
        self.assertEqual(ls.link_state(self.d.perms["irise"]), "open")
        self.assertIn("IRISE EXPO", msg)

    def test_anyone_is_always_reader(self):
        ls.open_link(self.d, "irise", ROOT)
        fid, body = self.d.created[0]
        self.assertEqual(body["type"], "anyone")
        self.assertEqual(body["role"], "reader")
        self.assertEqual(ls.ANYONE_ROLE, "reader")

    def test_it_never_writes_writer_for_anyone(self):
        # belt and braces: the constant is the only source of the role
        ls.open_link(self.d, "irise", ROOT)
        for _, body in self.d.created:
            self.assertNotEqual(body.get("role"), "writer")

    def test_an_already_open_folder_is_left_alone(self):
        ok, msg = ls.open_link(self.d, "aug", ROOT)
        self.assertTrue(ok)
        self.assertEqual(self.d.created, [], "must not add a second permission")
        self.assertIn("already open", msg)

    def test_it_refuses_anything_outside_clients(self):
        ok, msg = ls.open_link(self.d, "outside", ROOT)
        self.assertFalse(ok)
        self.assertEqual(self.d.created, [])
        self.assertIn("not inside", msg)

    def test_it_refuses_when_the_root_is_not_configured(self):
        ok, msg = ls.open_link(self.d, "irise", "")
        self.assertFalse(ok)
        self.assertEqual(self.d.created, [])
        self.assertIn("LARA_DRIVE_CLIENTS_FOLDER_ID", msg)

    def test_it_refuses_an_empty_id(self):
        ok, _ = ls.open_link(self.d, "", ROOT)
        self.assertFalse(ok)

    def test_an_api_error_is_reported_not_swallowed(self):
        self.d.create_raises = RuntimeError("quota")
        ok, msg = ls.open_link(self.d, "irise", ROOT)
        self.assertFalse(ok)
        self.assertIn("Could not open", msg)

    def test_success_is_read_back_not_assumed(self):
        # the API returns 200 and nothing actually changes
        self.d.create_is_a_lie = True
        ok, msg = ls.open_link(self.d, "irise", ROOT)
        self.assertFalse(ok, "a 200 is not proof")
        self.assertIn("Do not send the link", msg)

    def test_it_audits_the_change(self):
        ls.open_link(self.d, "irise", ROOT, audit=self._audit)
        self.assertEqual(len(self.audits), 1)
        self.assertEqual(self.audits[0]["role"], "reader")
        self.assertEqual(self.audits[0]["folder_id"], "irise")

    def test_a_broken_audit_does_not_fail_the_share(self):
        def boom(**kw):
            raise RuntimeError("sheets down")
        ok, _ = ls.open_link(self.d, "irise", ROOT, audit=boom)
        self.assertTrue(ok, "the folder is open; logging is secondary")

    def test_the_message_carries_the_link(self):
        _, msg = ls.open_link(self.d, "irise", ROOT)
        self.assertIn("drive.google.com/drive/folders/irise", msg)


class TestCloseLink(unittest.TestCase):
    def setUp(self):
        self.d = FakeDrive()

    def test_it_closes_an_open_folder(self):
        ok, msg = ls.close_link(self.d, "aug", ROOT)
        self.assertTrue(ok, msg)
        self.assertEqual(ls.link_state(self.d.perms["aug"]), "closed")

    def test_the_owner_is_not_removed(self):
        ls.close_link(self.d, "aug", ROOT)
        roles = [p["role"] for p in self.d.perms["aug"]]
        self.assertIn("owner", roles)

    def test_an_already_closed_folder_is_fine(self):
        ok, msg = ls.close_link(self.d, "irise", ROOT)
        self.assertTrue(ok)
        self.assertEqual(self.d.deleted, [])
        self.assertIn("already closed", msg)

    def test_it_refuses_outside_clients(self):
        ok, _ = ls.close_link(self.d, "outside", ROOT)
        self.assertFalse(ok)
        self.assertEqual(self.d.deleted, [])

    def test_a_lying_delete_is_caught(self):
        self.d.delete_is_a_lie = True
        ok, msg = ls.close_link(self.d, "aug", ROOT)
        self.assertFalse(ok)
        self.assertIn("still reads as open", msg)


class TestCheckLink(unittest.TestCase):
    def setUp(self):
        self.d = FakeDrive()

    def test_it_reports_open(self):
        ok, msg = ls.check_link(self.d, "aug", ROOT)
        self.assertTrue(ok)
        self.assertIn("OPEN", msg)

    def test_it_reports_closed(self):
        ok, msg = ls.check_link(self.d, "irise", ROOT)
        self.assertTrue(ok)
        self.assertIn("CLOSED", msg)
        self.assertIn("Request access", msg)

    def test_it_changes_nothing(self):
        ls.check_link(self.d, "irise", ROOT)
        self.assertEqual(self.d.created, [])
        self.assertEqual(self.d.deleted, [])

    def test_it_flags_a_folder_outside_clients(self):
        ok, msg = ls.check_link(self.d, "outside", ROOT)
        self.assertTrue(ok)
        self.assertIn("not inside", msg)

    def test_unreadable_permissions_are_admitted(self):
        self.d.unreadable.add("irise")
        ok, msg = ls.check_link(self.d, "irise", ROOT)
        self.assertFalse(ok)
        self.assertIn("could not read", msg.lower())


class TestDescribe(unittest.TestCase):
    def test_it_names_the_link_permission_in_plain_words(self):
        out = ls.describe_permissions([{"type": "anyone", "role": "reader"}])
        self.assertIn("anyone with the link", out)

    def test_it_names_a_person(self):
        out = ls.describe_permissions(
            [{"type": "user", "role": "writer", "emailAddress": "a@b.com"}])
        self.assertIn("a@b.com", out)

    def test_empty_is_admitted_not_faked(self):
        self.assertIn("could not read", ls.describe_permissions([]))


# ── routing ────────────────────────────────────────────────────────────────
# These exist because the first version of Patch #134 routed
# "open the link on <url>" correctly but dropped "make that folder shareable"
# and "is this folder shared?" on the floor — the patterns only knew
# "the folder", not "that folder". A phrasing that silently matches nothing
# is worse than one that errors: LARA just answers from the model and nobody
# finds out the tool was never called.
class TestRouting(unittest.TestCase):

    def _intent(self, text):
        from lara_actions import detect_lara_intent
        r = detect_lara_intent(text)
        return r[0] if isinstance(r, tuple) else r

    def test_open_phrasings(self):
        for t in ("open the link on https://drive.google.com/drive/folders/"
                  "1ODe0fNXadpcnCn0XXDLDeGX2wVwRGTNa",
                  "make that folder shareable",
                  "make this folder shareable",
                  "set the folder to anyone with the link",
                  "open it up for the client",
                  "publish the link"):
            self.assertEqual(self._intent(t), "drive_open_link", t)

    def test_check_phrasings(self):
        for t in ("is this folder shared?",
                  "is that folder open?",
                  "is it shared",
                  "check the sharing on that folder",
                  "check the permissions",
                  "who can see that folder"):
            self.assertEqual(self._intent(t), "drive_check_link", t)

    def test_close_phrasings(self):
        for t in ("close the link on that folder",
                  "stop sharing",
                  "make it private"):
            self.assertEqual(self._intent(t), "drive_close_link", t)

    def test_a_named_person_still_goes_to_the_old_flow(self):
        """`share X with a@b.com` must NOT become a public link."""
        self.assertEqual(self._intent("share the iRise folder with cleo@expo.com"),
                         "drive_share")

    def test_it_did_not_swallow_client_status(self):
        self.assertEqual(self._intent("what's the status of the iRise project"),
                         "client_status")


if __name__ == "__main__":
    unittest.main(verbosity=2)
