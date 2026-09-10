"""victory_routes.py — Patch #129: the Victory Intelligence HTTP surface.

Registered from app.py with a single call, so the 24k-line app file gains six
lines rather than three hundred, and this surface can be reasoned about on its
own.

    /vi/health   what the index holds right now
    /vi/search   ranked results for a query
    /vi/ingest   load an event from victory_source/ (admin)

AUTH, HONESTLY: every route here is gated on UPLOAD_SECRET via the existing
_admin_secret_ok, which fails closed. That is deliberately a placeholder. It is
the right gate for Phase 1 — the index is Victory's material and must not be
open to the internet while we build — and it is the WRONG gate for Victory
staff, who are never going to hold an admin secret. Phase 2 replaces it with an
emailed sign-in link scoped to @victoryma.com and puts a session in front of
these same handlers. Nothing else about them changes.

Until then: no route here is linked from anywhere, and none of them mutate
client-visible state.
"""
import os
import time


def register(app, admin_ok, report_error=None):
    """Attach the /vi/* routes to the Flask app.

    admin_ok(provided) -> bool      the app's existing fail-closed admin check
    report_error(where, err, ctx)   the app's error reporter, optional
    """
    from flask import request, jsonify

    def _err(where, exc, ctx=""):
        try:
            if report_error:
                report_error(where, exc, ctx)
            else:
                print("[VI] %s: %r %s" % (where, exc, ctx))
        except Exception:
            pass

    def _secret_from_request():
        # querystring, form, or JSON body — same shape as the app's other
        # admin routes, so operators do not have to remember a new convention.
        s = request.values.get("secret", "")
        if not s:
            body = request.get_json(force=True, silent=True) or {}
            s = body.get("secret", "")
        return s

    def _guard():
        if not admin_ok(_secret_from_request()):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        return None

    @app.route("/vi/health", methods=["GET"])
    def vi_health():
        blocked = _guard()
        if blocked:
            return blocked
        try:
            import victory_index as vi
            import victory_ingest as ingest
            out = {
                "ok": True,
                "corpus": vi.corpus_size(),
                "events_on_disk": ingest.list_events(),
                "db": False,
                "events": [],
            }
            try:
                import pg_store
                if pg_store.enabled():
                    out["db"] = True
                    with pg_store._conn() as c, c.cursor() as cur:
                        cur.execute(
                            """SELECT e.event_key, e.title, COUNT(r.id)
                                 FROM vi_event e
                                 LEFT JOIN vi_record r ON r.event_key = e.event_key
                             GROUP BY e.event_key, e.title
                             ORDER BY e.event_key""")
                        out["events"] = [{"event": r[0], "title": r[1], "records": r[2]}
                                         for r in cur.fetchall()]
            except Exception as e:
                out["db_error"] = repr(e)
            return jsonify(out), 200
        except Exception as e:
            _err("vi_health", e)
            return jsonify({"ok": False, "error": "exception"}), 500

    @app.route("/vi/search", methods=["GET", "POST"])
    def vi_search():
        blocked = _guard()
        if blocked:
            return blocked
        try:
            import victory_index as vi
            body = request.get_json(force=True, silent=True) or {}
            q = request.values.get("q", body.get("q", ""))
            event = request.values.get("event", body.get("event")) or None
            try:
                limit = int(request.values.get("limit", body.get("limit", 7)))
            except Exception:
                limit = 7
            limit = max(1, min(limit, 50))

            # A cold worker has an empty corpus; load it rather than reporting
            # zero results, which would look like a data loss to the caller.
            if vi.corpus_size() == 0:
                vi.load_corpus()

            t0 = time.time()
            out = vi.search(q, event_key=event, limit=limit)
            out["ms"] = int((time.time() - t0) * 1000)
            return jsonify(out), 200
        except Exception as e:
            _err("vi_search", e, "q=%r" % (request.values.get("q", ""),))
            return jsonify({"ok": False, "error": "exception"}), 500

    @app.route("/vi/ingest", methods=["POST"])
    def vi_ingest():
        blocked = _guard()
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

    return app


def boot():
    """Called once at app start. Creates tables and warms the corpus.

    Never raises: a Victory Intelligence problem must not stop the sales
    machine from booting. Returns the number of records resident.
    """
    try:
        import victory_index as vi
        if vi.init_schema():
            n = vi.load_corpus()
            print("[VI] boot ok — %d records resident" % n)
            return n
        print("[VI] boot: no database, index idle")
        return 0
    except Exception as e:
        print("[VI] boot failed (non-fatal): %r" % e)
        return 0
