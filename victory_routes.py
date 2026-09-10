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


def _client_ip(request):
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr or ""


def register(app, admin_ok, report_error=None, send_email=None, notify=None):
    """Attach the /vi/* routes.

    admin_ok(provided) -> bool          the app's fail-closed admin check
    report_error(where, err, ctx)       the app's error reporter (optional)
    send_email(to, subject, text, html) -> bool   (optional; without it, no
                                        link can be emailed and /vi/login says
                                        so in the log rather than pretending)
    notify(text)                        a line into #dev (optional)
    """
    from flask import request, jsonify, make_response, redirect

    import victory_auth as va
    import victory_store as vs
    import victory_page as vp

    limiter = va.RateLimiter()

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

            if sess:
                vs.log_search(sess["email"], sess["role"], q, event,
                              out.get("found"), out["ms"], _client_ip(request))
            return jsonify(out), 200
        except Exception as e:
            _err("vi_search", e, "q=%r" % (request.values.get("q", ""),))
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
                   "auth": {"secret": bool(vs.session_secret(create=False)),
                            "people": len(vs.list_people(limit=500))}}
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
