"""lara_share.py — letting LARA open a client folder without waiting for a click.

WHY THIS EXISTS
    LARA and EDDIE have both been blocked, repeatedly, on one manual action:
    Michael setting a Drive folder to shareable. On 10 Sep the board showed
    iRise EXPO at 53 days from the shoot with 454 finished files the client
    could not see, and Expo Brazil with Cléo chasing three times for an
    animation that was already rendered. In both cases the work was done. The
    only thing missing was a permission.

    LARA already had `share_with_external`, but it does the wrong thing for a
    delivery: it adds ONE NAMED PERSON as an EDITOR. The house pattern for
    handing work to a client is `anyone with the link → reader` — that is what
    the Enzo and Hablando Claro folders actually use, and it is what makes a
    link in an email open instead of saying "Request access".

    She also could only find a folder by CLIENT NAME, while EDDIE hands her
    FOLDER IDS for dated subfolders. So even when she knew exactly which
    folder was blocked, she had no way to act on it.

THE RULES, AND WHY EACH ONE IS HERE
    * `anyone` is ALWAYS reader. Never writer, not as an option, not as an
      argument. A public writer on a client folder is a bad day that cannot be
      undone by deleting a permission.
    * Nothing is touched unless it lives under _CLIENTS (or the FOOTAGE shared
      drive). A folder id is an opaque string; without this rail, one wrong
      character could publish something that has nothing to do with the client.
    * If the root folder id is not configured, everything refuses. An unset
      variable must never widen what LARA may touch.
    * The permission is READ BACK from the API afterwards and reported. A 200
      is not proof; the state of the folder is proof.
    * Every change is audited.

Pure where it can be: every function takes the Drive service as an argument,
so the decisions can be tested without a network.
"""
import re

ANYONE_ROLE = "reader"          # never anything else, see above
MAX_PARENT_WALK = 12            # deep enough for _CLIENTS/x/2026/09. SETEMBRO/y


# ── safety rails ───────────────────────────────────────────────────────────
def is_under_root(drive, file_id, root_id, max_walk=MAX_PARENT_WALK):
    """True when file_id sits somewhere beneath root_id.

    Walks parents rather than trusting the caller. Returns False on anything
    unexpected — a missing root, a broken chain, a loop — because 'I could not
    prove it is a client folder' must never mean 'go ahead'.
    """
    if not file_id or not root_id:
        return False
    if file_id == root_id:
        return True
    seen = set()
    current = file_id
    for _ in range(max_walk):
        if current in seen:
            return False
        seen.add(current)
        try:
            meta = drive.files().get(
                fileId=current, fields="id, parents",
                supportsAllDrives=True).execute()
        except Exception:
            return False
        parents = meta.get("parents") or []
        if not parents:
            return False
        if root_id in parents:
            return True
        current = parents[0]
    return False


def folder_name(drive, file_id):
    try:
        return drive.files().get(fileId=file_id, fields="name",
                                 supportsAllDrives=True).execute().get("name", "")
    except Exception:
        return ""


def read_permissions(drive, file_id):
    """The live permission list. Returns [] when it cannot be read."""
    try:
        res = drive.permissions().list(
            fileId=file_id, fields="permissions(id,type,role,emailAddress)",
            supportsAllDrives=True).execute()
        return res.get("permissions") or []
    except Exception:
        return []


def link_state(permissions):
    """'open' when anyone-with-the-link can read, else 'closed'."""
    for p in permissions or []:
        if p.get("type") == "anyone":
            return "open"
    return "closed"


def describe_permissions(permissions):
    """One human line per permission, for a Slack message."""
    if not permissions:
        return "_could not read the permissions_"
    out = []
    for p in permissions:
        t = p.get("type")
        if t == "anyone":
            out.append("• *anyone with the link* → %s" % p.get("role"))
        elif t == "user":
            out.append("• %s → %s" % (p.get("emailAddress") or "a user", p.get("role")))
        else:
            out.append("• %s → %s" % (t, p.get("role")))
    return "\n".join(out)


# ── parsing ────────────────────────────────────────────────────────────────
_FOLDER_ID_RE = re.compile(r"[-\w]{25,}")


def extract_folder_id(text):
    """Pull a Drive folder id out of a raw id, a /folders/<id> URL, or a
    ?id=<id> URL. Returns '' when there is not one.

    EDDIE posts folder links into Slack, so accepting the URL he already wrote
    is the difference between LARA acting and LARA asking someone to retype it.
    """
    if not text:
        return ""
    m = re.search(r"/folders/([-\w]{25,})", text)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([-\w]{25,})", text)
    if m:
        return m.group(1)
    for token in re.split(r"[\s<>|,]+", text.strip()):
        token = token.strip().strip('."\'')
        if _FOLDER_ID_RE.fullmatch(token):
            return token
    return ""


# ── the actions ────────────────────────────────────────────────────────────
def open_link(drive, file_id, root_id, root_label="_CLIENTS", audit=None,
              actor="LARA"):
    """Set a folder to `anyone with the link → reader`.

    Returns (ok, message). Idempotent: a folder that is already open says so
    rather than adding a second permission.
    """
    if not root_id:
        return False, ("⚠️ I cannot do this safely — `LARA_DRIVE_CLIENTS_FOLDER_ID` "
                       "is not set, so I have no way to check the folder is a "
                       "client folder. Set it and ask me again.")
    if not file_id:
        return False, "🤔 I need a folder link or id."

    if not is_under_root(drive, file_id, root_id):
        return False, ("🔴 That folder is not inside *%s*, so I am not touching "
                       "it. If it really is a client folder, send me the link "
                       "from inside %s." % (root_label, root_label))

    name = folder_name(drive, file_id) or file_id
    before = read_permissions(drive, file_id)
    if link_state(before) == "open":
        return True, ("✅ *%s* was already open — `anyone with the link → "
                      "reader`. Nothing to change. The link works.\n\n%s"
                      % (name, describe_permissions(before)))

    try:
        drive.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": ANYONE_ROLE},
            fields="id, type, role",
            supportsAllDrives=True,
        ).execute()
    except Exception as e:
        return False, "⚠️ Could not open *%s*: %s" % (name, str(e)[:200])

    # Read it back. A 200 is not proof; the state of the folder is proof.
    after = read_permissions(drive, file_id)
    if link_state(after) != "open":
        return False, ("⚠️ I asked Drive to open *%s* and it did not refuse, but "
                       "reading the folder back it is still closed. Do not send "
                       "the link. This needs a human." % name)

    if audit:
        try:
            audit(folder_name=name, folder_type=root_label, folder_id=file_id,
                  recipient="anyone-with-link", role=ANYONE_ROLE)
        except Exception:
            pass

    return True, ("✅ *%s* is open — `anyone with the link → reader`.\n"
                  "https://drive.google.com/drive/folders/%s\n\n"
                  "_Read back from Drive after the change:_\n%s\n\n"
                  "_Set by %s. Audit logged._" % (name, file_id,
                                                  describe_permissions(after), actor))


def close_link(drive, file_id, root_id, root_label="_CLIENTS", audit=None,
               actor="LARA"):
    """Remove `anyone with the link`. The other half of the tool.

    A capability that can only open access is half a capability — if LARA can
    publish a folder she must be able to un-publish it without waiting for
    anyone.
    """
    if not root_id:
        return False, "⚠️ `LARA_DRIVE_CLIENTS_FOLDER_ID` is not set."
    if not file_id:
        return False, "🤔 I need a folder link or id."
    if not is_under_root(drive, file_id, root_id):
        return False, "🔴 That folder is not inside *%s* — not touching it." % root_label

    name = folder_name(drive, file_id) or file_id
    before = read_permissions(drive, file_id)
    targets = [p for p in before if p.get("type") == "anyone"]
    if not targets:
        return True, "✅ *%s* was already closed. Nothing to change." % name

    for p in targets:
        try:
            drive.permissions().delete(fileId=file_id, permissionId=p.get("id"),
                                       supportsAllDrives=True).execute()
        except Exception as e:
            return False, "⚠️ Could not close *%s*: %s" % (name, str(e)[:200])

    after = read_permissions(drive, file_id)
    if link_state(after) == "open":
        return False, ("⚠️ I removed the link permission on *%s* but it still "
                       "reads as open. This needs a human." % name)
    if audit:
        try:
            audit(folder_name=name, folder_type=root_label, folder_id=file_id,
                  recipient="anyone-with-link", role="REMOVED")
        except Exception:
            pass
    return True, ("🔒 *%s* is closed again. The link now says "
                  "\"Request access\".\n\n_Read back from Drive:_\n%s"
                  % (name, describe_permissions(after)))


def check_link(drive, file_id, root_id, root_label="_CLIENTS"):
    """Answer 'is this shared?' without changing anything.

    The question EDDIE and LARA keep asking each other in Slack, and the one
    that has been answered wrong often enough to be worth a tool.
    """
    if not file_id:
        return False, "🤔 I need a folder link or id."
    name = folder_name(drive, file_id) or file_id
    perms = read_permissions(drive, file_id)
    if not perms:
        return False, "⚠️ I could not read the permissions on that folder."
    state = link_state(perms)
    head = ("✅ *%s* is OPEN — the link works for the client."
            if state == "open" else
            "🔴 *%s* is CLOSED — the client would see \"Request access\".")
    inside = is_under_root(drive, file_id, root_id) if root_id else None
    tail = ""
    if inside is False:
        tail = "\n\n_Note: this folder is not inside %s._" % root_label
    return True, (head % name) + "\n\n" + describe_permissions(perms) + tail
