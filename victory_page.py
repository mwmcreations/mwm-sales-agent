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
/* Victory Intelligence — the look. Michael, 17 Sep: "very modern, AI era,
   like the Tesla website": black, white, one accent, big quiet type,
   hairline borders, no boxes where none are needed. */
:root{--bg:#000;--sur:#0e0e0e;--sur2:#181818;--line:rgba(255,255,255,.12);--line2:rgba(255,255,255,.22);
 --tx:#f4f4f4;--dim:#9b9b9b;--dim2:#6e6e6e;--red:#e0102f;--ok:#3ddc84;--warn:#ffb454;color-scheme:dark}
*{box-sizing:border-box;min-width:0}
html{background:var(--bg)}
body{margin:0;background:var(--bg);color:var(--tx);
 font:16px/1.55 Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
 -webkit-font-smoothing:antialiased;-webkit-text-size-adjust:100%;letter-spacing:-.005em}
a{color:#fff;text-decoration:none;border-bottom:1px solid var(--line2)}
a:hover{border-bottom-color:#fff}
::selection{background:#fff;color:#000}
::placeholder{color:var(--dim2)}
.wrap{max-width:980px;margin:0 auto;padding:0 24px 40px;min-height:100vh;min-height:100dvh;display:flex;flex-direction:column}
main{flex:1}
header.cv{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;padding:26px 0 18px}
header.cv .top{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap}
header.cv h1{font-size:13px;margin:0;font-weight:600;color:#fff;line-height:1}
.vilogo{display:inline-flex;align-items:center;gap:10px;color:#fff;border:0;text-decoration:none}
.vilogo .vimark{width:22px;height:22px;flex:0 0 22px}
.viword{font-size:13px;letter-spacing:.22em;text-transform:uppercase;font-weight:600;white-space:nowrap}
.viword b{font-weight:300}
main.door .vilogo.big{display:flex;margin:0 0 44px}
main.door .vilogo.big .vimark{width:56px;height:56px;flex-basis:56px}
main.door .vilogo.big .viword{font-size:22px;letter-spacing:.26em}
main.door h2{font-size:30px;font-weight:300;letter-spacing:-.02em}
header.cv .ev{font-size:11px;color:var(--dim);letter-spacing:.18em;text-transform:uppercase}
header.cv .who{font-size:12.5px;color:var(--dim2);margin:0}
header.cv .who a{color:var(--dim);border:0}
header.cv .who a:hover{color:#fff}
nav.sub{display:flex;gap:26px;padding:0;border-bottom:1px solid var(--line);overflow-x:auto}
nav.sub a{white-space:nowrap;color:var(--dim);font-weight:500;font-size:14px;line-height:1;padding:14px 0 15px;border:0;
 border-bottom:1px solid transparent;margin-bottom:-1px;transition:color .2s}
nav.sub a:hover{color:#fff}
nav.sub a.on{color:#fff;border-bottom-color:#fff}
nav.sub a .n{display:inline-block;background:#fff;color:#000;border-radius:100px;font-size:11px;font-weight:600;
 padding:2px 7px;margin-left:7px;vertical-align:1px}
main{padding:44px 0 30px;border:0;background:none}
footer{padding:28px 0 20px;color:var(--dim2);font-size:12px;border-top:1px solid var(--line);text-align:center}
p.h,p.p{color:var(--dim);font-size:14px}
p.small{font-size:13px;color:var(--dim2)}
h2{font-weight:500;letter-spacing:-.02em}
/* controls */
input[type=text],input[type=email]{flex:1;font-family:inherit;font-size:17px;line-height:1.4;padding:14px 20px;
 border:1px solid var(--line);border-radius:100px;background:var(--sur);color:#fff;min-width:0;-webkit-appearance:none;
 transition:border-color .2s,background .2s}
input:focus,textarea:focus{outline:none;border-color:#fff;background:#121212}
button{font-weight:600;font-family:inherit;font-size:14.5px;line-height:1;padding:14px 22px;border:0;border-radius:100px;
 background:#fff;color:#000;cursor:pointer;white-space:nowrap;transition:transform .15s,opacity .2s,background .2s}
button:hover{opacity:.9}
button:active{transform:scale(.98)}
button:disabled{opacity:.35;cursor:default}
.searchbar{display:flex;gap:10px;margin:0 0 14px}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 18px}
.chip{font-weight:500;font-family:inherit;font-size:13.5px;line-height:1;padding:10px 15px;border:1px solid var(--line);border-radius:100px;
 background:none;color:#ddd;cursor:pointer;transition:background .2s,border-color .2s}
.chip:hover{background:rgba(255,255,255,.06);border-color:var(--line2)}
.chip:active{background:rgba(255,255,255,.12)}
.chips .lbl{font-size:12.5px;color:var(--dim2);align-self:center;margin-right:2px}
.tabs{display:flex;gap:22px;border-bottom:1px solid var(--line);margin:0 0 6px}
.tab{font-weight:500;font-family:inherit;font-size:14px;line-height:1;padding:12px 0 13px;background:none;color:var(--dim);border:0;
 border-bottom:1px solid transparent;border-radius:0;margin-bottom:-1px;cursor:pointer}
.tab.on{color:#fff;border-bottom-color:#fff}
.tab .c{font-weight:400;color:var(--dim2);margin-left:6px;font-size:12.5px}
.meta{font-size:13px;color:var(--dim);min-height:19px;margin:14px 0 8px}
/* library rows */
.row{display:flex;gap:16px;padding:16px 0;border-bottom:1px solid var(--line);align-items:flex-start}
.row:last-child{border-bottom:0}
.thumb{width:128px;flex:0 0 128px;aspect-ratio:16/9;background:var(--sur2);border-radius:10px;overflow:hidden;position:relative}
.thumb img{width:100%;height:100%;object-fit:cover;display:block}
.thumb.said{background:var(--sur);display:flex;align-items:center;justify-content:center;border:1px solid var(--line)}
.thumb.said b{font-size:10.5px;letter-spacing:.14em;color:var(--warn);font-weight:600}
.thumb .dur{position:absolute;right:6px;bottom:6px;background:rgba(0,0,0,.7);color:#fff;
 font-size:10.5px;padding:2px 6px;border-radius:100px;font-variant-numeric:tabular-nums;backdrop-filter:blur(6px)}
.thumb.play{cursor:pointer}
.thumb .pl{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);width:34px;height:34px;
 border-radius:100px;background:rgba(255,255,255,.9);color:#000;font-size:12px;display:flex;
 align-items:center;justify-content:center;padding-left:2px}
.thumb.open{width:100%;flex-basis:100%;aspect-ratio:16/9}
.thumb video{width:100%;height:100%;display:block;background:#000}
.row:has(.thumb.open){flex-wrap:wrap}
.body{flex:1}
.title{font-weight:500;font-size:15.5px;margin:0 0 3px;line-height:1.35;color:#fff}
.said .title{font-weight:400;font-size:15px;color:#e6e6e6}
.sub{font-size:12.5px;color:var(--dim);line-height:1.45}
.file{font-size:11px;color:var(--dim2);font-family:ui-monospace,SFMono-Regular,Menlo,monospace;margin-top:4px;word-break:break-all}
.tag{display:inline-block;font-size:9.5px;letter-spacing:.12em;text-transform:uppercase;font-weight:600;
 padding:3px 7px;border-radius:100px;margin-right:6px;vertical-align:2px;border:1px solid var(--line)}
.tag.hero{border-color:rgba(224,16,47,.5);color:#ff5c72}
.pick{flex:0 0 auto;width:36px;height:36px;border:1px solid var(--line2);background:none;color:#fff;
 border-radius:100px;font-weight:300;font-family:inherit;font-size:22px;line-height:1;padding:0;cursor:pointer;align-self:center}
.pick.on{background:#fff;border-color:#fff;color:#000}
.empty{padding:40px 0;color:var(--dim)}
.more{margin:18px 0 0}
.more button{background:none;color:#fff;border:1px solid var(--line2);width:100%}
/* the shortlist bar and the ask panel */
.bar{position:fixed;left:0;right:0;bottom:0;background:rgba(10,10,10,.8);backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);
 color:#fff;padding:14px 20px;display:none;border-top:1px solid var(--line);z-index:20}
.bar.on{display:block}
.bar .in{max-width:980px;margin:0 auto;display:flex;gap:10px;align-items:center}
.bar .n{font-size:14px;flex:1;color:var(--dim)}
.bar .n b{font-size:16px;color:#fff}
.bar button.go{background:#fff;color:#000}
.bar button.clr{background:none;color:var(--dim);padding:13px 6px;font-weight:500}
.panel{position:fixed;inset:0;background:rgba(0,0,0,.7);backdrop-filter:blur(6px);display:none;z-index:30;align-items:flex-end}
.panel.on{display:flex}
.panel .card{background:var(--sur);border:1px solid var(--line);border-bottom:0;width:100%;max-width:980px;margin:0 auto;
 border-radius:22px 22px 0 0;padding:28px 26px 30px;max-height:88vh;overflow-y:auto}
.panel h2{font-size:22px;margin:0 0 6px}
.panel p.h{font-size:14px;color:var(--dim);margin:0 0 18px}
.panel ul{margin:0 0 18px;padding-left:18px;font-size:13.5px;color:var(--dim)}
.panel li{margin:0 0 5px}
textarea{font-family:inherit;color:#fff;background:var(--sur);border:1px solid var(--line);-webkit-appearance:none}
.panel textarea{width:100%;font-size:16px;line-height:1.5;padding:14px 16px;border-radius:14px;min-height:92px;resize:vertical}
.panel .acts{display:flex;gap:10px;margin-top:18px}
.panel .acts button{flex:1}
.panel .acts button.cancel{background:none;color:#fff;border:1px solid var(--line2)}
.done{background:rgba(61,220,132,.08);border:1px solid rgba(61,220,132,.3);border-radius:14px;padding:16px 18px;margin:0 0 18px;
 font-size:14.5px;color:#bfeed3}
.done.warn{background:rgba(255,180,84,.08);border-color:rgba(255,180,84,.35);color:#ffd9a3}
.lbl2{display:block;font-size:13.5px;font-weight:500;color:#ddd;margin:14px 0 6px}
.lbl2 span{font-weight:400;color:var(--dim);font-size:12.5px}
.panel textarea.short{min-height:64px}
.panel input[type=text]{width:100%;font-size:16px;padding:12px 18px;margin:0 0 12px}
.len{display:flex;gap:8px;margin:0 0 14px;flex-wrap:wrap;align-items:center}
.len span{font-size:13px;color:var(--dim);margin-right:4px}
.len label{font-weight:500;font-family:inherit;font-size:14px;line-height:1;padding:10px 15px;border:1px solid var(--line);border-radius:100px;
 cursor:pointer;color:#ddd;background:none}
.len input{display:none}
.len input:checked+label{background:#fff;color:#000;border-color:#fff}
.askbox h2{font-size:24px;margin:4px 0 12px}
.askbox textarea{width:100%;font-size:17px;line-height:1.5;padding:16px 18px;border-radius:16px;min-height:110px;resize:vertical}
.brief{min-height:22px;font-size:13.5px;color:var(--dim);margin:8px 0 12px;line-height:1.5}
.brief .k{font-weight:600;color:var(--dim2);text-transform:uppercase;font-size:11px;letter-spacing:.1em;margin-right:6px}
details.opts{margin:0 0 14px;font-size:14px}
details.opts summary{cursor:pointer;color:#fff;font-weight:500;padding:6px 0}
.toggle{display:flex;align-items:center;gap:10px;font-size:15px;font-weight:500;color:#ddd;margin:6px 0 14px;cursor:pointer}
.toggle input{width:22px;height:22px;accent-color:#fff}
button.big{width:100%;font-size:17px;padding:17px 20px}
.askbox p.h{margin:12px 0 0}
/* the chat — the front door */
.vichat{margin:0 0 6px;max-width:760px}
.vichat .log{max-height:min(64vh,680px);overflow:auto;padding:4px 2px 6px;-webkit-overflow-scrolling:touch;
 scrollbar-width:thin;scrollbar-color:#333 transparent}
.msg{font-size:16.5px;line-height:1.55;padding:0;margin:0 0 22px;max-width:100%;width:auto;animation:rise .4s ease both}
@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.msg.bot{background:none;color:var(--tx);white-space:pre-line}
.msg.bot#hello{font-size:26px;font-weight:300;line-height:1.35;letter-spacing:-.02em;color:#fff;margin:0 0 26px}
.msg.me{background:var(--sur2);color:#fff;margin-left:auto;padding:12px 18px;border-radius:20px;border-bottom-right-radius:6px;
 width:fit-content;max-width:86%}
.msg.wait{color:var(--dim);background:none;border:0;font-style:normal;padding:0}
.msg.wait::before{content:"";display:inline-block;width:8px;height:8px;border-radius:100px;background:#fff;margin-right:10px;
 vertical-align:1px;animation:pulse 1.2s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:.25}50%{opacity:1}}
.msg.offer,.msg.plan{background:var(--sur);border:1px solid var(--line);border-radius:20px;padding:22px 22px 20px;max-width:100%;width:100%;white-space:normal}
.msg .ask{font-size:20px;font-weight:500;line-height:1.35;letter-spacing:-.01em;margin:0 0 10px}
.msg .brief{margin:0 0 10px;font-size:13px}
.msg .lens{display:flex;gap:8px;margin:6px 0 16px}
.msg .lens button{background:none;color:#ddd;border:1px solid var(--line);border-radius:100px;font-size:14px;font-weight:500;padding:10px 15px}
.msg .lens button.on{background:#fff;color:#000;border-color:#fff}
.msg .use{display:block;width:100%;background:#fff;color:#000;border:0;border-radius:100px;font-family:inherit;font-weight:600;font-size:16px;
 line-height:1;padding:17px 18px;white-space:normal;text-align:center}
.msg .hint{font-size:12.5px;color:var(--dim2);margin:10px 0 0;text-align:center}
.msg .ph{font-weight:600;font-size:11.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--dim);margin:0 0 12px}
.msg .step{padding:14px 0;border-top:1px solid var(--line)}
.msg .step:first-of-type{border-top:0;padding-top:0}
.msg .st{font-weight:500;font-size:16.5px;line-height:1.35;display:flex;gap:10px;align-items:flex-start}
.msg .st .n{flex:0 0 24px;width:24px;height:24px;border-radius:100px;border:1px solid var(--line2);color:#fff;font-size:12px;
 line-height:22px;text-align:center;font-weight:500;margin-top:-1px}
.msg .sw{font-size:14px;color:var(--dim);margin:5px 0 0}
.msg .sv{font-size:13.5px;color:#e6e6e6;margin:8px 0 0;padding:10px 12px;background:var(--sur2);border-radius:12px}
.msg .sx{font-size:12.5px;color:var(--dim2);margin:5px 0 0}
.msg .mk{display:inline-block;margin:10px 0 0;background:#fff;color:#000;border:0;border-radius:100px;font-family:inherit;font-weight:600;
 font-size:13.5px;line-height:1;padding:11px 16px;white-space:normal}
.msg .pkg{margin:0 0 12px;padding:12px 14px;background:var(--sur2);border-radius:14px;font-size:14px}
.msg .pk{margin:0 0 8px}
.msg .pk .k{display:block;font-weight:600;color:var(--dim2);text-transform:uppercase;font-size:10.5px;letter-spacing:.12em;margin:0 0 3px}
.msg .pk .ln{font-weight:500;line-height:1.35;color:#fff}
.msg .pk .then{color:var(--dim);font-size:12.5px}
.msg .alt{display:block;margin:8px 0 0;background:none;color:#fff;border:1px solid var(--line);border-radius:100px;font-family:inherit;
 font-weight:500;font-size:13.5px;line-height:1.3;padding:11px 16px;text-align:left;white-space:normal;max-width:100%;
 transition:background .2s,border-color .2s}
.msg .alt:hover{background:rgba(255,255,255,.06);border-color:var(--line2)}
.msg .ideas .lbl{display:block;font-size:12.5px;color:var(--dim2);margin:14px 0 2px;letter-spacing:.02em}
.msg a{color:#fff;font-weight:500}
.vichat .hin{display:flex;gap:10px;align-items:flex-end;padding:8px 0 0}
.vichat .hin textarea{flex:1;font-size:17px;line-height:1.4;padding:15px 20px;border-radius:26px;min-width:0;resize:none;
 min-height:52px;max-height:160px;transition:border-color .2s}
.vichat .hin button{border-radius:100px;padding:18px 22px;font-size:15px}
.vichat p.h{font-size:13px;color:var(--dim2);margin:16px 0 0}
.vichat p.h strong{color:var(--dim);font-weight:500}
.vichat p.h a{color:var(--dim);font-weight:500}
.vichat p.h a:hover{color:#fff}
.msg.note{background:rgba(255,180,84,.08);border:1px solid rgba(255,180,84,.3);border-radius:14px;padding:12px 16px;color:#ffd9a3;font-size:13.5px}
.mem{margin:14px 0 0;padding:16px 18px;border:1px solid var(--line);border-radius:16px;background:var(--sur);font-size:14px}
.mem .mh{font-weight:500;margin:0 0 8px;color:#fff}
.mem .ml{margin:0 0 5px;color:var(--dim)}
.mem .forget{background:none;color:#fff;border:0;padding:2px 6px;font-size:12.5px;font-weight:500}
.mem .forget.all{display:block;margin-top:10px;color:#ff5c72;padding:4px 0}
.picker{margin-top:34px;padding-top:24px;border-top:1px solid var(--line)}
.picker p.h{font-size:14px;color:var(--dim);margin:0 0 14px}
main.browse .pick{display:none}
.mk{margin:0 0 16px}
.mk button{width:100%}
/* my videos */
.req{border:1px solid var(--line);border-radius:20px;padding:22px 24px;margin:0 0 18px;background:var(--sur)}
.req .hd{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:baseline}
.req .id{font-size:12.5px;color:var(--dim)}
.req .id b{color:#fff;font-size:14px;font-weight:500}
.status{display:inline-block;font-size:11px;letter-spacing:.1em;text-transform:uppercase;font-weight:600;
 padding:5px 11px;border-radius:100px;background:rgba(255,255,255,.08);color:#ddd}
.status.asked,.status.rendering{background:rgba(255,180,84,.12);color:var(--warn)}
.status.ready{background:rgba(61,220,132,.12);color:var(--ok)}
.status.approved,.status.delivered{background:rgba(92,150,255,.14);color:#8fb4ff}
.status.failed,.status.declined{background:rgba(224,16,47,.14);color:#ff5c72}
.ask{font-size:19px;font-weight:500;margin:12px 0 4px;line-height:1.4;letter-spacing:-.01em}
.from{font-size:13px;color:var(--dim);margin:0 0 14px}
.moments{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 16px}
.m{width:124px}
.m .mt{aspect-ratio:16/9;border-radius:8px;overflow:hidden;background:var(--sur2);margin:0 0 5px}
.m .mt img{width:100%;height:100%;object-fit:cover;display:block}
.m .t{font-size:12px;font-weight:400;line-height:1.3;color:var(--dim)}
.player.pl{display:flex;align-items:center;justify-content:center;cursor:pointer;border:1px solid var(--line)}
.player .pb{color:#000;font-weight:600;font-family:inherit;font-size:15px;line-height:1;background:#fff;padding:15px 24px;border-radius:100px}
.player{width:100%;max-width:300px;aspect-ratio:9/16;border:0;border-radius:16px;background:#000;display:block;margin:0 0 14px}
.summ{font-size:12.5px;color:var(--dim2);margin:0 0 12px;line-height:1.5}
.fb{margin:16px 0 0;border-top:1px solid var(--line);padding-top:14px}
.fb .fbh{font-size:14px;color:var(--dim);margin:0 0 10px}
.fb .fbs{font-size:13.5px;color:var(--dim)}
.ver{font-size:13px;color:var(--dim);margin:-2px 0 10px}
.ver a{color:#fff}
.fb .note{background:var(--sur2);border-left:2px solid var(--line2);padding:10px 14px;font-size:14px;color:#ddd;margin:0 0 8px;white-space:pre-wrap;border-radius:0 10px 10px 0}
.fb .note small{display:block;color:var(--dim2);font-size:11.5px;margin-top:3px}
.fb textarea{width:100%;font-size:15px;line-height:1.5;padding:12px 16px;border-radius:14px;min-height:70px;resize:vertical;margin:0 0 10px}
.acts{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.acts button.sec{background:none;color:#fff;border:1px solid var(--line2)}
.acts button.quiet{background:none;color:var(--dim);border:0;padding:12px 8px;font-weight:500}
.acts a.dl{font-size:14px;font-weight:500}
.spin{display:inline-block;width:12px;height:12px;border:2px solid rgba(255,180,84,.3);border-top-color:var(--warn);
 border-radius:100px;animation:sp 1s linear infinite;vertical-align:-1px;margin-right:7px}
@keyframes sp{to{transform:rotate(360deg)}}
.errbox{background:rgba(224,16,47,.1);border:1px solid rgba(224,16,47,.35);border-radius:14px;padding:12px 16px;font-size:13.5px;color:#ffb3bd;
 margin:0 0 12px;white-space:pre-wrap}
.errbox.warn{background:rgba(255,180,84,.08);border-color:rgba(255,180,84,.35);color:#ffd9a3}
@media(max-width:600px){
 .wrap{padding:0 18px 100px}
 header.cv{padding:20px 0 12px;flex-wrap:nowrap;align-items:flex-start}
 header.cv .top{flex-direction:column;gap:5px}
 .viword{font-size:12px;letter-spacing:.18em}
 .vilogo .vimark{width:19px;height:19px;flex-basis:19px}
 main.door .vilogo.big{flex-direction:column;align-items:flex-start;gap:16px;margin:0 0 34px}
 main.door .vilogo.big .viword{font-size:17px}
 header.cv .ev{font-size:10.5px;letter-spacing:.14em}
 header.cv .who .e{display:none}
 header.cv .who{margin-top:1px}
 nav.sub{gap:20px}nav.sub a{font-size:13.5px}
 main{padding:30px 0 24px}
 .msg.bot#hello{font-size:22px}
 .m{width:calc(33% - 7px)}
 .searchbar{flex-direction:column}.searchbar button{width:100%}
 .thumb{width:104px;flex:0 0 104px}
 .row{gap:12px}
 .pick{width:34px;height:34px}
 .vichat .hin button{padding:17px 18px}
 .req{padding:18px 18px}
 .msg.offer,.msg.plan{padding:18px 18px 16px}
}
"""

# iOS turns bare email addresses and four-digit years into links, which put
# blue underlines through the header on Michael's phone. Off, explicitly.
NO_AUTOLINK = ('<meta name="format-detection" '
               'content="telephone=no,date=no,address=no,email=no">')


def _shell(title, body, extra=""):
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">"
        "<meta name=\"theme-color\" content=\"#000000\">"
        "<link rel=\"preconnect\" href=\"https://fonts.googleapis.com\">"
        "<link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin>"
        "<link href=\"https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap\" rel=\"stylesheet\">"
        + NO_AUTOLINK +
        "<title>%s</title><style>%s</style></head><body>%s%s</body></html>"
        % (title, CSS, body, extra)
    )


VI_MARK = ("<svg class=\"vimark\" viewBox=\"0 0 34 34\" aria-hidden=\"true\">"
           "<path d=\"M4 7 L13 27 L22 7\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"3.2\" "
           "stroke-linecap=\"round\" stroke-linejoin=\"round\"/>"
           "<rect x=\"27\" y=\"7\" width=\"3.2\" height=\"20\" rx=\"1.6\" fill=\"#e0102f\"/></svg>")
VI_WORDMARK = "<span class=\"viword\">Victory <b>Intelligence</b></span>"


def vi_logo(cls=""):
    """The Victory Intelligence lockup: the VI mark (a V and a red I) and the
    wordmark. Michael, 17 Sep: the platform gets its own logo, not the
    Victory Martial Arts one."""
    return "<a class=\"vilogo %s\" href=\"/vi/\">%s%s</a>" % (cls, VI_MARK, VI_WORDMARK)


def _head(email, event_title="Convention 2026", tab="library", badge=0):
    b = ("<span class=\"n\">%d</span>" % badge) if badge else ""
    return ("<header class=\"cv\"><div class=\"top\">"
            "<h1>" + vi_logo() + "</h1><span class=\"ev\">%s</span></div>"
            "<div class=\"who\"><span class=\"e\">%s &middot; </span>"
            "<a href=\"/vi/logout\">sign out</a></div></header>"
            "<nav class=\"sub\"><a href=\"/vi/\"%s>Make a video</a>"
            "<a href=\"/vi/queue\"%s>My videos%s</a>"
            "<a href=\"/vi/library\"%s>Browse footage</a></nav>"
            % (event_title, email,
               " class=\"on\"" if tab == "make" else "",
               " class=\"on\"" if tab == "queue" else "", b,
               " class=\"on\"" if tab == "library" else ""))


def signin_page(sent=False, message=""):
    """The door. Says the same thing whether or not the address is known."""
    if sent:
        inner = (
            "<div style=\"max-width:430px\">"
            "<h2 style=\"font-size:26px;margin:0 0 12px\">Check your email</h2>"
            "<p class=\"p\">If that address can use Victory "
            "Intelligence, a sign-in link is on its way. It works once and "
            "expires in 15 minutes.</p>"
            "<p class=\"small\">Nothing arrived? Check "
            "spam, then try again.</p></div>")
    else:
        warn = ("<div class=\"done warn\">%s</div>" % message) if message else ""
        inner = (
            "<div style=\"max-width:430px\">"
            "<h2 style=\"font-size:26px;margin:0 0 12px\">Sign in</h2>"
            "<p class=\"p\">Enter your Victory email address and we "
            "will send you a link. There is no password to remember.</p>"
            + warn +
            "<form method=\"post\" action=\"/vi/login\">"
            "<div class=\"searchbar\">"
            "<input type=\"email\" name=\"email\" required autofocus "
            "autocomplete=\"email\" placeholder=\"you@victoryma.com\">"
            "<button type=\"submit\">Send link</button></div></form>"
            "<p class=\"small\">Access is granted by MWM. "
            "If you sign in and see nothing yet, that is why.</p></div>")
    body = ("<div class=\"wrap\"><header class=\"cv\"><div class=\"top\">"
            "<span class=\"ev\">MWM Creations &amp; Studios</span></div></header>"
            "<main class=\"door\">" + vi_logo("big") + inner + "</main>"
            "<footer>Built by MWM Creations &amp; Studios for Victory Martial Arts.</footer>"
            "</div>")
    return _shell("Victory Intelligence — sign in", body)


def pending_page(email):
    inner = (
        "<div style=\"max-width:460px\">"
        "<h2 style=\"font-size:26px;margin:0 0 12px\">You are signed in</h2>"
        "<p class=\"p\">We have not been told what "
        "<strong>%s</strong> should be able to see yet, so there is nothing "
        "here for the moment.</p>"
        "<p class=\"p\">MWM has been notified. Once access is "
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
      pickmode=document.getElementById('pickmode'), picker=document.getElementById('picker'),
      picked={}, rows=[], shown=0, kind='clip', timer=null, seq=0, PAGE=12, btimer=null;

  function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}

  function clipId(r){ return String(r.id||'').split(':').slice(-1)[0]; }
  function thumb(r){
    if(r.kind==='clip'){
      var cid = clipId(r);
      var fallback = r.drive_id ? 'https://drive.google.com/thumbnail?id=' + esc(r.drive_id) + '&sz=w400' : '';
      return '<div class="thumb play" data-clip="' + esc(cid) + '" title="Tap to watch">' +
        '<img loading="lazy" alt="" src="/vi/thumb/' + esc(cid) + '.jpg"' +
        (fallback ? ' onerror="this.onerror=null;this.src=\'' + fallback + '\'"' : '') + '>' +
        '<span class="pl">&#9654;</span>' +
        (r.duration ? '<span class="dur">'+esc(r.duration)+'</span>' : '') + '</div>';
    }
    if(r.moment){
      // a line someone said: the picture is the piece of the recording it was
      // said in, and tapping plays it from that line (Michael, 16 Sep:
      // "thumbnails for everything, even a phrase someone said")
      return '<div class="thumb play said" data-clip="' + esc(r.moment) + '" data-at="' + (r.offset||0) + '" title="Tap to hear">' +
        '<img loading="lazy" alt="" src="/vi/thumb/' + esc(r.moment) + '.jpg"' +
        ' onerror="this.onerror=null;this.parentNode.innerHTML=\'<b>SAID</b>\'">' +
        '<span class="pl">&#9654;</span>' +
        (r.duration ? '<span class="dur">'+esc(r.duration)+'</span>' : '') + '</div>';
    }
    return '<div class="thumb said"><b>SAID</b></div>';
  }
  // tap a thumbnail: play the small preview right there; tap again to stop
  out.addEventListener('click', function(e){
    var t=e.target.closest('.thumb.play'); if(!t) return;
    e.preventDefault();
    var cid=t.getAttribute('data-clip'), at=parseFloat(t.getAttribute('data-at')||'0')||0;
    if(t.querySelector('video')){ paint(); return; }
    document.querySelectorAll('.thumb.play video').forEach(function(v){ v.pause(); });
    t.innerHTML = '<video playsinline autoplay controls preload="metadata" src="/vi/preview/' + esc(cid) + '.mp4' + (at>0.5 ? '#t=' + at.toFixed(1) : '') + '"></video>';
    var v=t.querySelector('video');
    if(at>0.5){ v.addEventListener('loadedmetadata', function(){ try{ if(v.currentTime<at-0.5) v.currentTime=at; }catch(_){} }); }
    t.classList.add('open');
  });

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
    if(!bar) return;
    var n=Object.keys(picked).length;
    bar.className = n ? 'bar on' : 'bar';
    barn.innerHTML = '<b>' + n + '</b> moment' + (n===1?'':'s') + ' picked';
  }

  if(bar){
    document.getElementById('clr').onclick=function(){ picked={}; paint(); painBar(); };
    document.getElementById('ask').onclick=function(){ send(); };
  }

  // ── the chat: Victory Intelligence itself (Michael, 17 Sep: "people nowadays
  // are used to go to AI and chat with AI … make this 100% interactive")
  var ideas=document.getElementById('ideas'), hlog=document.getElementById('hlog'),
      hq=document.getElementById('hq'), hsend=document.getElementById('hsend'),
      hist=[], curAsk='', curLen=30, curLines=[], curCta='';

  function bubble(cls, text){
    var m=document.createElement('div'); m.className='msg '+cls; if(text) m.textContent=text;
    hlog.appendChild(m); m.scrollIntoView({block:'nearest'}); return m;
  }
  function ideaButton(t, cls){
    var b=document.createElement('button'); b.type='button'; b.className=cls||'alt'; b.textContent=t;
    b.onclick=function(){ hq.value=t; helperSend(); }; return b;
  }
  if(ideas){
    fetch('/vi/ideas', {credentials:'same-origin'}).then(function(r){ return r.json(); })
      .then(function(d){
        if(!d.ok || !(d.ideas||[]).length) return;
        var l=document.createElement('div'); l.className='lbl'; l.textContent='Or try one of these:'; ideas.appendChild(l);
        d.ideas.forEach(function(t){ ideas.appendChild(ideaButton(t, 'alt')); });
      }).catch(function(){});
  }
  // the card that offers the cut: the sentence, how the editor reads it,
  // the length, and the one button that matters
  function offer(d){
    curAsk=d.ask; curLen=d.length||30; curLines=d.lines||[]; curCta=d.cta||'';
    var m=bubble('bot offer');
    var q=document.createElement('div'); q.className='ask'; q.textContent=d.ask; m.appendChild(q);
    if(d.brief){ var b=document.createElement('div'); b.className='brief'; b.innerHTML='<span class="k">Understood as</span> '+esc(d.brief); m.appendChild(b); }
    if(curLines.length || curCta){
      var x=document.createElement('div'); x.className='pkg';
      if(curLines.length){
        var w=document.createElement('div'); w.className='pk'; w.innerHTML='<span class="k">Words on screen</span>';
        curLines.forEach(function(t){ var li=document.createElement('div'); li.className='ln'; li.textContent=t; w.appendChild(li); });
        x.appendChild(w);
      }
      if(curCta){ var c=document.createElement('div'); c.className='pk'; c.innerHTML='<span class="k">End card</span> '+esc(curCta)+' <span class="then">then the Victory Martial Arts card</span>'; x.appendChild(c); }
      m.appendChild(x);
    }
    var len=document.createElement('div'); len.className='lens';
    [15,30,60].forEach(function(n){
      var c=document.createElement('button'); c.type='button'; c.textContent=n+' s'; c.className=(n===curLen?'on':'');
      c.onclick=function(){ curLen=n; len.querySelectorAll('button').forEach(function(o){ o.className=''; }); c.className='on'; };
      len.appendChild(c);
    });
    m.appendChild(len);
    var go=document.createElement('button'); go.type='button'; go.className='use'; go.textContent='Make it';
    go.onclick=function(){ makeIt(go); }; m.appendChild(go);
    var ch=document.createElement('div'); ch.className='hint'; ch.textContent='Want something different? Just say so below.'; m.appendChild(ch);
    m.scrollIntoView({block:'nearest'});
  }
  function helperSend(){
    var t=(hq.value||'').trim(); if(!t) return;
    hq.value=''; hq.style.height='';
    bubble('me', t); hist.push({role:'user', text:t});
    var w=bubble('bot wait', 'thinking…'); hsend.disabled=true;
    fetch('/vi/helper', {method:'POST', credentials:'same-origin',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify({messages: hist.slice(-14)})})
    .then(function(r){ return r.json(); })
    .then(function(d){
      hsend.disabled=false; w.remove();
      if(!d.ok){ bubble('bot', d.error || 'I did not catch that; say it again.'); return; }
      if(d.say){ bubble('bot', d.say); }
      // our own turn goes back as the object it was, so the next answer keeps the shape
      hist.push({role:'bot', text: JSON.stringify({say: d.say || '', ask: d.ask || null, lines: d.lines || [], cta: d.cta || null,
                                                 plan: (d.plan||[]).map(function(st){ return {title: st.title, ask: st.ask || null}; })})});
      if(d.remembered){ bubble('bot note', 'Noted for next time: ' + d.remembered); }
      if(d.forgot){ bubble('bot note', 'Forgotten.'); }
      if(d.ask) offer(d);
      if((d.plan||[]).length) showPlan(d.plan);
      if((d.ideas||[]).length){
        var m=bubble('bot'); m.textContent=d.ask?'Or one of these:':'Some ideas:';
        d.ideas.forEach(function(t){ m.appendChild(ideaButton(t,'alt')); });
      }
    })
    .catch(function(){ hsend.disabled=false; w.remove(); bubble('bot', 'I am not answering just now; try again in a moment.'); });
  }
  function makeIt(btn, pkg, stay){
    // pkg: {ask, len, lines, cta} — the proposal card's, or one step of a plan
    pkg = pkg || {ask: curAsk, len: curLen, lines: curLines, cta: curCta};
    if(!pkg.ask) return;
    var ids=(picker && !picker.hidden) ? Object.keys(picked) : [];
    var label=btn.textContent;
    btn.disabled=true; btn.textContent='Sending…';
    fetch('/vi/request', {method:'POST', credentials:'same-origin',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({note: pkg.ask, length: pkg.len || 30, lines: (pkg.lines||[]).join('\n'), cta: pkg.cta || '',
        items: ids.map(function(i){ return {id:i, title: picked[i].title, kind: picked[i].kind,
                                             file: picked[i].file, quote: picked[i].quote}; })})})
    .then(function(r){ return r.json(); })
    .then(function(d){
      if(!d.ok){ btn.disabled=false; btn.textContent=label; bubble('bot', d.error || 'That did not send. Try again in a moment.'); return; }
      btn.textContent='Sent ✓';
      var m=bubble('bot', stay ? 'On it — that one is with the editor; it will be under My videos in a few minutes. '
                               : 'On it. Your video will be under My videos in a few minutes — taking you there. ');
      var a=document.createElement('a'); a.href='/vi/queue#req'+d.id; a.textContent='See it'; m.appendChild(a);
      hist.push({role:'bot', text:'Sent to the editor: '+pkg.ask});
      picked={}; paint(); painBar();
      if(!stay){ curAsk=''; setTimeout(function(){ window.location.href='/vi/queue#req'+d.id; }, 1800); }
    })
    .catch(function(){ btn.disabled=false; btn.textContent=label; bubble('bot', 'That did not send. Try again in a moment.'); });
  }
  // a plan: numbered steps; the ones that are videos can be cut from right here
  function showPlan(steps){
    var m=bubble('bot plan');
    var h=document.createElement('div'); h.className='ph'; h.textContent='The plan'; m.appendChild(h);
    steps.forEach(function(st, i){
      var row=document.createElement('div'); row.className='step';
      var t=document.createElement('div'); t.className='st'; t.innerHTML='<span class="n">'+(i+1)+'</span> '+esc(st.title); row.appendChild(t);
      if(st.why){ var w=document.createElement('div'); w.className='sw'; w.textContent=st.why; row.appendChild(w); }
      if(st.ask){
        var v=document.createElement('div'); v.className='sv'; v.textContent=st.ask; row.appendChild(v);
        if((st.lines||[]).length || st.cta){
          var x=document.createElement('div'); x.className='sx';
          x.textContent=((st.lines||[]).length ? 'On screen: '+st.lines.join(' / ') : '') + (st.cta ? ((st.lines||[]).length?' · ':'')+'End card: '+st.cta : '');
          row.appendChild(x);
        }
        var b=document.createElement('button'); b.type='button'; b.className='mk'; b.textContent='Make this video · '+(st.length||30)+' s';
        b.onclick=function(){ makeIt(b, {ask: st.ask, len: st.length||30, lines: st.lines||[], cta: st.cta||''}, true); };
        row.appendChild(b);
      }
      m.appendChild(row);
    });
    m.scrollIntoView({block:'nearest'});
  }
  if(hsend){
    hsend.onclick=helperSend;
    hq.addEventListener('keydown', function(e){ if(e.key==='Enter' && !e.shiftKey){ e.preventDefault(); helperSend(); }});
    hq.addEventListener('input', function(){ hq.style.height=''; hq.style.height=Math.min(140, hq.scrollHeight)+'px'; });
  }
  // what it remembers about you — always one tap away, always yours to clear
  var memlink=document.getElementById('memlink'), mem=document.getElementById('mem');
  function showMem(){
    fetch('/vi/memory', {credentials:'same-origin'}).then(function(r){ return r.json(); })
      .then(function(d){
        if(!d.ok) return;
        mem.innerHTML='';
        var h=document.createElement('div'); h.className='mh'; h.textContent='What Victory Intelligence remembers about you'; mem.appendChild(h);
        if(!(d.notes||[]).length && !(d.videos||[]).length){
          var e=document.createElement('div'); e.className='ml'; e.textContent='Nothing yet. Tell me about your school and where you post, and I will keep it.'; mem.appendChild(e);
        }
        (d.notes||[]).forEach(function(n){
          var l=document.createElement('div'); l.className='ml'; l.textContent='\u2022 '+n;
          var x=document.createElement('button'); x.type='button'; x.className='forget'; x.textContent='forget';
          x.onclick=function(){ fetch('/vi/memory/forget', {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body: JSON.stringify({text:n})}).then(showMem); };
          l.appendChild(x); mem.appendChild(l);
        });
        if((d.videos||[]).length){
          var v=document.createElement('div'); v.className='ml'; v.textContent='Videos: '+d.videos.slice(0,5).map(function(x){ return x.ask; }).join(' · '); mem.appendChild(v);
        }
        if((d.notes||[]).length){
          var all=document.createElement('button'); all.type='button'; all.className='forget all'; all.textContent='Forget everything about me';
          all.onclick=function(){ fetch('/vi/memory/forget', {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body: JSON.stringify({text:'*'})}).then(showMem); };
          mem.appendChild(all);
        }
        mem.hidden=false;
      }).catch(function(){});
  }
  if(memlink){ memlink.addEventListener('click', function(e){ e.preventDefault(); if(mem.hidden) showMem(); else mem.hidden=true; }); }

  // the few who want to choose clips: the picker opens under the chat; the
  // chat still writes the sentence and the picks ride along with it
  if(pickmode){
    pickmode.addEventListener('click', function(e){
      e.preventDefault();
      picker.hidden=!picker.hidden;
      pickmode.textContent = picker.hidden ? 'Choose my own clips' : 'Hide the clips';
      if(!picker.hidden){
        if(!q.value.trim() && curAsk) q.value=curAsk.slice(0,120);
        if(q.value.trim()) run();
        picker.scrollIntoView({behavior:'smooth', block:'start'});
      } else { picked={}; paint(); painBar(); }
    });
  }
  function send(){
    // the bottom bar's "Make it with these": picks without a sentence yet —
    // the chat asks what to make of them
    var n=Object.keys(picked).length;
    if(curAsk){ var b=document.querySelector('.offer .use:not(:disabled)'); if(b){ makeIt(b); return; } }
    hq.value='Make a video with the '+n+' clip'+(n===1?'':'s')+' I picked';
    document.getElementById('chat').scrollIntoView({behavior:'smooth', block:'start'});
    helperSend();
  }

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

  if(!q) return;
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


def app_page(email, role, event_title="Convention 2026", records=0, mode="make", greeting=None):
    """The front door (mode="make"): one box — say what you want — and a
    switch for the few who want to choose clips themselves (Michael, 17 Sep:
    "the majority of the requests are just people requesting with no need to
    select any footage"). mode="browse" is the Library on its own."""
    chips = "".join("<button class=\"chip\">%s</button>" % c for c in CHIPS)
    picker = (
        "<div class=\"searchbar\">"
        "<input type=\"text\" id=\"q\" autocomplete=\"off\" autocorrect=\"off\" "
        "placeholder=\"What are you looking for?\">"
        "<button id=\"go\">Search</button></div>"
        "<div class=\"chips\" id=\"chips\"><span class=\"lbl\">Try:</span>" + chips + "</div>"
        "<div class=\"tabs\" id=\"tabs\"></div>"
        "<div class=\"meta\" id=\"meta\"></div>"
        "<div id=\"out\"></div>"
        "<div class=\"more\" id=\"more\"></div>")
    if mode == "browse":
        main = ("<p class=\"h\" style=\"margin:0 0 14px\">Search the footage and what people said; tap a picture to watch. "
                "To make a video, go to <a href=\"/vi/\">Make a video</a>.</p>" + picker)
        bar = ""
    else:
        first = email.split("@")[0].split(".")[0].capitalize() if email else ""
        if not greeting:
            greeting = ("Hi%s. What are we making today? Tell me what's going on at the school \u2014 an event "
                        "coming up, new students you want, parents to fire up, who it is for and where it will "
                        "be posted \u2014 and I'll put a video together. Or just say \"you choose\"."
                        % (", " + first if first else ""))
        main = (
            "<section class=\"vichat\" id=\"chat\">"
            "<div class=\"log\" id=\"hlog\">"
            "<div class=\"msg bot\" id=\"hello\">" + _e(greeting) +
            "<div class=\"ideas\" id=\"ideas\"></div></div>"
            "</div>"
            "<div class=\"hin\"><textarea id=\"hq\" rows=\"1\" autocomplete=\"off\" "
            "placeholder=\"Say what you want\u2026\"></textarea>"
            "<button id=\"hsend\">Send</button></div>"
            "<p class=\"h\">Your videos appear under <strong>My videos</strong> in a few minutes. "
            "Prefer to pick the clips yourself? <a href=\"#\" id=\"pickmode\">Choose my own clips</a> "
            "&middot; <a href=\"#\" id=\"memlink\">What I remember about you</a></p>"
            "<div class=\"mem\" id=\"mem\" hidden></div>"
            "</section>"
            "<section id=\"picker\" class=\"picker\" hidden>"
            "<p class=\"h\">Tap <b>+</b> on the clips you want in &mdash; your picks always go in, in your "
            "order. Search for something else, then tell the chat what to make of them.</p>"
            + picker + "</section>")
        bar = ("<div class=\"bar\" id=\"bar\"><div class=\"in\">"
               "<span class=\"n\" id=\"barn\"></span>"
               "<button class=\"clr\" id=\"clr\">Clear</button>"
               "<button class=\"go\" id=\"ask\">Make it with these</button>"
               "</div></div>")
    body = (
        "<div class=\"wrap\">" + _head(email, event_title, tab=("library" if mode == "browse" else "make")) +
        "<main class=\"" + ("browse" if mode == "browse" else "make") + "\">" + main + "</main>"
        "<footer>%s moments from %s &middot; every result names the session and "
        "camera it came from.</footer>"
        "</div>" % ("{:,}".format(records), event_title) + bar
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
    """'Sep 14, 11:44 PM' in Victory's time (Eastern) from a datetime or its
    string form. The database keeps UTC; a request made at 9:15 PM in Orlando
    was showing as "1:15 AM" (16 Sep self-test). Never raises."""
    try:
        import datetime as _dt
        if isinstance(ts, str):
            ts = _dt.datetime.fromisoformat(ts.replace(" ", "T", 1)[:19])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=_dt.timezone.utc)
        try:
            import pytz                       # already a dependency of the app
            ts = ts.astimezone(pytz.timezone("America/New_York"))
        except Exception:
            try:
                from zoneinfo import ZoneInfo
                ts = ts.astimezone(ZoneInfo("America/New_York"))
            except Exception:
                pass
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
    if not isinstance(txt, dict):
        txt = {}
    if txt.get("parent"):
        h.append("<div class=\"ver\">Version %s &middot; cut again from <a href=\"#req%s\">Video #%s</a> "
                 "with your change: &ldquo;%s&rdquo;</div>"
                 % (txt.get("version") or 2, txt["parent"], txt["parent"], _e(txt.get("change") or "")))
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
            cid = str(it.get("id") or "").split(":")[-1]
            pic = ("<div class=\"mt\"><img loading=\"lazy\" alt=\"\" src=\"/vi/thumb/%s.jpg\" "
                   "onerror=\"this.parentNode.style.display='none'\"></div>" % _e(cid)) if it.get("kind") == "clip" else ""
            h.append("<div class=\"m\">%s<div class=\"t\">%s</div></div>"
                     % (pic, _e(it.get("title") or it.get("quote") or it.get("id"))))
        h.append("</div>")
    if st == "ready" or (st in ("approved", "delivered") and r.get("result_drive_id")):
        if r.get("preview_url"):
            # a placeholder, not a live player: twenty Drive players on one
            # page crashed Safari on Michael's phone (17 Sep, "a problem
            # repeatedly occurred"). The page opens the one you came for
            # (#reqN) or the newest; the rest load when tapped.
            h.append("<div class=\"player pl\" data-src=\"%s\" role=\"button\" tabindex=\"0\">"
                     "<span class=\"pb\">&#9654;&nbsp; Watch</span></div>" % _e(r["preview_url"]))
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
        if summ.get("skipped"):
            h.append("<div class=\"errbox warn\">"
                     "Could not find the recording for these picks, so they are not in this cut:\n%s</div>"
                     % "\n".join("\u2022 " + _e(x) for x in summ["skipped"]))
        if r.get("note"):
            try:
                import victory_cut as _vc
                h.append("<div class=\"brief\"><span class=\"k\">Understood as</span> %s</div>"
                         % _e(_vc.brief_for(r["note"], r.get("length_s"))["text"]))
            except Exception:
                pass
        if summ.get("no_room"):
            h.append("<div class=\"errbox warn\">"
                     "Picked, but no room in a %s-second video (ask for a longer one to fit them):\n%s</div>"
                     % (_e(str(r.get("length_s") or "")), "\n".join("\u2022 " + _e(x) for x in summ["no_room"])))
        if summ.get("speech_seconds"):
            bits.append("%ds of interview" % int(round(summ["speech_seconds"])))
        if summ.get("pace") and float(summ["pace"]) != 3.0:
            bits.append("%s pace" % ("fast" if float(summ["pace"]) < 3 else "slow"))
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
        # what would you change -> the next version, cut with that change
        # (Michael, 18 Sep). Empty box = the same brief cut again.
        h.append("<div class=\"fbh\">Not quite right? Say what to change and it gets cut again with that change.</div>"
                 "<textarea placeholder=\"e.g. use the demo team on stage in the red uniforms · less of the crowd · "
                 "slower · different music\" data-fb=\"%s\"></textarea>"
                 "<div class=\"acts\"><button data-recut=\"%s\">Cut it again</button>"
                 "<span class=\"fbs\" data-fbs=\"%s\"></span></div>" % (rid, rid, rid))
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
  // the button says what it will do as the person types
  document.addEventListener('input', function(e){
    var ta=e.target.closest('textarea[data-fb]'); if(!ta) return;
    var b=document.querySelector('button[data-recut="'+ta.getAttribute('data-fb')+'"]');
    if(b) b.textContent = ta.value.trim() ? 'Cut it again with this change' : 'Cut it again';
  });
  document.addEventListener('click', function(e){
    var b=e.target.closest('button[data-recut]');
    if(b){
      var id=b.getAttribute('data-recut'), ta=document.querySelector('textarea[data-fb="'+id+'"]');
      var s=document.querySelector('[data-fbs="'+id+'"]');
      var text=(ta&&ta.value.trim())||'';
      b.disabled=true; if(s) s.textContent = text ? 'Reading your change\u2026' : 'Back in the queue\u2026';
      post('/vi/recut',{id:parseInt(id,10), text:text}).then(function(d){
        if(!d.ok){ b.disabled=false; if(s) s.textContent = d.error||'That did not work.'; return; }
        if(d.same){ window.location.reload(); return; }
        if(s) s.textContent = (d.say||'Cutting it again.') + ' It will appear above as Video #'+d.id+'.';
        setTimeout(function(){ window.location.href='/vi/queue#req'+d.id; window.location.reload(); }, 1800);
      }).catch(function(){ b.disabled=false; if(s) s.textContent='That did not work.'; });
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
  // Drive players load one at a time: the card you came for (or the newest
  // finished one) opens by itself, the others on a tap
  function openPlayer(el){
    if(!el || el.querySelector('iframe')) return;
    var f=document.createElement('iframe');
    f.className='player'; f.src=el.getAttribute('data-src');
    f.setAttribute('allow','autoplay; fullscreen'); f.setAttribute('allowfullscreen','');
    el.parentNode.replaceChild(f, el);
  }
  document.addEventListener('click', function(e){
    var el=e.target.closest('.player.pl'); if(el){ e.preventDefault(); openPlayer(el); }
  });
  (function(){
    var want = (location.hash||'').replace('#','');
    var card = want ? document.getElementById(want) : null;
    var el = card ? card.querySelector('.player.pl') : null;
    if(!el) el = document.querySelector('.player.pl');
    openPlayer(el);
  })();
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
