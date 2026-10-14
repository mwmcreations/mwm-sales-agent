"""
ad_video.py — PATCH #247. Put a finished ad video into the Meta ad account's
video library (ERIC, 14 Oct: his Chrome uploader is capped at 10 MB, the
AD_20 draft is waiting on two 20–29 MB files).

The machine already streams a Drive file to Meta on a one-time
/ig/media/<token> URL for the Instagram publisher; the Marketing API takes
the same thing as `file_url` on POST /act_<id>/advideos. Meta pulls the
file, transcodes it, and the video shows up in the account library under
`title`; ERIC then picks it in Ads Manager. Nothing here touches a
campaign, ad set, ad or budget.

PURE: the checks, the request bodies, the upload-and-wait loop with an
injectable http/clock. app.py owns Drive, the token, the route, Slack.
"""
import time

GRAPH = "https://graph.facebook.com/v21.0"
AD_ACCOUNT_DEFAULT = "act_691911781413399"      # MWM ad account (business 671606610233935)
VIDEO_MIMES = ("video/mp4", "video/quicktime")
MAX_BYTES = 4 * 1024 ** 3                        # Meta's advideos ceiling
POLL_EVERY_S = 10
POLL_MAX_S = 15 * 60
READY = ("ready",)
FAILED = ("error", "failed")


def problems(meta):
    """Drive metadata -> list of reasons not to send it."""
    out = []
    if not meta or not meta.get("id"):
        out.append("Drive file not found or not readable by the machine")
        return out
    if str(meta.get("mimeType") or "") not in VIDEO_MIMES:
        out.append("not an MP4/MOV (mimeType %s)" % meta.get("mimeType"))
    try:
        size = int(meta.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    if size <= 0:
        out.append("Drive reports no size for the file")
    elif size > MAX_BYTES:
        out.append("file is %d bytes; Meta's limit is 4 GB" % size)
    if not meta.get("md5Checksum"):
        out.append("Drive has no md5 for the file (not a binary upload?)")
    return out


def title_for(meta, title=None):
    t = " ".join(str(title or meta.get("name") or "").split())
    return t[:255] or "untitled"


def upload_params(file_url, title):
    return {"file_url": file_url, "title": title, "name": title}


def run_upload(job, http, token, account=AD_ACCOUNT_DEFAULT, sleep=time.sleep, now=time.time, log=lambda *_: None):
    """POST advideos (file_url) -> poll until ready -> job. Mutates and returns job.
    http: get(url, params, timeout) / post(url, data, timeout) -> .status_code, .json()."""
    def _err(stage, r=None, extra=""):
        msg = extra
        try:
            if r is not None:
                e = (r.json() or {}).get("error") or {}
                msg = (e.get("error_user_msg") or e.get("message") or msg or "HTTP %s" % r.status_code)
        except Exception:
            msg = msg or "HTTP %s" % getattr(r, "status_code", "?")
        job.update(status="failed", stage=stage, error=str(msg)[:400])
        return job

    job.update(status="uploading")
    r = http.post("%s/%s/advideos" % (GRAPH, account),
                  data=dict(upload_params(job["video_url"], job["title"]), access_token=token), timeout=120)
    vid = (r.json() or {}).get("id") if r.status_code == 200 else None
    if not vid:
        return _err("upload", r)
    job.update(video_id=vid, status="processing")
    t0 = now()
    while True:
        s = http.get("%s/%s" % (GRAPH, vid), params={"fields": "id,title,length,status", "access_token": token}, timeout=30)
        d = (s.json() or {}) if s.status_code == 200 else {}
        st = (d.get("status") or {})
        vs = str(st.get("video_status") or "").lower()
        if vs in READY:
            job.update(status="ready", title_in_library=d.get("title"), length_s=d.get("length"))
            return job
        if vs in FAILED:
            return _err("processing", None, "Meta could not process the video (%s)" % (st.get("processing_phase") or vs))
        if now() - t0 > POLL_MAX_S:
            return _err("processing", None, "Meta did not finish processing in %d min" % (POLL_MAX_S // 60))
        sleep(POLL_EVERY_S)
