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
nav.sub{background:#1f2429;padding:0 24px;display:flex;gap:4px}
nav.sub a{color:#9aa3ac;text-decoration:none;font:600 13.5px/1 inherit;padding:13px 12px;
 border-bottom:2px solid transparent}
nav.sub a.on{color:#fff;border-bottom-color:#C8102E}
nav.sub a .n{display:inline-block;background:#C8102E;color:#fff;border-radius:100px;font-size:11px;
 padding:2px 7px;margin-left:6px;vertical-align:1px}
.lbl2{display:block;font-size:13.5px;font-weight:600;color:#3b4249;margin:12px 0 5px}
.lbl2 span{font-weight:400;color:#767d85;font-size:12.5px}
.panel textarea.short{min-height:64px}
.panel input[type=text]{width:100%;font:16px/1.4 inherit;padding:11px 14px;border:1px solid #c9ced4;
 border-radius:4px;margin:0 0 12px;-webkit-appearance:none}
.len{display:flex;gap:8px;margin:0 0 14px;flex-wrap:wrap;align-items:center}
.len span{font-size:13px;color:#767d85;margin-right:4px}
.len label{font:600 14px/1 inherit;padding:10px 14px;border:1px solid #d7dbe0;border-radius:100px;
 cursor:pointer;color:#3b4249;background:#fff}
.len input{display:none}
.len input:checked+label{background:#14171a;color:#fff;border-color:#14171a}
.mk{margin:0 0 16px}
.mk button{width:100%;background:#C8102E}
.req{border:1px solid #e2e5e9;border-radius:8px;padding:18px 20px;margin:0 0 18px}
.req .hd{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:baseline}
.req .id{font-size:12.5px;color:#767d85}
.req .id b{color:#14171a;font-size:14px}
.status{display:inline-block;font-size:12px;letter-spacing:.06em;text-transform:uppercase;font-weight:700;
 padding:4px 9px;border-radius:3px;background:#f2f3f5;color:#3b4249}
.status.asked,.status.rendering{background:#fff3ea;color:#a3400a}
.status.ready{background:#eef7f2;color:#0f7a4d}
.status.approved,.status.delivered{background:#eef2fb;color:#1f4fa3}
.status.failed,.status.declined{background:#fdf0f2;color:#C8102E}
.ask{font-size:17px;font-weight:650;margin:10px 0 4px;line-height:1.4}
.from{font-size:13px;color:#767d85;margin:0 0 12px}
.moments{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 14px}
.m .t{font-size:12.5px;font-weight:600;padding:6px 10px;border:1px solid #d7dbe0;border-radius:100px;
 color:#3b4249;background:#fff}
.player{width:100%;max-width:300px;aspect-ratio:9/16;border:0;border-radius:6px;background:#14171a;
 display:block;margin:0 0 12px}
.summ{font-size:12.5px;color:#767d85;margin:0 0 12px;line-height:1.5}
.fb{margin:14px 0 0;border-top:1px solid #eceef1;padding-top:12px}
.fb .note{background:#f7f8fa;border-left:3px solid #c9ced4;padding:8px 12px;font-size:14px;color:#3b4249;
 margin:0 0 8px;white-space:pre-wrap}
.fb .note small{display:block;color:#98a0a8;font-size:11.5px;margin-top:2px}
.fb textarea{width:100%;font:15px/1.5 inherit;padding:11px 13px;border:1px solid #c9ced4;border-radius:4px;
 min-height:70px;resize:vertical;-webkit-appearance:none;margin:0 0 8px}
.acts{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.acts button.sec{background:#fff;color:#14171a;border:1px solid #d7dbe0}
.acts button.quiet{background:none;color:#767d85;border:0;padding:12px 8px;font-weight:500}
.acts a.dl{font-size:14px;font-weight:600}
.spin{display:inline-block;width:14px;height:14px;border:2px solid #f3c9a6;border-top-color:#a3400a;
 border-radius:100px;animation:sp 1s linear infinite;vertical-align:-2px;margin-right:6px}
@keyframes sp{to{transform:rotate(360deg)}}
.errbox{background:#fdf0f2;border-left:3px solid #C8102E;padding:10px 14px;font-size:13.5px;color:#7a1020;
 margin:0 0 12px;white-space:pre-wrap}
@media(max-width:600px){
 nav.sub{padding-left:16px;padding-right:16px}
 .m{width:calc(33% - 7px)}
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


def _head(email, event_title="Convention 2026", tab="library", badge=0):
    b = ("<span class=\"n\">%d</span>" % badge) if badge else ""
    return ("<header class=\"cv\"><div class=\"top\">"
            "<h1>Victory Intelligence</h1><span class=\"ev\">%s</span></div>"
            "<div class=\"who\"><span class=\"e\">%s</span> &middot; "
            "<a href=\"/vi/logout\">sign out</a></div></header>"
            "<nav class=\"sub\"><a href=\"/vi/\"%s>Library</a>"
            "<a href=\"/vi/queue\"%s>My videos%s</a></nav>"
            % (event_title, email,
               " class=\"on\"" if tab == "library" else "",
               " class=\"on\"" if tab == "queue" else "", b))


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

  document.getElementById('mkbtn').onclick=function(){ panel.className='panel on'; note.focus(); };
  function chosenLength(){
    var r=document.querySelector('input[name=len]:checked'); return r ? parseInt(r.value,10) : 30;
  }
  document.getElementById('send').onclick=function(){
    var ids=Object.keys(picked), b=this;
    if(!ids.length && !note.value.trim()){ note.focus(); return; }
    b.disabled=true; b.textContent='Sending…';
    fetch('/vi/request', {method:'POST', credentials:'same-origin',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({note: note.value, length: chosenLength(),
        lines: document.getElementById('lines').value, cta: document.getElementById('cta').value,
        items: ids.map(function(i){
        return {id:i, title: picked[i].title, kind: picked[i].kind,
                file: picked[i].file, quote: picked[i].quote}; })})})
    .then(function(r){ return r.json(); })
    .then(function(d){
      b.disabled=false; b.textContent='Make it';
      if(!d.ok){ alert(d.error || 'That did not send. Try again in a moment.'); return; }
      panel.className='panel'; picked={}; note.value='';
      document.getElementById('lines').value=''; document.getElementById('cta').value='';
      paint(); painBar();
      window.location.href='/vi/queue#req' + d.id;
    })
    .catch(function(){ b.disabled=false; b.textContent='Make it';
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
        "<div class=\"wrap\">" + _head(email, event_title, tab="library") +
        "<main>"
        "<div class=\"mk\"><button id=\"mkbtn\">Make a video</button></div>"
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
        "<button class=\"go\" id=\"ask\">Make a video with these</button>"
        "</div></div>"

        "<div class=\"panel\" id=\"panel\"><div class=\"card\">"
        "<h2>Make a video</h2>"
        "<p class=\"h\">Say what you want. Any moments you picked go in for sure; "
        "the machine finds the rest, cuts it, and it appears under "
        "<strong>My videos</strong> in a few minutes.</p>"
        "<ul>"
        "<li>Say where it is going — Instagram, a screen in the lobby, an email.</li>"
        "<li>Say who it is for — parents, students, a specific school.</li>"
        "<li>Say the feel, if you have one — proud, fun, epic, quiet.</li>"
        "</ul>"
        "<textarea id=\"note\" placeholder=\"A reel for the Lake Nona page, aimed at "
        "parents — the candlelight moments.\"></textarea>"
        "<label class=\"lbl2\">Words on screen <span>optional &middot; one sentence per line, "
        "up to four &middot; the first opens the video</span></label>"
        "<textarea id=\"lines\" class=\"short\" placeholder=\"Four days. Every school. One floor.\n"
        "Champions are made here.\"></textarea>"
        "<label class=\"lbl2\">End card <span>optional &middot; your call to action</span></label>"
        "<input type=\"text\" id=\"cta\" maxlength=\"60\" placeholder=\"Enroll today \u2014 victoryma.com\">"
        "<div class=\"len\"><span>How long</span>"
        "<input type=\"radio\" name=\"len\" id=\"l15\" value=\"15\"><label for=\"l15\">15 s</label>"
        "<input type=\"radio\" name=\"len\" id=\"l30\" value=\"30\" checked><label for=\"l30\">30 s</label>"
        "<input type=\"radio\" name=\"len\" id=\"l60\" value=\"60\"><label for=\"l60\">60 s</label>"
        "</div>"
        "<div class=\"acts\">"
        "<button class=\"cancel\" id=\"cancel\">Cancel</button>"
        "<button id=\"send\">Make it</button>"
        "</div></div></div>"
        % ("{:,}".format(records), event_title)
    )
    return _shell("Victory Intelligence", body, APP_JS)


# ── My videos: what the machine made, and the box to say what you think ────
STATE_LABEL = {
    "asked": "In the queue", "planned": "Planned", "rendering": "Cutting it now",
    "ready": "Ready to watch", "approved": "Approved", "delivered": "Delivered",
    "declined": "Declined", "failed": "Did not work",
}


def _e(s):
    return (str(s) if s is not None else "").replace("&", "&amp;").replace("<", "&lt;") \
        .replace(">", "&gt;").replace("\"", "&quot;")


def _when(ts):
    """'Sep 14, 11:44 PM' from a datetime or its string form. Never raises."""
    try:
        import datetime as _dt
        if isinstance(ts, str):
            ts = _dt.datetime.fromisoformat(ts.replace(" ", "T", 1)[:19])
        return ts.strftime("%b %-d, %-I:%M %p")
    except Exception:
        return _e(str(ts or ""))[:16]


def _request_card(r, mine_only):
    st = r.get("state") or "asked"
    items = r.get("items") or []
    if isinstance(items, str):
        try:
            import json as _json
            items = _json.loads(items)
        except Exception:
            items = []
    summ = r.get("summary") or {}
    if isinstance(summ, str):
        try:
            import json as _json
            summ = _json.loads(summ)
        except Exception:
            summ = {}
    rid = r.get("id")
    h = ["<div class=\"req\" id=\"req%s\">" % rid,
         "<div class=\"hd\"><span class=\"id\"><b>Video #%s</b> &middot; %s%s</span>"
         "<span class=\"status %s\">%s%s</span></div>"
         % (rid, _when(r.get("at")),
            ("" if mine_only else " &middot; %s" % _e(r.get("email"))),
            _e(st), "<i class=\"spin\"></i>" if st in ("asked", "rendering") else "",
            STATE_LABEL.get(st, st))]
    h.append("<div class=\"ask\">&ldquo;%s&rdquo;</div>" % _e(r.get("note") or "(no words — just the picked moments)"))
    txt = r.get("text") or {}
    if isinstance(txt, str):
        try:
            import json as _json
            txt = _json.loads(txt)
        except Exception:
            txt = {}
    if txt.get("lines") or txt.get("cta"):
        bits = ["on screen: %s" % " / ".join(_e(x) for x in txt.get("lines") or [])] if txt.get("lines") else []
        if txt.get("cta"):
            bits.append("end card: %s" % _e(txt["cta"]))
        h.append("<div class=\"from\">%s</div>" % " &middot; ".join(bits))
    h.append("<div class=\"from\">%ss requested%s</div>"
             % (r.get("length_s") or 30,
                (" &middot; %d moment%s picked" % (len(items), "" if len(items) == 1 else "s")) if items else
                " &middot; no moments picked, the machine chose"))
    if items:
        h.append("<div class=\"moments\">")
        for it in items[:8]:
            # the request stores what the page sent: id, title, kind, file, quote
            h.append("<div class=\"m\"><div class=\"t\">%s</div></div>"
                     % _e(it.get("title") or it.get("quote") or it.get("id")))
        h.append("</div>")
    if st == "ready" or (st in ("approved", "delivered") and r.get("result_drive_id")):
        if r.get("preview_url"):
            h.append("<iframe class=\"player\" src=\"%s\" allow=\"autoplay; fullscreen\" "
                     "allowfullscreen></iframe>" % _e(r["preview_url"]))
        shots = summ.get("shots") or []
        bits = []
        if shots:
            bits.append("%d shots" % len(shots))
        if summ.get("days"):
            bits.append("day%s %s" % ("s" if len(summ["days"]) > 1 else "",
                                      ", ".join(str(d) for d in summ["days"])))
        if summ.get("kinds"):
            bits.append(", ".join(_e(k).lower() for k in summ["kinds"]))
        if summ.get("music_title"):
            bits.append("music: %s" % _e(summ["music_title"]))
        if summ.get("render_seconds"):
            bits.append("cut in %ds" % int(summ["render_seconds"] + (summ.get("fetch_seconds") or 0)))
        if r.get("result_seconds"):
            bits.insert(0, "%.0f s" % float(r["result_seconds"]))
        if bits:
            h.append("<div class=\"summ\">%s</div>" % " &middot; ".join(bits))
        h.append("<div class=\"acts\">")
        if r.get("download_url"):
            h.append("<a class=\"dl\" href=\"%s\">Download</a>" % _e(r["download_url"]))
        if st == "ready":
            h.append("<button class=\"sec\" data-decide=\"approved\" data-id=\"%s\">Approve</button>" % rid)
            h.append("<button class=\"quiet\" data-decide=\"redo\" data-id=\"%s\">Cut it again</button>" % rid)
        h.append("</div>")
    elif st == "failed":
        h.append("<div class=\"errbox\">The machine could not make this one.\n%s</div>"
                 % _e(r.get("error") or ""))
        h.append("<div class=\"acts\"><button class=\"sec\" data-decide=\"redo\" data-id=\"%s\">Try again</button></div>" % rid)
    elif st in ("asked", "rendering"):
        h.append("<div class=\"summ\">%s</div>"
                 % ("The machine is cutting this now. This page refreshes itself."
                    if st == "rendering" else "Waiting for the machine. Usually under five minutes."))
    # feedback
    h.append("<div class=\"fb\">")
    for f in r.get("feedback") or []:
        h.append("<div class=\"note\">%s<small>%s &middot; %s</small></div>"
                 % (_e(f.get("text")), _e(f.get("email")), _when(f.get("at"))))
    if st not in ("asked", "rendering"):
        h.append("<textarea placeholder=\"What would you change? Be specific — the editor learns from this.\" "
                 "data-fb=\"%s\"></textarea>"
                 "<div class=\"acts\"><button data-fbsend=\"%s\">Send feedback</button></div>" % (rid, rid))
    h.append("</div></div>")
    return "".join(h)


QUEUE_JS = r"""
<script>
(function(){
  function post(url, body){
    return fetch(url,{method:'POST',credentials:'same-origin',
      headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
      .then(function(r){return r.json();});
  }
  document.addEventListener('click', function(e){
    var b=e.target.closest('button[data-fbsend]');
    if(b){
      var id=b.getAttribute('data-fbsend'), ta=document.querySelector('textarea[data-fb="'+id+'"]');
      if(!ta || !ta.value.trim()){ if(ta) ta.focus(); return; }
      b.disabled=true;
      post('/vi/feedback',{id:parseInt(id,10), text:ta.value}).then(function(d){
        if(!d.ok){ b.disabled=false; alert(d.error||'That did not save.'); return; }
        window.location.reload();
      }).catch(function(){ b.disabled=false; alert('That did not save.'); });
      return;
    }
    var d=e.target.closest('button[data-decide]');
    if(d){
      d.disabled=true;
      post('/vi/decide',{id:parseInt(d.getAttribute('data-id'),10), decision:d.getAttribute('data-decide')})
        .then(function(r){ if(!r.ok){ d.disabled=false; alert(r.error||'That did not save.'); return; }
          window.location.reload(); })
        .catch(function(){ d.disabled=false; alert('That did not save.'); });
    }
  });
  // while anything is in the queue or cutting, look again every 20 s
  if(document.querySelector('.status.asked, .status.rendering')){
    setTimeout(function(){
      fetch('/vi/mine',{credentials:'same-origin'}).then(function(r){return r.json();})
        .then(function(d){ window.location.reload(); })
        .catch(function(){ window.location.reload(); });
    }, 20000);
  }
})();
</script>
"""


def queue_page(email, role, rows, event_title="Convention 2026", all_people=False):
    waiting = sum(1 for r in rows if r.get("state") in ("asked", "rendering"))
    cards = "".join(_request_card(r, mine_only=not all_people) for r in rows)
    if not cards:
        cards = ("<div class=\"empty\">Nothing yet. Go to the Library, search for a moment, "
                 "and press <strong>Make a video</strong>.</div>")
    body = (
        "<div class=\"wrap\">" + _head(email, event_title, tab="queue", badge=waiting) +
        "<main>" +
        ("<div class=\"from\" style=\"margin:0 0 16px\">Everyone's videos, newest first "
         "(you are MWM).</div>" if all_people else "") +
        cards +
        "</main>"
        "<footer>Cut by the Victory Intelligence editor &middot; MWM Creations &amp; Studios.</footer>"
        "</div>"
    )
    return _shell("Victory Intelligence — my videos", body, QUEUE_JS)
