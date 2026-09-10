"""victory_page.py — the two pages a person sees.

Kept out of victory_routes.py so the routing logic stays readable and the
markup can be changed without touching anything that makes a security
decision.

The design brief is narrow on purpose. This is not the demo — the demo had to
persuade a room. This has to be usable at 7am by a school director on a phone
who wants one clip. So: one field, results that say what they are and where
they came from, and nothing that needs explaining.

Every result row states its session, day and camera. That provenance is the
whole reason to trust the thing, and it comes from the camera-card join rather
than from anyone's memory.
"""

CSS = """
*{box-sizing:border-box;min-width:0}
body{margin:0;background:#f2f3f5;color:#14171a;
 font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Helvetica,Arial,sans-serif;
 -webkit-font-smoothing:antialiased}
a{color:#12507e}
.wrap{max-width:860px;margin:0 auto;padding:0 18px 80px}
header.cv{background:#14171a;color:#fff;padding:26px 30px;display:flex;
 align-items:baseline;gap:14px;flex-wrap:wrap}
header.cv h1{font-size:19px;margin:0;letter-spacing:-.01em;font-weight:700}
header.cv .ev{font-size:12px;color:#9aa3ac;letter-spacing:.1em;text-transform:uppercase}
header.cv .who{margin-left:auto;font-size:13px;color:#9aa3ac}
header.cv .who a{color:#d5dade}
main{background:#fff;border:1px solid #e2e5e9;border-top:none;padding:30px}
.searchbar{display:flex;gap:10px;margin:0 0 8px}
input[type=text],input[type=email]{flex:1;font:17px/1.4 inherit;padding:13px 15px;
 border:1px solid #c9ced4;border-radius:3px;background:#fff;color:#14171a;min-width:0}
input:focus{outline:2px solid #14171a;outline-offset:-1px;border-color:#14171a}
button{font:600 15px/1 inherit;padding:13px 22px;border:0;border-radius:3px;
 background:#14171a;color:#fff;cursor:pointer;white-space:nowrap}
button:disabled{opacity:.5;cursor:default}
.meta{font-size:13px;color:#767d85;min-height:20px;margin:0 0 18px}
.row{display:flex;gap:14px;padding:15px 0;border-bottom:1px solid #eceef1;align-items:baseline}
.row:last-child{border-bottom:0}
.row .body{flex:1}
.row .title{font-weight:650;font-size:15.5px;margin:0 0 3px}
.row .sub{font-size:13px;color:#767d85}
.row .file{font-size:11.5px;color:#98a0a8;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
 margin-top:3px;word-break:break-all}
.row .right{font-size:12px;color:#767d85;text-align:right;white-space:nowrap}
.tag{display:inline-block;font-size:10px;letter-spacing:.08em;text-transform:uppercase;
 font-weight:700;padding:2px 7px;border-radius:2px;margin-right:7px;vertical-align:1px}
.tag.clip{background:#eef4fa;color:#12507e}
.tag.quote{background:#fdf6e7;color:#8a5a00}
.tag.hero{background:#fdf0f2;color:#C8102E}
.empty{padding:34px 0;color:#767d85}
.note{background:#fdf6e7;border-left:3px solid #8a5a00;padding:14px 18px;
 margin:0 0 22px;font-size:14px;color:#5c4a1e}
.note b{color:#14171a}
.signin{max-width:420px;margin:0 auto;padding:14px 0 6px}
.signin p{color:#4a5158;font-size:15px}
.hint{font-size:13px;color:#767d85;margin-top:16px}
footer{padding:20px 30px 26px;background:#14171a;color:#767d85;font-size:12px;
 border:1px solid #14171a;border-top:none}
@media(max-width:600px){header.cv,main,footer{padding-left:18px;padding-right:18px}
 .searchbar{flex-direction:column}button{width:100%}
 .row{flex-direction:column;gap:4px}.row .right{text-align:left}}
"""


def _shell(title, body, extra_js=""):
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>%s</title><style>%s</style></head><body>%s%s</body></html>"
        % (title, CSS, body, extra_js)
    )


def signin_page(sent=False, message=""):
    """The door. Says the same thing whether or not the address is known."""
    if sent:
        inner = (
            "<div class=\"signin\">"
            "<h2 style=\"font-size:21px;margin:0 0 12px\">Check your email</h2>"
            "<p>If that address can use Victory Intelligence, a sign-in link is "
            "on its way. It works once and expires in 15 minutes.</p>"
            "<p class=\"hint\">Nothing arrived? Check spam, then try again — or "
            "reply to whoever sent you here.</p>"
            "</div>")
    else:
        warn = ("<div class=\"note\">%s</div>" % message) if message else ""
        inner = (
            "<div class=\"signin\">"
            "<h2 style=\"font-size:21px;margin:0 0 12px\">Sign in</h2>"
            "<p>Enter your Victory email address and we will send you a link. "
            "There is no password to remember.</p>"
            + warn +
            "<form method=\"post\" action=\"/vi/login\">"
            "<div class=\"searchbar\">"
            "<input type=\"email\" name=\"email\" required autofocus "
            "autocomplete=\"email\" placeholder=\"you@victoryma.com\">"
            "<button type=\"submit\">Send link</button>"
            "</div></form>"
            "<p class=\"hint\">Access is granted by MWM. If you sign in and see "
            "nothing yet, that is why — we will have been told.</p>"
            "</div>")
    body = ("<div class=\"wrap\">"
            "<header class=\"cv\"><h1>Victory Intelligence</h1>"
            "<span class=\"ev\">MWM Creations &amp; Studios</span></header>"
            "<main>" + inner + "</main>"
            "<footer>Built by MWM Creations &amp; Studios for Victory Martial Arts.</footer>"
            "</div>")
    return _shell("Victory Intelligence — sign in", body)


def pending_page(email):
    inner = (
        "<div class=\"signin\">"
        "<h2 style=\"font-size:21px;margin:0 0 12px\">You are signed in</h2>"
        "<p>We have not been told what <strong>%s</strong> should be able to "
        "see yet, so there is nothing here for the moment.</p>"
        "<p>MWM has been notified. Once access is granted this page will show "
        "the convention library — no need to sign in again.</p>"
        "</div>" % email)
    body = ("<div class=\"wrap\">"
            "<header class=\"cv\"><h1>Victory Intelligence</h1>"
            "<span class=\"ev\">MWM Creations &amp; Studios</span>"
            "<span class=\"who\">%s · <a href=\"/vi/logout\">sign out</a></span>"
            "</header><main>%s</main>"
            "<footer>Built by MWM Creations &amp; Studios for Victory Martial Arts.</footer>"
            "</div>" % (email, inner))
    return _shell("Victory Intelligence", body)


APP_JS = """
<script>
(function(){
  var q=document.getElementById('q'), go=document.getElementById('go'),
      out=document.getElementById('out'), meta=document.getElementById('meta'),
      timer=null, seq=0;

  function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}

  function row(r){
    var isClip = r.kind === 'clip';
    var tag = isClip ? '<span class="tag clip">Clip</span>'
                     : '<span class="tag quote">Said</span>';
    var hero = (r.priority === 'hero') ? '<span class="tag hero">Hero</span>' : '';
    var title = isClip ? esc(r.title) : '&ldquo;' + esc(r.quote || r.title) + '&rdquo;';
    var bits = [];
    if (r.day_no) bits.push('Day ' + r.day_no);
    if (r.session) bits.push(esc(r.session));
    if (r.camera) bits.push(esc(r.camera));
    var right = esc(r.duration || '');
    if (r.timecode) right = esc(r.timecode) + '<br>' + right;
    var link = r.drive_id
      ? ' &middot; <a href="https://drive.google.com/file/d/' + esc(r.drive_id) +
        '/view" target="_blank" rel="noopener">open</a>' : '';
    return '<div class="row"><div class="body"><div class="title">' + tag + hero +
      title + '</div><div class="sub">' + bits.join(' &middot; ') + link +
      '</div>' + (r.file ? '<div class="file">' + esc(r.file) + '</div>' : '') +
      '</div><div class="right">' + right + '</div></div>';
  }

  function run(){
    var term = q.value, mine = ++seq;
    if (!term.trim()){ out.innerHTML=''; meta.textContent=''; return; }
    meta.textContent = 'Searching\\u2026';
    fetch('/vi/search?limit=12&q=' + encodeURIComponent(term), {credentials:'same-origin'})
      .then(function(r){ return r.json(); })
      .then(function(d){
        if (mine !== seq) return;              // a later keystroke already won
        if (!d.ok){ meta.textContent = 'Something went wrong.'; return; }
        var rows = d.results || [];
        out.innerHTML = rows.length ? rows.map(row).join('')
          : '<div class="empty">Nothing in the convention matches that yet.</div>';
        meta.innerHTML = d.fallback
          ? 'No direct match \\u2014 showing the strongest moments instead'
          : d.found + ' moment' + (d.found===1?'':'s') + ' found in ' + d.ms +
            ' ms &nbsp;\\u00b7&nbsp; showing ' + rows.length;
      })
      .catch(function(){ if (mine===seq) meta.textContent = 'Could not reach the index.'; });
  }

  q.addEventListener('input', function(){ clearTimeout(timer); timer=setTimeout(run,180); });
  go.addEventListener('click', run);
  q.addEventListener('keydown', function(e){ if(e.key==='Enter'){ clearTimeout(timer); run(); }});
})();
</script>
"""


def app_page(email, role, event_title="Convention 2026", records=0):
    body = (
        "<div class=\"wrap\">"
        "<header class=\"cv\"><h1>Victory Intelligence</h1>"
        "<span class=\"ev\">%s</span>"
        "<span class=\"who\">%s &middot; <a href=\"/vi/logout\">sign out</a></span>"
        "</header>"
        "<main>"
        "<div class=\"searchbar\">"
        "<input type=\"text\" id=\"q\" autofocus autocomplete=\"off\" "
        "placeholder=\"candlelight &middot; why parents enrolled &middot; night of champions\">"
        "<button id=\"go\">Search</button></div>"
        "<div class=\"meta\" id=\"meta\"></div>"
        "<div id=\"out\"></div>"
        "</main>"
        "<footer>%s indexed moments from %s &middot; every result names the "
        "session and camera it came from.</footer>"
        "</div>" % (event_title, email, "{:,}".format(records), event_title)
    )
    return _shell("Victory Intelligence", body, APP_JS)
