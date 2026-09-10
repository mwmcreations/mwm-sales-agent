const SYN = {
  iconic:["candlelight","night of champions","winning","podium","medal","belt","break","celebration","arms raised","finale"],
  best:["candlelight","winning","podium","champion","medal","celebration","finale"],
  highlight:["candlelight","winning","champion","medal","celebration","night of champions"],
  emotional:["candlelight","proud","moms","cheering","celebration","family","mother"],
  powerful:["break","board","strike","champion","candlelight"],
  moment:["moments"],
  moments:["celebration","candlelight","winning","medal"],
  ceremony:["candlelight","belt","rank","presentation","masters"],
  candle:["candlelight","candles"],
  kids:["kid","children","child","students","youth"],
  children:["kid","kids","child","students"],
  parents:["mother","mom","moms","father","dad","family","proud"],
  crowd:["audience","cheering","spectators","packed"],
  win:["winning","winner","won","podium","medal","champion","victory"],
  winning:["winner","podium","medal","champion","arms raised"],
  champion:["champions","winning","podium","medal","night of champions"],
  blackbelt:["black belt","belt","testing","rank"],
  "black belt":["belt","testing","rank","presentation"],
  belt:["black belt","rank","presentation","testing"],
  break:["board","breaking","hammer fist","strike"],
  boards:["board","break","breaking"],
  sparring:["spar","fight","exchange","headgear"],
  forms:["form","kata","pattern","solo form"],
  weapons:["bo staff","staff","weapon"],
  training:["drill","drills","class","practice","seminar"],
  instructor:["instructors","teaching","coach","master","masters"],
  grandmaster:["grand master","master","masters","founder"],
  drone:["aerial","overhead"],
  perseverance:["persevere","never give up","keep going","push through","didn't quit","discipline","hard work"],
  respect:["respect","discipline","responsibility","courtesy"],
  confidence:["confident","self esteem","shy","believe"],
  community:["together","team","family","support","school"],
  tournament:["competition","finals","compete","competitor"],
  interview:["interviews","podcast","testimonial","said","says","talking"],
  quote:["said","says","interview","podcast"],
  speech:["address","talk","speaking","said"],
};

/* Queries that are asking for editorial peak rather than a subject.
   These lean on Victory's OWN priority markers — the call sheet's HERO/HIGH
   tags and the delivery's own category names — not on our opinion. */
const PEAK = /\b(iconic|best|greatest|highlight|highlights|top|standout|memorable|emotional|powerful|hero|strongest|moving)\b/i;

/* Queries that are asking for something SAID rather than something seen.
   "Grandmaster on perseverance" is the proposal's own headline example, and it
   must return a person speaking, not a wide shot of a hall. */
const SPEECH = /\b(on|about|talking|talks|speak|speaks|speaking|said|says|saying|quote|quotes|story|stories|testimonial|interview|explains|describes)\b|\b(perseverance|confidence|discipline|respect|gratitude|why|meaning)\b/i;

const norm = s => (s||"").toLowerCase().replace(/[^a-z0-9\s']/g," ").replace(/\s+/g," ").trim();
const STOP = new Set("the a an of from in on at to for with and or is are was were be been show me find get all any some that this it's our your my we i".split(" "));

function expand(q){
  const raw = norm(q);
  const toks = raw.split(" ").filter(w=>w && !STOP.has(w));
  const out = new Map();
  toks.forEach(t=>out.set(t,1.0));
  // multi-word keys first
  Object.keys(SYN).forEach(k=>{ if(k.includes(" ") && raw.includes(k)) SYN[k].forEach(s=>{ if(!out.has(s)) out.set(s,0.62); }); });
  toks.forEach(t=>{ (SYN[t]||[]).forEach(s=>{ if(!out.has(s)) out.set(s,0.62); }); });
  return out;
}

/* Word-boundary matching, not substring.
   "bo staff" must not match "aBOut", "BOard", "BOy" — which is exactly what a
   naive includes() does, and it turned a nine-result query into ninety-eight.
   A term matches a WHOLE word, or the START of a word when the term is long
   enough for that to mean something (so "candle" still reaches "candlelight"). */
function fieldHit(padded, term){
  if(padded.indexOf(" "+term+" ") !== -1) return 1.0;
  if(term.length >= 4 && padded.indexOf(" "+term) !== -1) return 0.75;
  return 0;
}

function score(rec, terms, peak, speech){
  let sc = 0, hits = 0;
  const title = " "+norm(rec.t)+" ", cat = " "+norm(rec.cat)+" ",
        ses = " "+norm(rec.ses)+" ", blob = " "+(rec.s||"")+" ";
  for(const [term,w] of terms){
    let got = 0;
    let h;
    if((h=fieldHit(title,term))) got = Math.max(got, 3.4*w*h);
    if((h=fieldHit(cat,term)))   got = Math.max(got, 2.5*w*h);
    if((h=fieldHit(ses,term)))   got = Math.max(got, 2.0*w*h);
    if((h=fieldHit(blob,term)))  got = Math.max(got, 1.15*w*h);
    if(got>0){ sc += got; hits++; }
  }
  if(hits===0) return 0;
  sc *= (1 + 0.16*(hits-1));               // several terms landing beats one landing hard
  sc += 2.9 * (rec.w||0.4) * (peak?1.9:1); // Victory's own priority markers
  if(peak && rec.k==="quote") sc *= 0.55;  // "iconic moments" wants pictures first
  if(speech){                              // "...on perseverance" wants a person speaking
    if(rec.k==="quote" && rec.qb) sc *= 1.85;
    else if(rec.k==="clip") sc *= 0.72;
  }
  if(rec.k==="quote" && rec.qb===false) sc *= 0.34;
  return sc;
}

function search(q){
  const peak = PEAK.test(q||"");
  const speech = SPEECH.test(q||"") && !peak;
  const terms = expand(q);
  if(!terms.size){
    return {rows: DATA.filter(r=>r.k==="clip").sort((a,b)=>b.w-a.w).slice(0,8), peak, speech, fallback:true};
  }
  let scored = DATA.map(r=>({r, s:score(r, terms, peak, speech)})).filter(x=>x.s>0)
                   .sort((a,b)=>b.s-a.s);
  /* Honesty floor. Synonym expansion is generous on purpose — it is what lets
     "iconic" reach the candlelight — but that generosity would let us print
     "171 moments found" for a query that really has nine good answers. Only
     results within reach of the best one are counted as found. */
  let rows = [];
  if(scored.length){
    const top = scored[0].s;
    rows = scored.filter(x=>x.s >= top*0.42).map(x=>x.r);
  }
  let fallback = false;
  if(!rows.length){ rows = DATA.filter(r=>r.k==="clip").sort((a,b)=>b.w-a.w); fallback = true; }
  return {rows, peak, speech, fallback};
}

