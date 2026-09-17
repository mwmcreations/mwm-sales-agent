"""victory_routes.py — the Victory Intelligence HTTP surface.

Registered from app.py with a single call, so the 24k-line app file gains six
lines rather than several hundred, and this surface can be reasoned about on
its own.

    GET  /vi/            the app, or the sign-in form
    POST /vi/login       ask for a sign-in link
    GET  /vi/auth        spend a link, get a session
    GET  /vi/logout      end the session
    GET  /vi/search      ranked results          (session or admin)
    GET  /vi/health      what the index holds    (admin)
    POST /vi/ingest      load an event           (admin)
    POST /vi/grant       set someone's role      (admin)
    GET  /vi/people      who has been granted    (admin)
    POST /vi/issue-link  mint a link WITHOUT emailing it (admin)

    Phase 3 — the machine editor (14 Sep 2026):
    POST /vi/request         ask for a cut (session)   — items optional now
    GET  /vi/mine            my requests as JSON       (session)
    GET  /vi/queue           my requests as a page     (session; mwm sees all)
    POST /vi/feedback        a note on a finished cut  (session)
    POST /vi/decide          approve / decline a cut   (session)
    GET  /vi/jobs/next       claim the next request    (admin; the Mac worker)
    POST /vi/jobs/<id>/deliver   the finished file     (admin; multipart)
    POST /vi/jobs/<id>/fail      why it did not render (admin)
    POST /vi/jobs/<id>/requeue   back in the queue     (admin)
    GET  /vi/card            a title card as a PNG     (admin; the worker)
    GET  /vi/media/missing   clips without thumbnails  (admin; the worker)
    POST /vi/media/<clip>    poster + preview upload   (admin; the worker)
    GET  /vi/thumb/<clip>.jpg, /vi/preview/<clip>.mp4  (session)
    POST /vi/drive-selftest  prove the Drive path      (admin)

TWO GATES, AND THE DIFFERENCE MATTERS
    Anything that changes the system — ingest, grant — stays behind the
    fail-closed admin secret, which only Michael and the deploy daemon hold.
    Reading the index needs only a signed-in session, because that is the
    thing Victory staff are meant to do.

    /vi/search accepts either. The admin path is what lets the daemon prove
    the live ranking without a browser, and it is checked first so a
    verification run never depends on a cookie.

WHY /vi/issue-link EXISTS
    It returns a working sign-in link instead of emailing it, so the whole
    door can be tested end to end without sending mail to a real person at
    Victory. It is admin-only and it logs loudly. It is a testing instrument,
    not a back door: it still mints an ordinary single-use link for an
    ordinary allowed address.
"""
import time

COOKIE = "vi_session"
HELPER_MAX_PER_WINDOW = 40     # helper messages per person per rate window


def _client_ip(request):
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr or ""


def register(app, admin_ok, report_error=None, send_email=None, notify=None, drive_upload=None):
    """Attach the /vi/* routes.

    admin_ok(provided) -> bool          the app's fail-closed admin check
    report_error(where, err, ctx)       the app's error reporter (optional)
    send_email(to, subject, text, html) -> bool   (optional; without it, no
                                        link can be emailed and /vi/login says
                                        so in the log rather than pretending)
    notify(text)                        a line into #dev (optional)
    drive_upload(name, bytes) -> {"id",..} | None   where a finished cut goes
                                        (optional; defaults to victory_drive)
    """
    from flask import request, jsonify, make_response, redirect

    import victory_auth as va
    import victory_store as vs
    import victory_page as vp

    limiter = va.RateLimiter()

    if drive_upload is None:
        def drive_upload(name, data):
            import victory_drive as vd
            return vd.upload_video(name, data)

    def _is_mwm(sess):
        return bool(sess) and sess.get("role") == va.ROLE_MWM

    def _jsonable_request(r):
        out = dict(r)
        for k in ("at", "handled_at", "started_at", "finished_at"):
            if out.get(k) is not None:
                out[k] = str(out[k])
        if isinstance(out.get("summary"), str):
            try:
                import json as _json
                out["summary"] = _json.loads(out["summary"])
            except Exception:
                pass
        return out

    def _err(where, exc, ctx=""):
        try:
            if report_error:
                report_error(where, exc, ctx)
            else:
                print("[VI] %s: %r %s" % (where, exc, ctx))
        except Exception:
            pass

    def _tell(text):
        try:
            if notify:
                notify(text)
            else:
                print("[VI] %s" % text)
        except Exception:
            pass

    # ── gates ──────────────────────────────────────────────────────────────
    def _secret_from_request():
        s = request.values.get("secret", "")
        if not s:
            body = request.get_json(force=True, silent=True) or {}
            s = body.get("secret", "")
        return s

    def _is_admin():
        return admin_ok(_secret_from_request())

    def _admin_guard():
        if not _is_admin():
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        return None

    def _session():
        """The signed-in person, or None."""
        return va.verify_session(request.cookies.get(COOKIE, ""),
                                 vs.session_secret(create=False))

    def _base_url():
        # Railway terminates TLS in front of us, so request.url_root can say
        # http:// even though the world reached us over https. A sign-in link
        # that downgrades the scheme is a sign-in link sent in the clear.
        root = request.url_root.rstrip("/")
        if request.headers.get("X-Forwarded-Proto", "").startswith("https"):
            root = "https://" + root.split("://", 1)[-1]
        return root

    # ── the door ───────────────────────────────────────────────────────────
    @app.route("/vi/", methods=["GET"])
    @app.route("/vi", methods=["GET"])
    def vi_home():
        try:
            sess = _session()
            if not sess:
                return vp.signin_page()
            if not va.can_search(sess["role"]):
                return vp.pending_page(sess["email"])
            import victory_index as vi
            if vi.corpus_size() == 0:
                vi.load_corpus()
            return vp.app_page(sess["email"], sess["role"], records=vi.corpus_size())
        except Exception as e:
            _err("vi_home", e)
            return vp.signin_page(message="Something went wrong. Try again.")

    @app.route("/vi/library", methods=["GET"])
    def vi_library():
        """The Library on its own (Browse footage). The front door no longer
        shows clips unless the person asks to choose them (Michael, 17 Sep)."""
        try:
            sess = _session()
            if not sess:
                return vp.signin_page()
            if not va.can_search(sess["role"]):
                return vp.pending_page(sess["email"])
            import victory_index as vi
            if vi.corpus_size() == 0:
                vi.load_corpus()
            return vp.app_page(sess["email"], sess["role"], records=vi.corpus_size(), mode="browse")
        except Exception as e:
            _err("vi_library", e)
            return vp.signin_page(message="Something went wrong. Try again.")

    @app.route("/vi/ideas", methods=["GET"])
    def vi_ideas():
        """Ready-made asks from what the Library holds — for the person who
        would only ever write "give me a nice video" (Michael, 17 Sep)."""
        try:
            sess = _session()
            if not sess or not va.can_search(sess["role"]):
                return jsonify({"ok": False, "error": "unauthorized"}), 401
            import victory_index as vi
            import victory_helper as vh
            if vi.corpus_size() == 0:
                vi.load_corpus()
            return jsonify({"ok": True, "ideas": vh.ideas(vi.snapshot())})
        except Exception as e:
            _err("vi_ideas", e)
            return jsonify({"ok": False, "error": "no ideas just now"}), 500

    @app.route("/vi/helper", methods=["POST"])
    def vi_helper():
        """The helper: a short exchange that ends with a sentence for the box.
        Session only; one model call per message, so it is rate-limited per
        person like the sign-in link is per address."""
        try:
            sess = _session()
            if not sess or not va.can_search(sess["role"]):
                return jsonify({"ok": False, "error": "unauthorized"}), 401
            if not limiter.allow("help:" + sess["email"], HELPER_MAX_PER_WINDOW):
                return jsonify({"ok": False, "error": "Give me a minute — too many messages at once."}), 429
            body = request.get_json(force=True, silent=True) or {}
            msgs = body.get("messages") or []
            if not isinstance(msgs, list) or not msgs or not any(
                    isinstance(m, dict) and str(m.get("text") or "").strip() for m in msgs):
                return jsonify({"ok": False, "error": "say something first"}), 400
            import victory_index as vi
            import victory_helper as vh
            if vi.corpus_size() == 0:
                vi.load_corpus()
            client = app.config.get("VI_HELPER_CLIENT") or app.config.get("VI_DESCRIBE_CLIENT")
            out = vh.chat(msgs[-vh.MAX_TURNS:], vi.snapshot(), client=client)
            out["ok"] = True
            return jsonify(out), 200
        except Exception as e:
            _err("vi_helper", e)
            return jsonify({"ok": False, "error": "the helper is not answering; try again"}), 500

    @app.route("/vi/brief", methods=["GET"])
    def vi_brief():
        """'Understood as …' — how the editor reads an ask, shown under the
        box while the person types. Cheap: words only, no model, no search."""
        try:
            if not _is_admin():
                sess = _session()
                if not sess or not va.can_search(sess["role"]):
                    return jsonify({"ok": False, "error": "unauthorized"}), 401
            q = (request.values.get("q") or "")[:2000]
            try:
                length = int(request.values.get("length") or 0) or None
            except Exception:
                length = None
            import victory_cut as _vc
            said = _vc.length_from(q)
            b = _vc.brief_for(q, said or length)
            b["ok"] = True
            b["length_said"] = bool(said)
            return jsonify(b)
        except Exception as e:
            _err("vi_brief", e)
            return jsonify({"ok": False, "error": "brief failed"}), 500

    @app.route("/vi/login", methods=["POST"])
    def vi_login():
        """Ask for a sign-in link.

        Answers identically whichever address is given. A form that says
        'unknown address' is a form that tells a stranger who works at Victory.
        """
        try:
            email = va.normalize_email(request.form.get("email", "")
                                       or (request.get_json(silent=True) or {}).get("email", ""))
            ip = _client_ip(request)
            ok_ip = limiter.allow("ip:" + ip, va.LINK_MAX_PER_IP)
            ok_em = limiter.allow("em:" + email, va.LINK_MAX_PER_EMAIL) if email else True

            # An address off a trusted domain is allowed ONLY if Michael has
            # already granted it a role. Three of Victory's leadership are on
            # me.com, yahoo.com and aol.com; without this they could not sign
            # in to their own platform. The lookup is skipped for trusted
            # domains so the common path costs nothing.
            known = False
            if email and va.is_external(email):
                known = bool(vs.get_person(email))

            # THE SEND LOCK. Checked before anything is created, not before
            # anything is sent — a link that exists is a link that can leak.
            # See victory_auth.client_email_enabled for why this is here.
            if email and not va.may_email(email):
                print("[VI-AUTH] SEND LOCK: refused to create or email a link "
                      "for a client address")
                _tell(":lock: Victory Intelligence is still locked to internal "
                      "testing, so a sign-in link for *%s* was NOT created or "
                      "sent. Set VI_CLIENT_EMAIL=1 in Railway when the testing "
                      "is done." % email)
                return vp.signin_page(sent=True)

            if email and va.is_allowed(email, known=known) and ok_ip and ok_em:
                token, token_hash = va.new_token()
                if vs.create_link(token_hash, email, ip):
                    url = "%s/vi/auth?token=%s" % (_base_url(), token)
                    sent = False
                    if send_email:
                        try:
                            sent = bool(send_email(email, va.LINK_SUBJECT,
                                                   va.link_email_text(url),
                                                   va.link_email_html(url)))
                        except Exception as _sx:
                            _err("vi_login.send", _sx, email)
                    if sent:
                        print("[VI-AUTH] link sent to %s" % email)
                    else:
                        # Never print the token: the log would become a key.
                        print("[VI-AUTH] link created for %s but NOT emailed "
                              "(no mailer)" % email)
                        _tell(":warning: Victory Intelligence could not email a "
                              "sign-in link to %s — the mailer is not wired." % email)
            elif email and not va.is_allowed(email, known=known):
                print("[VI-AUTH] refused a link for a domain we do not trust")
            elif not (ok_ip and ok_em):
                print("[VI-AUTH] rate limited a link request")

            return vp.signin_page(sent=True)
        except Exception as e:
            _err("vi_login", e)
            return vp.signin_page(sent=True)      # still say nothing useful

    @app.route("/vi/auth", methods=["GET"])
    def vi_auth():
        """Spend a link. Single use is enforced by the UPDATE in the store."""
        try:
            token = request.args.get("token", "")
            secret = vs.session_secret()
            if not secret:
                return vp.signin_page(message="Sign-in is unavailable right now."), 503

            claimed = vs.consume_link(va.hash_token(token)) if token else None
            if not claimed:
                return vp.signin_page(
                    message="That link has already been used, or it is not valid. "
                            "Ask for a new one."), 400
            email, issued_at = claimed
            if va.link_expired(issued_at):
                return vp.signin_page(
                    message="That link has expired. Ask for a new one."), 400

            person = vs.get_person(email)
            if person:
                role, school = person["role"], person["school"]
                vs.remember_person(email, role, school)
            else:
                role, school = va.default_role(email), ""
                vs.remember_person(email, role, school)
                if role == va.ROLE_PENDING:
                    _tell(":bust_in_silhouette: *%s* signed in to Victory "
                          "Intelligence and has no access yet. Grant it with "
                          "`/vi/grant`." % email)

            value = va.sign_session(email, role, school, secret)
            if not value:
                return vp.signin_page(message="Sign-in failed. Try again."), 500

            resp = make_response(redirect("/vi/"))
            resp.set_cookie(COOKIE, value, max_age=va.SESSION_TTL_SECONDS,
                            httponly=True, samesite="Lax",
                            secure=request.headers.get(
                                "X-Forwarded-Proto", "").startswith("https"),
                            path="/vi")
            print("[VI-AUTH] signed in %s as %s" % (email, role))
            return resp
        except Exception as e:
            _err("vi_auth", e)
            return vp.signin_page(message="Sign-in failed. Try again."), 500

    @app.route("/vi/logout", methods=["GET", "POST"])
    def vi_logout():
        resp = make_response(redirect("/vi/"))
        resp.set_cookie(COOKIE, "", max_age=0, path="/vi")
        return resp

    # ── reading the index ──────────────────────────────────────────────────
    @app.route("/vi/search", methods=["GET", "POST"])
    def vi_search():
        try:
            import victory_index as vi
            admin = _is_admin()
            sess = None if admin else _session()
            if not admin:
                if not sess:
                    return jsonify({"ok": False, "error": "unauthorized"}), 401
                if not va.can_search(sess["role"]):
                    return jsonify({"ok": False, "error": "no access yet",
                                    "pending": True}), 403

            body = request.get_json(force=True, silent=True) or {}
            q = request.values.get("q", body.get("q", ""))
            event = request.values.get("event", body.get("event")) or None
            try:
                limit = int(request.values.get("limit", body.get("limit", 7)))
            except Exception:
                limit = 7
            limit = max(1, min(limit, 50))

            # A cold worker has an empty corpus; load it rather than reporting
            # zero results, which would look like data loss to the caller.
            if vi.corpus_size() == 0:
                vi.load_corpus()

            t0 = time.time()
            out = vi.search(q, event_key=event, limit=limit)
            out["ms"] = int((time.time() - t0) * 1000)
            _annotate_moments(out.get("results") or [])

            if sess:
                vs.log_search(sess["email"], sess["role"], q, event,
                              out.get("found"), out["ms"], _client_ip(request))
            return jsonify(out), 200
        except Exception as e:
            _err("vi_search", e, "q=%r" % (request.values.get("q", ""),))
            return jsonify({"ok": False, "error": "exception"}), 500

    @app.route("/vi/request", methods=["POST"])
    def vi_request():
        """A signed-in person picked some moments and asked for something.

        This is the front of the Phase 3 queue. It stores the ask and tells
        #dev; it does not render anything yet, and the page says so in plain
        words rather than implying a video is on its way.
        """
        try:
            sess = _session()
            if not sess:
                return jsonify({"ok": False, "error": "unauthorized"}), 401
            if not va.can_search(sess["role"]):
                return jsonify({"ok": False, "error": "no access yet"}), 403

            body = request.get_json(force=True, silent=True) or {}
            items = body.get("items") or []
            note = (body.get("note") or "").strip()
            try:
                length_s = int(body.get("length") or 30)
            except (TypeError, ValueError):
                length_s = 30
            if length_s not in (15, 30, 60):
                length_s = 30
            if not isinstance(items, list):
                items = []
            # The person's own words on screen (up to 4 lines) and the end card.
            raw_lines = body.get("lines")
            if isinstance(raw_lines, str):
                raw_lines = raw_lines.splitlines()
            lines = [str(x).strip()[:60] for x in (raw_lines or []) if str(x).strip()][:4]
            cta = str(body.get("cta") or "").strip()[:60]
            text = {"lines": lines, "cta": cta} if (lines or cta) else None
            # Since 14 Sep the machine finds the footage itself: a request may
            # be words alone, moments alone, or both. Never neither.
            if not items and not note:
                return jsonify({"ok": False, "error": "say what you want, or pick a moment"}), 400
            if len(items) > 60:
                return jsonify({"ok": False, "error": "that is too many at once"}), 400

            # Keep only fields we put there. The page is ours, but a request
            # body is a request body — it is not a place to trust shape.
            clean = []
            for it in items[:60]:
                if not isinstance(it, dict):
                    continue
                clean.append({k: str(it.get(k) or "")[:300]
                              for k in ("id", "title", "kind", "file", "quote")})
            if not clean and not note:
                return jsonify({"ok": False, "error": "say what you want, or pick a moment"}), 400

            vs.init_schema()
            rid = vs.create_request(sess["email"], sess["role"],
                                    sess.get("school", ""), note, clean, length_s=length_s, text=text)
            if not rid:
                return jsonify({"ok": False, "error": "could not save the request"}), 500

            lines = "\n".join("   \u2022 %s" % (i["title"] or i["quote"] or i["id"])[:80]
                               for i in clean[:8])
            if len(clean) > 8:
                lines += "\n   \u2026 and %d more" % (len(clean) - 8)
            _tell(":clapper: *Victory Intelligence \u2014 cut #%s requested* by *%s* (%ds)\n"
                  "> %s\n%s"
                  % (rid, sess["email"], length_s, note or "_no note given_",
                     lines or "   _no moments picked \u2014 the machine chooses_"))
            print("[VI] request #%s from %s \u2014 %d items, %ds"
                  % (rid, sess["email"], len(clean), length_s))
            return jsonify({"ok": True, "id": rid, "items": len(clean), "length": length_s}), 200
        except Exception as e:
            _err("vi_request", e)
            return jsonify({"ok": False, "error": "exception"}), 500

    @app.route("/vi/requests", methods=["GET"])
    def vi_requests():
        blocked = _admin_guard()
        if blocked:
            return blocked
        try:
            rows = [_jsonable_request(r) for r in
                    vs.list_requests(limit=int(request.values.get("limit", 50)))]
            return jsonify({"ok": True, "count": len(rows), "requests": rows}), 200
        except Exception as e:
            _err("vi_requests", e)
            return jsonify({"ok": False, "error": "exception"}), 500

    # ── the machine editor: what a person sees ─────────────────────────────
    def _mine(sess, limit=50):
        if _is_mwm(sess):
            rows = vs.list_requests(limit=limit)
        else:
            rows = vs.list_requests_for(sess["email"], limit=limit)
        fb = vs.list_feedback([r["id"] for r in rows])
        out = []
        for r in rows:
            j = _jsonable_request(r)
            j["feedback"] = [{"at": str(f["at"]), "email": f["email"], "text": f["text"]}
                             for f in fb.get(r["id"], [])]
            if j.get("result_drive_id"):
                import victory_drive as vd
                j["preview_url"] = vd.preview_url(j["result_drive_id"])
                j["download_url"] = vd.download_url(j["result_drive_id"])
            out.append(j)
        return out

    @app.route("/vi/mine", methods=["GET"])
    def vi_mine():
        try:
            sess = _session()
            if not sess:
                return jsonify({"ok": False, "error": "unauthorized"}), 401
            if not va.can_search(sess["role"]):
                return jsonify({"ok": False, "error": "no access yet"}), 403
            rows = _mine(sess)
            busy = any(r["state"] in ("asked", "rendering") for r in rows)
            return jsonify({"ok": True, "count": len(rows), "requests": rows, "busy": busy,
                            "all": _is_mwm(sess)}), 200
        except Exception as e:
            _err("vi_mine", e)
            return jsonify({"ok": False, "error": "exception"}), 500

    @app.route("/vi/queue", methods=["GET"])
    def vi_queue():
        try:
            sess = _session()
            if not sess:
                return vp.signin_page()
            if not va.can_search(sess["role"]):
                return vp.pending_page(sess["email"])
            return vp.queue_page(sess["email"], sess["role"], _mine(sess), all_people=_is_mwm(sess))
        except Exception as e:
            _err("vi_queue", e)
            return vp.signin_page(message="Something went wrong. Try again.")

    @app.route("/vi/feedback", methods=["POST"])
    def vi_feedback():
        """A note on a cut. Michael's professional feedback is the whole point
        of the test week, so it is stored, and it is posted to #dev where DEV
        reads it."""
        try:
            sess = _session()
            if not sess:
                return jsonify({"ok": False, "error": "unauthorized"}), 401
            body = request.get_json(force=True, silent=True) or {}
            rid = int(body.get("id") or request.values.get("id") or 0)
            text = (body.get("text") or request.values.get("text") or "").strip()
            if not rid or not text:
                return jsonify({"ok": False, "error": "say something about a specific cut"}), 400
            row = vs.get_request(rid)
            if not row or (row["email"] != sess["email"] and not _is_mwm(sess)):
                return jsonify({"ok": False, "error": "not yours"}), 404
            fid = vs.add_feedback(rid, sess["email"], text)
            if not fid:
                return jsonify({"ok": False, "error": "could not save the note"}), 500
            _tell(":memo: *Victory Intelligence \u2014 feedback on cut #%s* from *%s*\n> %s"
                  % (rid, sess["email"], text[:900]))
            return jsonify({"ok": True, "id": fid}), 200
        except Exception as e:
            _err("vi_feedback", e)
            return jsonify({"ok": False, "error": "exception"}), 500

    @app.route("/vi/decide", methods=["POST"])
    def vi_decide():
        """approve / decline a finished cut, or ask for it again (redo)."""
        try:
            sess = _session()
            if not sess:
                return jsonify({"ok": False, "error": "unauthorized"}), 401
            body = request.get_json(force=True, silent=True) or {}
            rid = int(body.get("id") or 0)
            decision = (body.get("decision") or "").strip().lower()
            row = vs.get_request(rid) if rid else None
            if not row or (row["email"] != sess["email"] and not _is_mwm(sess)):
                return jsonify({"ok": False, "error": "not yours"}), 404
            if decision == "redo":
                # back to the queue; the machine cuts it again (music rotates,
                # and any feedback left meanwhile is on the record)
                ok = vs.set_request_state(rid, "asked", by=sess["email"])
            elif decision in ("approved", "declined"):
                ok = vs.set_request_state(rid, decision, by=sess["email"])
            else:
                return jsonify({"ok": False, "error": "decision must be approved, declined or redo"}), 400
            if not ok:
                return jsonify({"ok": False, "error": "could not record that"}), 500
            _tell(":white_check_mark: Victory Intelligence \u2014 cut #%s marked *%s* by %s"
                  % (rid, decision, sess["email"]))
            return jsonify({"ok": True, "id": rid, "state": "asked" if decision == "redo" else decision}), 200
        except Exception as e:
            _err("vi_decide", e)
            return jsonify({"ok": False, "error": "exception"}), 500

    # ── the machine editor: the worker's side (admin) ──────────────────────
    @app.route("/vi/jobs/next", methods=["GET", "POST"])
    def vi_jobs_next():
        """The Mac worker asks for work. The claim is one UPDATE in the store."""
        blocked = _admin_guard()
        if blocked:
            return blocked
        try:
            worker = (request.values.get("worker") or "worker")[:60]
            vs.init_schema()
            back = vs.requeue_stale()
            if back:
                print("[VI] requeued %d stalled render(s)" % back)
            job = vs.claim_next_request(worker)
            if not job:
                return jsonify({"ok": True, "job": None}), 200
            job = _jsonable_request(job)
            job["recent_music"] = vs.recent_music(job["email"])
            job["recent_clips"] = vs.recent_clips(job["email"])
            if isinstance(job.get("text"), str):
                try:
                    import json as _json
                    job["text"] = _json.loads(job["text"])
                except Exception:
                    job["text"] = None
            print("[VI] job #%s claimed by %s" % (job["id"], worker))
            return jsonify({"ok": True, "job": job}), 200
        except Exception as e:
            _err("vi_jobs_next", e)
            return jsonify({"ok": False, "error": "exception"}), 500

    @app.route("/vi/jobs/<int:rid>/deliver", methods=["POST"])
    def vi_jobs_deliver(rid):
        """The finished file arrives. It goes to Drive; the row goes to 'ready'."""
        blocked = _admin_guard()
        if blocked:
            return blocked
        try:
            import json as _json
            row = vs.get_request(rid)
            if not row:
                return jsonify({"ok": False, "error": "no such request"}), 404
            f = request.files.get("video")
            if f is None:
                return jsonify({"ok": False, "error": "no video in the upload"}), 400
            data = f.read()
            if len(data) < 100_000:
                return jsonify({"ok": False, "error": "that file is too small to be a video"}), 400
            try:
                summary = _json.loads(request.form.get("summary") or "{}")
            except Exception:
                summary = {}
            try:
                seconds = float(request.form.get("seconds") or 0) or None
            except ValueError:
                seconds = None
            name = f.filename or ("VI_req%s.mp4" % rid)
            up = drive_upload(name, data)
            if not up or not up.get("id"):
                vs.finish_request(rid, "failed", summary=summary,
                                  error="rendered, but the upload to Drive failed")
                _tell(":x: Victory Intelligence \u2014 cut #%s rendered but could not be stored in Drive." % rid)
                return jsonify({"ok": False, "error": "drive upload failed"}), 502
            vs.finish_request(rid, "ready", drive_id=up["id"], file_name=name, size=len(data),
                              seconds=seconds, summary=summary, error=None)
            print("[VI] cut #%s ready -> drive %s (%d bytes)" % (rid, up["id"], len(data)))
            _tell(":clapper: *Victory Intelligence \u2014 cut #%s is ready* for %s (%s, %d shots, %s)\n%s"
                  % (rid, row["email"], "%.0fs" % seconds if seconds else "?s",
                     len(summary.get("shots") or []), summary.get("music_title") or "no music",
                     up.get("link", "")))
            return jsonify({"ok": True, "id": rid, "drive_id": up["id"], "link": up.get("link")}), 200
        except Exception as e:
            _err("vi_jobs_deliver", e, "rid=%s" % rid)
            return jsonify({"ok": False, "error": "exception"}), 500

    @app.route("/vi/jobs/<int:rid>/fail", methods=["POST"])
    def vi_jobs_fail(rid):
        blocked = _admin_guard()
        if blocked:
            return blocked
        try:
            body = request.get_json(force=True, silent=True) or {}
            error = (body.get("error") or request.values.get("error") or "unknown")[:2000]
            if not vs.get_request(rid):
                return jsonify({"ok": False, "error": "no such request"}), 404
            vs.finish_request(rid, "failed", error=error)
            _tell(":x: *Victory Intelligence \u2014 cut #%s failed* on %s\n> %s"
                  % (rid, body.get("worker") or "worker", error[:600]))
            return jsonify({"ok": True, "id": rid, "state": "failed"}), 200
        except Exception as e:
            _err("vi_jobs_fail", e, "rid=%s" % rid)
            return jsonify({"ok": False, "error": "exception"}), 500

    @app.route("/vi/jobs/<int:rid>/requeue", methods=["POST"])
    def vi_jobs_requeue(rid):
        """Put a request back in the queue (admin). For DEV during the test
        week: a cut that failed for a reason now fixed, or one worth redoing
        after the editor changed."""
        blocked = _admin_guard()
        if blocked:
            return blocked
        try:
            if not vs.get_request(rid):
                return jsonify({"ok": False, "error": "no such request"}), 404
            if not vs.set_request_state(rid, "asked", by="dev"):
                return jsonify({"ok": False, "error": "could not requeue"}), 500
            print("[VI] cut #%s requeued by admin" % rid)
            return jsonify({"ok": True, "id": rid, "state": "asked"}), 200
        except Exception as e:
            _err("vi_jobs_requeue", e, "rid=%s" % rid)
            return jsonify({"ok": False, "error": "exception"}), 500

    # ── thumbnails and previews ────────────────────────────────────────────
    _media_cache = {}          # (clip_id, kind) -> bytes; posters are small, keep them warm

    def _clip_ids_in_corpus():
        try:
            import victory_ingest as ingest
            out = []
            for ev in ingest.list_events():
                _, _, records = ingest.build_rows(ev, vs.extra_clips(ev))
                out += [r["id"].split(":", 1)[-1] for r in records if r.get("kind") == "clip"]
                # interview moments (the ~30 s pieces the transcript lines map to)
                # want a picture and a preview too
                for m in (_moments(ev).get("moments") or {}).values():
                    f = m.get("file") or ""
                    if f.endswith(".mp4"):
                        out.append(f[:-4])
            return out
        except Exception as e:
            _err("clip_ids_in_corpus", e)
            return []

    _moments_cache = {}

    def _moments(event_key):
        """victory_source/<event>/quote_moments.json, read once: which piece of
        the recording each transcript line was said in, and where in it."""
        if event_key not in _moments_cache:
            try:
                import json as _json
                import os as _os
                import victory_ingest as ingest
                path = _os.path.join(ingest.SOURCE_ROOT, event_key, "quote_moments.json")
                _moments_cache[event_key] = _json.load(open(path, encoding="utf-8")) if _os.path.exists(path) else {}
            except Exception as e:
                _err("moments_index", e)
                _moments_cache[event_key] = {}
        return _moments_cache[event_key]

    def _annotate_moments(results):
        """Give each quote result its moment id and the second the line starts
        at inside it, so the Library can show a picture and play the line."""
        for r in results:
            if r.get("kind") != "quote":
                continue
            rid = str(r.get("id") or "")
            ev, _, nat = rid.partition(":")
            idx = _moments(ev or "") if ev else {}
            q = (idx.get("quotes") or {}).get(nat)
            if not q:
                import re as _re
                q = (idx.get("quotes") or {}).get(_re.sub(r"#\d+$", "", nat))
            if not q:
                continue
            m = (idx.get("moments") or {}).get(q.get("moment"))
            f = (m or {}).get("file") or ""
            if f.endswith(".mp4"):
                r["moment"] = f[:-4]
                r["offset"] = q.get("offset", 0)

    @app.route("/vi/media/missing", methods=["GET"])
    def vi_media_missing():
        """Which clips still need a poster and a preview (admin; the worker asks)."""
        blocked = _admin_guard()
        if blocked:
            return blocked
        try:
            have = vs.media_have()
            ids = [c for c in _clip_ids_in_corpus() if c not in have]
            limit = max(1, min(int(request.values.get("limit", 20)), 500))
            return jsonify({"ok": True, "missing": ids[:limit], "total_missing": len(ids)}), 200
        except Exception as e:
            _err("vi_media_missing", e)
            return jsonify({"ok": False, "error": "exception"}), 500

    @app.route("/vi/media/<clip_id>", methods=["POST"])
    def vi_media_put(clip_id):
        blocked = _admin_guard()
        if blocked:
            return blocked
        try:
            clip_id = clip_id[:200]
            poster = request.files.get("poster")
            preview = request.files.get("preview")
            pb = poster.read() if poster else None
            vb = preview.read() if preview else None
            if not pb and not vb:
                return jsonify({"ok": False, "error": "nothing in the upload"}), 400
            if pb and (len(pb) < 1000 or not pb.startswith(b"\xff\xd8")):
                return jsonify({"ok": False, "error": "poster is not a JPEG"}), 400
            if vb and (len(vb) < 10_000 or len(vb) > 6_000_000):
                return jsonify({"ok": False, "error": "preview size is off"}), 400
            if not vs.media_put(clip_id, pb, vb):
                return jsonify({"ok": False, "error": "could not store"}), 500
            _media_cache.pop((clip_id, "poster"), None)
            _media_cache.pop((clip_id, "preview"), None)
            return jsonify({"ok": True, "clip_id": clip_id,
                            "poster_bytes": len(pb or b""), "preview_bytes": len(vb or b"")}), 200
        except Exception as e:
            _err("vi_media_put", e, clip_id)
            return jsonify({"ok": False, "error": "exception"}), 500

    def _serve_media(clip_id, kind, mime):
        sess = _session()
        if not sess or not va.can_search(sess["role"]):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        key = (clip_id, kind)
        data = _media_cache.get(key)
        if data is None:
            data = vs.media_get(clip_id, kind)
            if data is None:
                return jsonify({"ok": False, "error": "no such media"}), 404
            if kind == "poster" or len(_media_cache) < 60:
                _media_cache[key] = data
        total = len(data)
        rng = request.headers.get("Range", "")
        if rng.startswith("bytes="):
            # iOS video needs Range answered properly, or it will not play
            try:
                a, b = rng[6:].split("-", 1)
                start = int(a) if a else max(0, total - int(b))
                end = int(b) if (a and b) else total - 1
                end = min(end, total - 1)
                if start > end:
                    raise ValueError
                chunk = data[start:end + 1]
                resp = make_response(chunk, 206)
                resp.headers["Content-Range"] = "bytes %d-%d/%d" % (start, end, total)
            except ValueError:
                resp = make_response(b"", 416)
                resp.headers["Content-Range"] = "bytes */%d" % total
        else:
            resp = make_response(data, 200)
        resp.headers["Content-Type"] = mime
        resp.headers["Accept-Ranges"] = "bytes"
        resp.headers["Cache-Control"] = "private, max-age=86400"
        return resp

    @app.route("/vi/thumb/<clip_id>.jpg", methods=["GET"])
    def vi_thumb(clip_id):
        try:
            return _serve_media(clip_id[:200], "poster", "image/jpeg")
        except Exception as e:
            _err("vi_thumb", e, clip_id)
            return jsonify({"ok": False, "error": "exception"}), 500

    @app.route("/vi/preview/<clip_id>.mp4", methods=["GET"])
    def vi_preview(clip_id):
        try:
            return _serve_media(clip_id[:200], "preview", "video/mp4")
        except Exception as e:
            _err("vi_preview", e, clip_id)
            return jsonify({"ok": False, "error": "exception"}), 500

    @app.route("/vi/moments/describe", methods=["POST"])
    def vi_moments_describe():
        """Name one candidate moment from its contact sheet (six frames).

        Admin secret, or a signed-in MWM person: it spends a model call, so
        Victory staff cannot drive it, and the long-recording pipeline that
        uses it runs from our side. Multipart: sheet=<jpeg>, context=<text>."""
        if not _is_admin():
            sess = _session()
            if not sess or sess.get("role") != va.ROLE_MWM:
                return jsonify({"ok": False, "error": "unauthorized"}), 401
        try:
            f = request.files.get("sheet")
            data = f.read(3_000_000) if f else b""
            if not data.startswith(b"\xff\xd8"):
                return jsonify({"ok": False, "error": "a JPEG contact sheet is required"}), 400
            context = str(request.values.get("context") or "")[:300]
            import victory_describe as vd
            out = vd.describe_sheet(data, context, client=app.config.get("VI_DESCRIBE_CLIENT"))
            if not out:
                return jsonify({"ok": False, "error": "no answer"}), 502
            out["ok"] = True
            return jsonify(out), 200
        except Exception as e:
            _err("vi_moments_describe", e)
            return jsonify({"ok": False, "error": "exception"}), 500

    @app.route("/vi/moments/publish", methods=["POST"])
    def vi_moments_publish():
        """The Mini hands over moments it cut and named on its own (admin).

        Body: {"event": "VWC26", "clips": [clip dicts as in clips.json, each
        may carry "reframe": {duration, windows}]}. They are stored, the
        event is re-ingested so the Library sees them, and the worker's
        /vi/moments/published?event= gives them back with their windows."""
        blocked = _admin_guard()
        if blocked:
            return blocked
        try:
            import victory_ingest as ingest
            body = request.get_json(force=True, silent=True) or {}
            event = str(body.get("event") or "")
            items = body.get("clips") or []
            if event not in ingest.list_events():
                return jsonify({"ok": False, "error": "no source folder for %r" % event}), 404
            if not isinstance(items, list) or not items:
                return jsonify({"ok": False, "error": "clips required"}), 400
            clean = []
            for it in items[:500]:
                if not isinstance(it, dict) or not it.get("id") or not it.get("file"):
                    continue
                it = dict(it)
                it["kind"] = "clip"
                it["id"] = str(it["id"])[:200]
                clean.append(it)
            vs.init_schema()
            stored = vs.put_extra_clips(event, clean)
            out = ingest.ingest(event) if stored else {"ok": False, "error": "nothing stored"}
            print("[VI] moments published: %d stored for %s -> %s" % (stored, event, out.get("ok")))
            return jsonify({"ok": bool(out.get("ok")), "stored": stored, "ingest": out}), (200 if out.get("ok") else 500)
        except Exception as e:
            _err("vi_moments_publish", e)
            return jsonify({"ok": False, "error": "exception"}), 500

    @app.route("/vi/moments/published", methods=["GET"])
    def vi_moments_published():
        """The published moments of an event, with their windows (admin; the worker)."""
        blocked = _admin_guard()
        if blocked:
            return blocked
        try:
            event = str(request.values.get("event") or "")
            items = vs.extra_clips(event, with_reframe=True)
            return jsonify({"ok": True, "event": event, "clips": items}), 200
        except Exception as e:
            _err("vi_moments_published", e)
            return jsonify({"ok": False, "error": "exception"}), 500

    @app.route("/vi/card", methods=["GET"])
    def vi_card():
        """A title card as a PNG (admin). The Mac worker fetches two per cut
        because its ffmpeg cannot draw text. See victory_cards."""
        blocked = _admin_guard()
        if blocked:
            return blocked
        try:
            import victory_cards as vc_
            big = (request.values.get("big") or "")[:40]
            small = (request.values.get("small") or "")[:40]
            try:
                y = float(request.values.get("y") or 0.40)
            except ValueError:
                y = 0.40
            try:
                size_big = int(request.values.get("size") or 70)
            except ValueError:
                size_big = 70
            png = vc_.render_card(big, small, y_frac=max(0.05, min(0.9, y)), size_big=max(30, min(120, size_big)))
            if not png:
                return jsonify({"ok": False, "error": "could not render"}), 500
            resp = make_response(png)
            resp.headers["Content-Type"] = "image/png"
            resp.headers["Cache-Control"] = "no-store"
            return resp
        except Exception as e:
            _err("vi_card", e)
            return jsonify({"ok": False, "error": "exception"}), 500

    @app.route("/vi/drive-selftest", methods=["POST"])
    def vi_drive_selftest():
        blocked = _admin_guard()
        if blocked:
            return blocked
        try:
            import victory_drive as vd
            out = vd.selftest()
            return jsonify(out), (200 if out.get("ok") else 502)
        except Exception as e:
            _err("vi_drive_selftest", e)
            return jsonify({"ok": False, "error": "exception"}), 500

    # ── admin ──────────────────────────────────────────────────────────────
    @app.route("/vi/health", methods=["GET"])
    def vi_health():
        blocked = _admin_guard()
        if blocked:
            return blocked
        try:
            import victory_index as vi
            import victory_ingest as ingest
            out = {"ok": True, "corpus": vi.corpus_size(),
                   "resident": vi.resident_count(),
                   "events_on_disk": ingest.list_events(),
                   "db": False, "events": [],
                   "queue": vs.queue_counts(),
                   "auth": {"secret": bool(vs.session_secret(create=False)),
                            "people": len(vs.list_people(limit=500)),
                            "client_email_enabled": va.client_email_enabled(),
                            "send_lock": not va.client_email_enabled()}}
            try:
                import pg_store
                if pg_store.enabled():
                    out["db"] = True
                    with pg_store._conn() as c, c.cursor() as cur:
                        cur.execute(
                            """SELECT e.event_key, e.title, COUNT(r.id)
                                 FROM vi_event e
                                 LEFT JOIN vi_record r ON r.event_key = e.event_key
                             GROUP BY e.event_key, e.title ORDER BY e.event_key""")
                        out["events"] = [{"event": r[0], "title": r[1], "records": r[2]}
                                         for r in cur.fetchall()]
            except Exception as e:
                out["db_error"] = repr(e)
            return jsonify(out), 200
        except Exception as e:
            _err("vi_health", e)
            return jsonify({"ok": False, "error": "exception"}), 500

    @app.route("/vi/ingest", methods=["POST"])
    def vi_ingest():
        blocked = _admin_guard()
        if blocked:
            return blocked
        try:
            import victory_ingest as ingest
            body = request.get_json(force=True, silent=True) or {}
            event = request.values.get("event", body.get("event", ""))
            dry = str(request.values.get("dry_run", body.get("dry_run", ""))).lower() \
                in ("1", "true", "yes")
            if not event:
                return jsonify({"ok": False, "error": "event required",
                                "available": ingest.list_events()}), 400
            if event not in ingest.list_events():
                return jsonify({"ok": False, "error": "no source folder for %r" % event,
                                "available": ingest.list_events()}), 404
            out = ingest.ingest(event, dry_run=dry)
            print("[VI] ingest %s dry=%s -> %s" % (event, dry, out))
            return jsonify(out), (200 if out.get("ok") else 500)
        except Exception as e:
            _err("vi_ingest", e)
            return jsonify({"ok": False, "error": "exception"}), 500

    @app.route("/vi/grant", methods=["POST"])
    def vi_grant():
        """Set someone's role. This is the access decision and it is Michael's."""
        blocked = _admin_guard()
        if blocked:
            return blocked
        try:
            body = request.get_json(force=True, silent=True) or {}
            email = va.normalize_email(request.values.get("email", body.get("email", "")))
            role = (request.values.get("role", body.get("role", "")) or "").strip().lower()
            school = request.values.get("school", body.get("school", "")) or ""
            if not email:
                return jsonify({"ok": False, "error": "a valid email is required"}), 400
            external = va.is_external(email)
            allow_external = str(request.values.get(
                "allow_external", body.get("allow_external", ""))).lower() in ("1", "true", "yes")
            if external and not allow_external:
                # Deliberate friction. A typo in a granted address hands a real
                # account to a stranger, and an address off victoryma.com is
                # exactly where a typo is least likely to be noticed.
                return jsonify({
                    "ok": False,
                    "error": "%s is outside victoryma.com and mwmcreations.com. "
                             "Re-send with allow_external=true to grant it "
                             "anyway." % email,
                    "external": True}), 400
            if role not in va.ROLES:
                return jsonify({"ok": False, "error": "role must be one of %s"
                                % (list(va.ROLES),)}), 400
            if role == va.ROLE_SCHOOL and not school.strip():
                return jsonify({"ok": False,
                                "error": "a school role needs a school"}), 400
            vs.init_schema()
            if not vs.grant(email, role, school):
                return jsonify({"ok": False, "error": "could not write the grant"}), 500
            print("[VI-AUTH] granted %s -> %s %s%s"
                  % (email, role, school, " [EXTERNAL]" if external else ""))
            _tell(":white_check_mark: Victory Intelligence access for *%s* set to "
                  "*%s*%s.%s" % (email, role, (" (%s)" % school) if school else "",
                                 "  :warning: this address is outside "
                                 "victoryma.com." if external else ""))
            return jsonify({"ok": True, "email": email, "role": role,
                            "school": school, "external": external}), 200
        except Exception as e:
            _err("vi_grant", e)
            return jsonify({"ok": False, "error": "exception"}), 500

    @app.route("/vi/people", methods=["GET"])
    def vi_people():
        blocked = _admin_guard()
        if blocked:
            return blocked
        try:
            people = vs.list_people()
            for p in people:
                for k in ("granted_at", "first_seen", "last_seen"):
                    if p.get(k) is not None:
                        p[k] = str(p[k])
            return jsonify({"ok": True, "count": len(people), "people": people,
                            "recent_searches": [
                                {**s, "at": str(s["at"])} for s in vs.recent_searches(25)]
                            }), 200
        except Exception as e:
            _err("vi_people", e)
            return jsonify({"ok": False, "error": "exception"}), 500

    @app.route("/vi/issue-link", methods=["POST"])
    def vi_issue_link():
        """Mint a sign-in link and RETURN it instead of emailing it.

        So the door can be proved end to end without sending mail to a real
        person at Victory. Admin-only, and it mints an ordinary single-use link
        for an ordinary allowed address — there is no privileged path here.
        """
        blocked = _admin_guard()
        if blocked:
            return blocked
        try:
            body = request.get_json(force=True, silent=True) or {}
            email = va.normalize_email(request.values.get("email", body.get("email", "")))
            known = bool(vs.get_person(email)) if email else False
            if not email or not va.is_allowed(email, known=known):
                return jsonify({"ok": False, "error": "a valid allowed email is required"}), 400
            if not va.may_email(email):
                # This route does not send mail, but it hands back a WORKING
                # link. While the lock is on, a client link must not exist in
                # any form — a URL in a log or a chat is still a credential.
                return jsonify({"ok": False, "external": False, "locked": True,
                                "error": "Victory Intelligence is locked to "
                                         "internal testing. Set VI_CLIENT_EMAIL=1 "
                                         "to mint links for client addresses."}), 423
            vs.init_schema()
            token, token_hash = va.new_token()
            if not vs.create_link(token_hash, email, _client_ip(request)):
                return jsonify({"ok": False, "error": "could not store the link"}), 500
            print("[VI-AUTH] issued a link for %s via the admin route "
                  "(not emailed)" % email)
            return jsonify({"ok": True, "email": email,
                            "url": "%s/vi/auth?token=%s" % (_base_url(), token),
                            "expires_in": va.LINK_TTL_SECONDS}), 200
        except Exception as e:
            _err("vi_issue_link", e)
            return jsonify({"ok": False, "error": "exception"}), 500

    return app


def boot():
    """Called once at app start. Creates tables and warms the corpus.

    Never raises: a Victory Intelligence problem must not stop the sales
    machine from booting. Returns the number of records resident.
    """
    n = 0
    try:
        import victory_index as vi
        if vi.init_schema():
            n = vi.load_corpus()
            print("[VI] boot ok — %d records resident" % n)
        else:
            print("[VI] boot: no database, index idle")
    except Exception as e:
        print("[VI] boot failed (non-fatal): %r" % (e,))
    try:
        import victory_store as vs
        if vs.init_schema():
            vs.session_secret()          # provision on first boot
            vs.purge_links()
    except Exception as e:
        print("[VI-AUTH] boot failed (non-fatal): %r" % (e,))
    return n
