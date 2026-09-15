"""victory_drive.py — where a finished cut lives: Michael's Drive, one folder.

The worker on the Mac hands the app the file; the app puts it in Drive with the
same DWD credentials LARA's Drive actions use (impersonating
michael@mwmcreations.com), makes it viewable by link, and keeps the id. The
page then plays it straight from Drive: no video bytes ever stream through
Railway, and the file is already where a delivery would be sent from.

Nothing here raises into a request: upload_video returns None on any failure
and prints why. The caller marks the request failed with that reason.
"""
import io
import os

FOLDER_NAME = os.environ.get("VI_DRIVE_FOLDER", "Victory Intelligence — Deliveries")
SCOPES = ["https://www.googleapis.com/auth/drive"]

_folder_id_cache = {}


def _service():
    from googleapiclient.discovery import build
    from lara_actions import _get_google_creds
    return build("drive", "v3", credentials=_get_google_creds(SCOPES, use_dwd=True),
                 cache_discovery=False)


def _folder(drive, name=FOLDER_NAME):
    """Find or create the deliveries folder in My Drive root."""
    if name in _folder_id_cache:
        return _folder_id_cache[name]
    q = ("name = '%s' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
         % name.replace("'", "\\'"))
    res = drive.files().list(q=q, fields="files(id,name)", pageSize=5).execute()
    files = res.get("files", [])
    if files:
        fid = files[0]["id"]
    else:
        meta = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
        fid = drive.files().create(body=meta, fields="id").execute()["id"]
        print("[VI-DRIVE] created folder %r -> %s" % (name, fid))
    _folder_id_cache[name] = fid
    return fid


def upload_video(name, data, mime="video/mp4", folder_name=FOLDER_NAME):
    """Put bytes in the deliveries folder, viewable by anyone with the link.
    Returns {"id", "link", "download"} or None."""
    try:
        from googleapiclient.http import MediaIoBaseUpload
        drive = _service()
        fid = _folder(drive, folder_name)
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime, resumable=len(data) > 5_000_000)
        f = drive.files().create(body={"name": name, "parents": [fid]}, media_body=media,
                                 fields="id,webViewLink").execute()
        file_id = f["id"]
        try:
            drive.permissions().create(fileId=file_id, body={"type": "anyone", "role": "reader"},
                                       fields="id").execute()
        except Exception as e:
            # Playable for Michael either way; a client viewer needs the link share.
            print("[VI-DRIVE] link-share failed for %s: %r" % (file_id, e))
        return {"id": file_id, "link": f.get("webViewLink", ""),
                "download": "https://drive.google.com/uc?export=download&id=" + file_id}
    except Exception as e:
        print("[VI-DRIVE] upload failed: %r" % (e,))
        return None


def selftest():
    """Prove the path with a 1 KB text file. Returns a dict, never raises."""
    try:
        drive = _service()
        fid = _folder(drive)
        from googleapiclient.http import MediaIoBaseUpload
        body = ("Victory Intelligence Drive self-test. Safe to delete.\n").encode("utf-8")
        f = drive.files().create(body={"name": "_vi_selftest.txt", "parents": [fid]},
                                 media_body=MediaIoBaseUpload(io.BytesIO(body), mimetype="text/plain"),
                                 fields="id,webViewLink").execute()
        drive.files().delete(fileId=f["id"]).execute()
        return {"ok": True, "folder_id": fid, "folder": FOLDER_NAME, "wrote_and_deleted": f["id"]}
    except Exception as e:
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:400])}


def preview_url(file_id):
    return "https://drive.google.com/file/d/%s/preview" % file_id


def download_url(file_id):
    return "https://drive.google.com/uc?export=download&id=%s" % file_id
