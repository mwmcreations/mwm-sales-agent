"""victory_page.py — the pages a person sees.

Kept out of victory_routes.py so the routing logic stays readable and the
markup can change without touching anything that makes a security decision.

WHAT THE FIRST REAL USE TAUGHT US
    Michael signed in on his phone, searched "Night of champions", got 17
    results in 33 ms — and said: "Found a few things, but not sure how to use
    it."

    That is the whole review. The page did its job and stopped. It answered a
    question nobody had finished asking. Three things were wrong:

      1. NO PICTURES. A footage library that shows you filenames is a card
         catalogue. Every clip carries a Drive id, and Drive serves a real
         JPEG thumbnail for it without authentication — so there was never a
         reason for a text list.

      2. NO WAY IN. An empty box on a phone at 11pm is a blank stare. The
         starter chips say what this thing can be asked.

      3. NOWHERE TO GO. You find the moment, and then what? Nothing. The
         shortlist is the answer: tap the moments you want, say what you want
         made, send it. That is the request queue Phase 3 will render from —
         built now, at the front, because the front is where the confusion was.

    A quote and a clip are also no longer shuffled together by default. He
    typed the name of a session and got three walls of transcript before a
    single picture. Footage is the default view; the words are one tap away.
"""

CSS = """
*{box-sizing:border-box;min-width:0}
body{margin:0;background:#f2f3f5;color:#14171a;
 font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Helvetica,Arial,sans-serif;
 -webkit-font-smoothing:antialiased;-webkit-text-size-adjust:100%}
a{color:#12507e}
.wrap{max-width:900px;margin:0 auto;padding:0 16px 120px}
header.cv{background:#14171a;color:#fff;padding:20px 24px}
header.cv .top{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}
header.cv h1{font-size:19px;margin:0;letter-spacing:-.01em;font-weight:700}
header.cv .ev{font-size:11.5px;color:#9aa3ac;letter-spacing:.1em;text-transform:uppercase}
header.cv .who{font-size:12.5px;color:#8b949d;margin-top:6px}
header.cv .who a{color:#c9d0d6}
header.cv .who span.e{color:#8b949d}
main{background:#fff;border:1px solid #e2e5e9;border-top:none;padding:22px 24px 30px}
.searchbar{display:flex;gap:9px;margin:0 0 12px}
input[type=text],input[type=email]{flex:1;font:17px/1.4 inherit;padding:13px 15px;
 border:1px solid #c9ced4;border-radius:4px;background:#fff;color:#14171a;min-width:0;
 -webkit-appearance:none}
input:focus{outline:2px solid #14171a;outline-offset:-1px;border-color:#14171a}
button{font:600 15px/1 inherit;padding:13px 20px;border:0;border-radius:4px;
 background:#14171a;color:#fff;cursor:pointer;white-space:nowrap}
button:disabled{opacity:.45;cursor:default}
.chips{display:flex;gap:7px;flex-wrap:wrap;margin:0 0 16px}
.chip{font:500 13.5px/1 inherit;padding:9px 13px;border:1px solid #d7dbe0;border-radius:100px;
 background:#fff;color:#3b4249;cursor:pointer}
.chip:active{background:#eef0f3}
.chips .lbl{font-size:12.5px;color:#767d85;align-self:center;margin-right:2px}
.tabs{display:flex;gap:0;border-bottom:1px solid #e2e5e9;margin:0 0 4px}
.tab{font:600 14px/1 inherit;padding:11px 15px;background:none;color:#767d85;border:0;
 border-bottom:2px solid transparent;border-radius:0;cursor:pointer}
.tab.on{color:#14171a;border-bottom-color:#C8102E}
.tab .c{font-weight:400;color:#98a0a8;margin-left:5px;font-size:12.5px}
.meta{font-size:13px;color:#767d85;min-height:19px;margin:12px 0 6px}
.row{display:flex;gap:13px;padding:14px 0;border-bottom:1px solid #eceef1;align-items:flex-start}
.row:last-child{border-bottom:0}
.thumb{width:112px;flex:0 0 112px;aspect-ratio:16/9;background:#e6e9ec;border-radius:4px;
 overflow:hidden;position:relative}
.thumb img{width:100%;height:100%;object-fit:cover;display:block}
.thumb.said{background:#fdf6e7;display:flex;align-items:center;justify-content:center}
.thumb.said b{font-size:10.5px;letter-spacing:.1em;color:#8a5a00;font-weight:700}
.thumb .dur{position:absolute;right:4px;bottom:4px;background:rgba(0,0,0,.72);color:#fff;
 font-size:10.5px;padding:1px 5px;border-radius:2px;font-variant-numeric:tabular-nums}
.body{flex:1}
.title{font-weight:650;font-size:15.5px;margin:0 0 3px;line-height:1.35}
.said .title{font-weight:600;font-size:15px}
.sub{font-size:12.5px;color:#767d85;line-height:1.45}
.file{font-size:11px;color:#a3aab1;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
 margin-top:3px;word-break:break-all}
.tag{display:inline-block;font-size:9.5px;letter-spacing:.08em;text-transform:uppercase;
 font-weight:700;padding:2px 6px;border-radius:2px;margin-right:6px;vertical-align:2px}
.tag.hero{background:#fdf0f2;color:#C8102E}
.pick{flex:0 0 auto;width:34px;height:34px;border:1px solid #d7dbe0;background:#fff;color:#3b4249;
 border-radius:100px;font:400 20px/1 inherit;padding:0;cursor:pointer;align-self:center}
.pick.on{background:#14171a;border-color:#14171a;color:#fff}
.empty{padding:30px 0;color:#767d85}
.more{margin:16px 0 0}
.more button{background:#fff;color:#14171a;border:1px solid #d7dbe0;width:100%}
.bar{position:fixed;left:0;right:0;bottom:0;background:#14171a;color:#fff;padding:12px 16px;
 display:none;box-shadow:0 -2px 14px rgba(0,0,0,.18);z-index:20}
.bar.on{display:block}
.bar .in{max-width:900px;margin:0 auto;display:flex;gap:10px;align-items:center}
.bar .n{font-size:14px;flex:1}
.bar .n b{font-size:16px}
.bar button.go{background:#fff;color:#14171a}
.bar button.clr{background:none;color:#9aa3ac;padding:13px 6px;font-weight:500}
.panel{position:fixed;inset:0;background:rgba(20,23,26,.55);display:none;z-index:30;
 align-items:flex-end}
.panel.on{display:flex}
.panel .card{background:#fff;width:100%;max-width:900px;margin:0 auto;border-radius:10px 10px 0 0;
 padding:24px 22px 26px;max-height:88vh;overflow-y:auto}
.panel h2{font-size:19px;margin:0 0 6px;letter-spacing:-.01em}
.panel p.h{font-size:14px;color:#767d85;margin:0 0 16px}
.panel ul{margin:0 0 18px;padding-left:18px;font-size:13.5px;color:#4a5158}
.panel li{margin:0 0 5px}
.panel textarea{width:100%;font:16px/1.5 inherit;padding:13px 14px;border:1px solid #c9ced4;
 border-radius:4px;min-height:92px;resize:vertical;-webkit-appearance:none}
.panel .acts{display:flex;gap:10px;margin-top:16px}
.panel .acts button{flex:1}
.panel .acts button.cancel{background:#fff;color:#3b4249;border:1px solid #d7dbe0}
.done{background:#eef7f2;border-left:3px solid #0f7a4d;padding:16px 18px;margin:0 0 18px;
 font-size:14.5px;color:#14532e}
footer{padding:18px 24px 24px;background:#14171a;color:#767d85;font-size:12px}
@media(max-width:600px){
 header.cv,main,footer{padding-left:16px;padding-right:16px}
 .searchbar{flex-direction:column}.searchbar button{width:100%}
 .thumb{width:92px;flex:0 0 92px}
 .row{gap:11px}
 .pick{width:32px;height:32px}
}
"""

# iOS turns bare email addresses and four-digit years into links, which put
# blue underlines through the header on Michael's phone. Off, explicitly.
NO_AUTOLINK = ('<meta name="format-detection" '
               'content="telephone=no,date=no,address=no,email=no">')


def _shell(title, body, extra=""):
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        + NO_AUTOLINK +
        "<title>%s</title><style>%s</style></head><body>%s%s</body></html>"
        % (title, CSS, body, extra)
    )


def _head(email, event_title="Convention 2026"):
    return ("<header class=\"cv\"><div class=\"top\">"
            "<h1>Victory Intelligence</h1><span class=\"ev\">%s</span></div>"
            "<div class=\"who\"><span class=\"e\">%s</span> &middot; "
            "<a href=\"/vi/logout\">sign out</a></div></header>"
            % (event_title, email))


def signin_page(sent=False, message=""):
    """The door. Says the same thing whether or not the address is known."""
    if sent:
        inner = (
            "<div style=\"max-width:430px\">"
            "<h2 style=\"font-size:21px;margin:0 0 12px\">Check your email</h2>"
            "<p style=\"color:#4a5158\">If that address can use Victory "
            "Intelligence, a sign-in link is on its way. It works once and "
            "expires in 15 minutes.</p>"
            "<p style=\"font-size:13px;color:#767d85\">Nothing arrived? Check "
            "spam, then try again.</p></div>")
    else:
        warn = ("<div class=\"done\" style=\"background:#fdf6e7;"
                "border-left-color:#8a5a00;color:#5c4a1e\">%s</div>" % message) if message else ""
        inner = (
            "<div style=\"max-width:430px\">"
            "<h2 style=\"font-size:21px;margin:0 0 12px\">Sign in</h2>"
            "<p style=\"color:#4a5158\">Enter your Victory email address and we "
            "will send you a link. There is no password to remember.</p>"
            + warn +
            "<form method=\"post\" action=\"/vi/login\">"
            "<div class=\"searchbar\">"
            "<input type=\"email\" name=\"email\" required autofocus "
            "autocomplete=\"email\" placeholder=\"you@victoryma.com\">"
            "<button type=\"submit\">Send link</button></div></form>"
            "<p style=\"font-size:13px;color:#767d85\">Access is granted by MWM. "
            "If you sign in and see nothing yet, that is why.</p></div>")
    body = ("<div class=\"wrap\"><header class=\"cv\"><div class=\"top\">"
            "<h1>Victory Intelligence</h1>"
            "<span class=\"ev\">MWM Creations &amp; Studios</span></div></header>"
            "<main>" + inner + "</main>"
            "<footer>Built by MWM Creations &amp; Studios for Victory Martial Arts.</footer>"
            "</div>")
    return _shell("Victory Intelligence — sign in", body)


def pending_page(email):
    inner = (
        "<div style=\"max-width:460px\">"
        "<h2 style=\"font-size:21px;margin:0 0 12px\">You are signed in</h2>"
        "<p style=\"color:#4a5158\">We have not been told what "
        "<strong>%s</strong> should be able to see yet, so there is nothing "
        "here for the moment.</p>"
        "<p style=\"color:#4a5158\">MWM has been notified. Once access is "
        "granted this page will show the library — no need to sign in "
        "again.</p></div>" % email)
    body = ("<div class=\"wrap\">" + _head(email, "Convention 2026") +
            "<main>%s</main>"
            "<footer>Built by MWM Creations &amp; Studios for Victory Martial Arts.</footer>"
            "</div>" % inner)
    return _shell("Victory Intelligence", body)


# The starter chips. Chosen to show the four things it can be asked for:
# a subject, a person speaking, an editorial peak, and a specific session.
CHIPS = ["candlelight", "why parents enrolled", "night of champions",
         "kids cheering", "on perseverance", "board break", "black belt testing"]

APP_JS = r"""
<script>
(function(){
  var q=document.getElementById('q'), go=document.getElementById('go'),
      out=document.getElementById('out'), meta=document.getElementById('meta'),
      tabs=document.getElementById('tabs'), more=document.getElementById('more'),
      bar=document.getElementById('bar'), barn=document.getElementById('barn'),
      panel=document.getElementById('panel'), note=document.getElementById('note'),
      picked={}, rows=[], shown=0, kind='clip', timer=null, seq=0, PAGE=12;

  function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}

  function thumb(r){
    if(r.kind==='clip' && r.drive_id){
      return '<div class="thumb"><img loading="lazy" alt="" src="https://drive.google.com/thumbnail?id='
        + esc(r.drive_id) + '&sz=w400">' + (r.duration ? '<span class="dur">'+esc(r.duration)+'</span>' : '') + '</div>';
    }
    if(r.kind==='clip') return '<div class="thumb"></div>';
    return '<div class="thumb said"><b>SAID</b></div>';
  }

  function row(r){
    var isClip = r.kind==='clip';
    var hero = (r.priority==='hero') ? '<span class="tag hero">Hero</span>' : '';
    var title = isClip ? esc(r.title) : '&ldquo;' + esc(r.quote || r.title) + '&rdquo;';
    var bits = [];
    if (r.day_no) bits.push('Day ' + r.day_no);
    if (r.session) bits.push(esc(r.session));
    if (r.camera) bits.push(esc(r.camera));
    if (!isClip && r.timecode) bits.push(esc(r.timecode));
    var link = r.drive_id ? ' &middot; <a href="https://drive.google.com/file/d/'
      + esc(r.drive_id) + '/view" target="_blank" rel="noopener">open</a>' : '';
    var on = picked[r.id] ? ' on' : '';
    return '<div class="row' + (isClip?'':' said') + '">' + thumb(r) +
      '<div class="body"><div class="title">' + hero + title + '</div>' +
      '<div class="sub">' + bits.join(' &middot; ') + link + '</div>' +
      (r.file ? '<div class="file">' + esc(r.file) + '</div>' : '') +
      '</div><button class="pick' + on + '" data-id="' + esc(r.id) + '" ' +
      'aria-label="add to list">' + (picked[r.id] ? '&#10003;' : '+') + '</button></div>';
  }

  function counts(){
    var c=0,s=0; rows.forEach(function(r){ r.kind==='clip' ? c++ : s++; });
    return {clip:c, quote:s, all:rows.length};
  }

  function visible(){
    if(kind==='all') return rows;
    return rows.filter(function(r){ return r.kind===kind; });
  }

  function paint(){
    var v = visible(), n = counts();
    tabs.innerHTML =
      tab('clip','Footage',n.clip) + tab('quote','What people said',n.quote) + tab('all','Everything',n.all);
    var slice = v.slice(0, shown);
    out.innerHTML = slice.length ? slice.map(row).join('')
      : '<div class="empty">Nothing here for that. Try another word, or check the other tab.</div>';
    more.innerHTML = (v.length > shown)
      ? '<button id="moreb">Show ' + Math.min(PAGE, v.length-shown) + ' more of ' + v.length + '</button>' : '';
    var mb=document.getElementById('moreb');
    if(mb) mb.onclick=function(){ shown += PAGE; paint(); };
  }

  function tab(k,label,n){
    return '<button class="tab' + (kind===k?' on':'') + '" data-k="' + k + '">' +
      label + '<span class="c">' + n + '</span></button>';
  }

  tabs.addEventListener('click', function(e){
    var t=e.target.closest('.tab'); if(!t) return;
    kind=t.getAttribute('data-k'); shown=PAGE; paint();
  });

  out.addEventListener('click', function(e){
    var b=e.target.closest('.pick'); if(!b) return;
    var id=b.getAttribute('data-id');
    if(picked[id]) delete picked[id];
    else {
      var found=null; rows.forEach(function(r){ if(r.id===id) found=r; });
      if(found) picked[id]=found;
    }
    paint(); painBar();
  });

  function painBar(){
    var n=Object.keys(picked).length;
    bar.className = n ? 'bar on' : 'bar';
    barn.innerHTML = '<b>' + n + '</b> moment' + (n===1?'':'s') + ' picked';
  }

  document.getElementById('clr').onclick=function(){ picked={}; paint(); painBar(); };
  document.getElementById('ask').onclick=function(){ panel.className='panel on'; note.focus(); };
  document.getElementById('cancel').onclick=function(){ panel.className='panel'; };

  document.getElementById('send').onclick=function(){
    var ids=Object.keys(picked), b=this;
    if(!ids.length) return;
    b.disabled=true; b.textContent='Sending…';
    fetch('/vi/request', {method:'POST', credentials:'same-origin',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({note: note.value, items: ids.map(function(i){
        return {id:i, title: picked[i].title, kind: picked[i].kind,
                file: picked[i].file, quote: picked[i].quote}; })})})
    .then(function(r){ return r.json(); })
    .then(function(d){
      b.disabled=false; b.textContent='Send to MWM';
      if(!d.ok){ alert('That did not send. Try again in a moment.'); return; }
      panel.className='panel'; picked={}; note.value='';
      paint(); painBar();
      meta.innerHTML = '<span style="color:#0f7a4d;font-weight:600">Sent to MWM. ' +
        'We will come back to you.</span>';
    })
    .catch(function(){ b.disabled=false; b.textContent='Send to MWM';
      alert('That did not send. Try again in a moment.'); });
  };

  function run(){
    var term=q.value, mine=++seq;
    if(!term.trim()){ rows=[]; out.innerHTML=''; tabs.innerHTML=''; more.innerHTML='';
      meta.textContent=''; return; }
    meta.textContent='Searching…';
    fetch('/vi/search?limit=60&q=' + encodeURIComponent(term), {credentials:'same-origin'})
      .then(function(r){ return r.json(); })
      .then(function(d){
        if(mine!==seq) return;
        if(!d.ok){ meta.textContent='Something went wrong.'; return; }
        rows = d.results || [];
        shown = PAGE;
        if(!rows.some(function(r){return r.kind==='clip';})) kind='quote';
        else if(kind==='quote' && rows.some(function(r){return r.kind==='clip';})) kind='clip';
        paint();
        meta.innerHTML = d.fallback
          ? 'No direct match — showing the strongest moments instead'
          : d.found + ' moment' + (d.found===1?'':'s') + ' found in ' + d.ms + ' ms';
      })
      .catch(function(){ if(mine===seq) meta.textContent='Could not reach the index.'; });
  }

  q.addEventListener('input', function(){ clearTimeout(timer); timer=setTimeout(run,200); });
  go.addEventListener('click', run);
  q.addEventListener('keydown', function(e){ if(e.key==='Enter'){ clearTimeout(timer); q.blur(); run(); }});
  document.getElementById('chips').addEventListener('click', function(e){
    var c=e.target.closest('.chip'); if(!c) return;
    q.value=c.textContent; run(); window.scrollTo(0,0);
  });
})();
</script>
"""


def app_page(email, role, event_title="Convention 2026", records=0):
    chips = "".join("<button class=\"chip\">%s</button>" % c for c in CHIPS)
    body = (
        "<div class=\"wrap\">" + _head(email, event_title) +
        "<main>"
        "<div class=\"searchbar\">"
        "<input type=\"text\" id=\"q\" autocomplete=\"off\" autocorrect=\"off\" "
        "placeholder=\"What are you looking for?\">"
        "<button id=\"go\">Search</button></div>"
        "<div class=\"chips\" id=\"chips\"><span class=\"lbl\">Try:</span>" + chips + "</div>"
        "<div class=\"tabs\" id=\"tabs\"></div>"
        "<div class=\"meta\" id=\"meta\"></div>"
        "<div id=\"out\"></div>"
        "<div class=\"more\" id=\"more\"></div>"
        "</main>"
        "<footer>%s moments from %s &middot; every result names the session and "
        "camera it came from.</footer>"
        "</div>"

        "<div class=\"bar\" id=\"bar\"><div class=\"in\">"
        "<span class=\"n\" id=\"barn\"></span>"
        "<button class=\"clr\" id=\"clr\">Clear</button>"
        "<button class=\"go\" id=\"ask\">Ask for a cut</button>"
        "</div></div>"

        "<div class=\"panel\" id=\"panel\"><div class=\"card\">"
        "<h2>Ask MWM for a cut</h2>"
        "<p class=\"h\">Your picked moments go with this. Say what you want made "
        "and we will come back to you.</p>"
        "<ul>"
        "<li>Say where it is going — Instagram, a screen in the lobby, an email.</li>"
        "<li>Say how long, if you mind. Fifteen to thirty seconds is our usual.</li>"
        "<li>Say who it is for — parents, students, a specific school.</li>"
        "</ul>"
        "<textarea id=\"note\" placeholder=\"A 30-second reel for the Lake Nona "
        "page, aimed at parents — the candlelight moments, no music over the "
        "talking.\"></textarea>"
        "<div class=\"acts\">"
        "<button class=\"cancel\" id=\"cancel\">Cancel</button>"
        "<button id=\"send\">Send to MWM</button>"
        "</div></div></div>"
        % ("{:,}".format(records), event_title)
    )
    return _shell("Victory Intelligence", body, APP_JS)
