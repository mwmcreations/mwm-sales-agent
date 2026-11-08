/* MWM Desk — slice 1: see. Vanilla JS, no build step. */
(function () {
  "use strict";
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const state = { tab: "board", only: "", board: null, inbox: null, lead: null, q: "", timer: null, busy: false };

  // ── helpers ──
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
  function rel(iso) {
    if (!iso) return "";
    const d = new Date(iso); if (isNaN(d)) return "";
    const s = Math.round((Date.now() - d.getTime()) / 1000);
    if (s < 60) return "now"; if (s < 3600) return Math.floor(s / 60) + "m"; if (s < 86400) return Math.floor(s / 3600) + "h";
    if (s < 86400 * 7) return Math.floor(s / 86400) + "d";
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
  function when(iso) {
    if (!iso) return ""; const d = new Date(iso); if (isNaN(d)) return iso;
    return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  }
  function toast(msg) { const t = $("#toast"); t.textContent = msg; t.hidden = false; clearTimeout(t._h); t._h = setTimeout(() => t.hidden = true, 2400); }
  function shortDate(iso) { if (!iso) return ""; const d = new Date(iso); return isNaN(d) ? "" : d.toLocaleDateString(undefined, { month: "short", day: "numeric" }); }
  function phoneFmt(d) { if (!d) return ""; if (d.length === 11 && d[0] === "1") return `(${d.slice(1, 4)}) ${d.slice(4, 7)}-${d.slice(7)}`; return "+" + d; }

  // an agent (or a test) may open the page with the admin secret in the URL; carry it to the API
  const SECRET = new URLSearchParams(location.search).get("secret") || "";
  function withAuth(path) { return SECRET ? path + (path.indexOf("?") >= 0 ? "&" : "?") + "secret=" + encodeURIComponent(SECRET) : path; }
  async function api(path, body) {
    const opts = { credentials: "same-origin", headers: { "Accept": "application/json" } };
    if (body !== undefined) { opts.method = "POST"; opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    const r = await fetch(withAuth(path), opts);
    if (r.status === 401) {
      // signed out (or a cookie that did not travel): reload ONCE a minute at most, never a loop
      let last = 0; try { last = parseInt(sessionStorage.getItem("desk.reloaded_at") || "0", 10) || 0; } catch (e) {}
      if (Date.now() - last > 60000) { try { sessionStorage.setItem("desk.reloaded_at", String(Date.now())); } catch (e) {} location.reload(); }
      else toast("Signed out — open /desk/ to sign in again");
      throw new Error("signed out");
    }
    let j = null; try { j = await r.json(); } catch (e) { throw new Error(r.ok ? "Unreadable answer from the server" : `Server error (${r.status})`); }
    if (!j.ok) throw new Error(j.error || j.message || `Request failed (${r.status})`);
    return j;
  }

  // ── badges ──
  const FLAG = {
    awaiting_reply: ["wait", "● awaiting reply"], michael: ["me", "Michael has it"], qualified: ["q", "qualified"],
    chasing: ["chase", "chasing"], first_touch_pending: ["chase", "first touch pending"], no_show: ["noshow", "no-show"],
    times_offered: ["wait", "times offered"], error: ["lost", "record error"], visit_passed: ["noshow", "visit passed — outcome?"], outcome_missing: ["", "outcome not recorded"],
  };
  const TEMP = { scorching: "🔥 scorching", hot: "🔥 hot", warm: "warm", cool: "cool", cold: "cold" };
  function tags(c) {
    const out = [];
    if (c.booking) { const b = c.booking; const label = b.when || (b.at ? "booked " + shortDate(b.at) : "booked");
      out.push(`<span class="tag ${b.passed ? "" : "booked"}">📅 ${esc(label)}${b.passed && b.when ? " · passed" : ""}</span>`); }
    (c.flags || []).forEach(f => { const m = FLAG[f]; if (m) out.push(`<span class="tag ${m[0]}">${esc(m[1])}</span>`); });
    if (c.product && c.stage === "Client") out.push(`<span class="tag">${esc(c.product)}</span>`);
    if (c.temperature && TEMP[c.temperature]) out.push(`<span class="tag temp ${esc(c.temperature)}">${TEMP[c.temperature]}</span>`);
    if (c.test) out.push(`<span class="tag test">test</span>`);
    out.push(`<span class="tag src">${esc(c.source || "—")}</span>`);
    return out.join("");
  }
  function card(c) {
    const who = c.last_turn_role === "lead" ? "them" : (c.last_turn_role === "maya" ? "Maya" : (c.last_turn_role === "michael" ? "Michael" : ""));
    const snip = c.snippet ? `<div class="snip ${c.last_turn_role === "lead" ? "lead" : ""}">${who ? `<span class="who">${who}: </span>` : ""}${esc(c.snippet)}</div>` : "";
    return `<button class="card" data-key="${esc(c.key)}">
      <div class="row1"><span class="nm">${esc(c.name)}</span><span class="when">${rel(c.last_activity)}</span></div>
      ${c.business && c.business !== c.name ? `<div class="biz">${esc(c.business)}</div>` : ""}
      ${snip}
      <div class="meta">${tags(c)}</div>
    </button>`;
  }

  // ── board ──
  async function loadBoard() {
    const el = $("#board"); if (!state.board) el.innerHTML = `<div class="skel">Loading the board…</div>`;
    try {
      const j = await api("/desk/api/board"); state.board = j; renderBoard(); $("#asof").textContent = "as of " + when(j.as_of);
      const b = $("#inbox-badge"); if (j.awaiting_reply) { b.textContent = j.awaiting_reply; b.hidden = false; } else b.hidden = true;
    } catch (e) { el.innerHTML = `<div class="skel">Could not load the board — ${esc(e.message)}</div>`; }
  }
  async function loadToday() {
    const el = $("#today"); if (!el) return;
    try {
      const j = await api("/desk/api/report/meetings?range=today");
      const ms = j.meetings || [];
      el.innerHTML = `<div class="today-head"><span>Today</span><span class="n">${ms.length ? ms.length + (ms.length === 1 ? " event" : " events") : "nothing on the calendar"}</span></div>` +
        (ms.length ? `<div class="today-row">${ms.map(m => `<div class="today-ev"><div class="t">${esc(m.time)}</div><div class="nm">${esc(m.name)}</div>${m.business ? `<div class="biz">${esc(m.business)}</div>` : ""}
          <button class="btn small report-ev" data-name="${esc(m.name)}" data-business="${esc(m.business || "")}" data-event="${esc(m.event_id)}">Report</button></div>`).join("")}</div>` : "");
      el.hidden = false;
    } catch (e) { el.hidden = true; }   // a report problem never touches the board
  }
  function renderBoard() {
    const j = state.board; if (!j) return;
    loadToday();
    const main = j.stages.filter(s => ["Paused", "Lost"].indexOf(s) < 0), side = ["Paused", "Lost"];
    $("#board-summary").innerHTML = `<span class="pill"><b>${j.total}</b> leads</span>` +
      `<span class="pill ${j.awaiting_reply ? "hot" : ""}"><b>${j.awaiting_reply}</b> awaiting a reply</span>` +
      `<span class="pill"><b>${j.counts.Booked || 0}</b> booked</span><span class="pill"><b>${j.counts.Client || 0}</b> clients</span>`;
    $("#board").innerHTML = main.concat(side).map(s => {
      const cards = j.columns[s] || [];
      return `<div class="col" data-stage="${s}">
        <div class="col-head"><span class="name"><span class="sw" style="background:var(--s-${s.toLowerCase()})"></span>${s}</span><span class="n">${j.counts[s] || 0}</span></div>
        <div class="col-body">${cards.length ? cards.map(card).join("") : `<div class="empty">Nobody here</div>`}</div>
      </div>`;
    }).join("");
  }

  // ── inbox ──
  async function loadInbox() {
    const el = $("#inbox"); if (!state.inbox) el.innerHTML = `<div class="skel">Loading…</div>`;
    try {
      const j = await api("/desk/api/inbox?limit=200" + (state.only ? "&only=" + state.only : "")); state.inbox = j; renderInbox();
    } catch (e) { el.innerHTML = `<div class="skel">Could not load the inbox — ${esc(e.message)}</div>`; }
  }
  function renderInbox() {
    const j = state.inbox; if (!j) return;
    $("#inbox").innerHTML = j.rows.length ? j.rows.map(card).join("") : `<div class="empty">Nothing here.</div>`;
  }

  // ── search ──
  let qTimer = null;
  async function doSearch() {
    const q = $("#q").value.trim(); state.q = q; const el = $("#results");
    if (!q) { el.innerHTML = `<div class="empty">Type to search.</div>`; return; }
    try { const j = await api("/desk/api/search?q=" + encodeURIComponent(q)); el.innerHTML = j.rows.length ? j.rows.map(card).join("") : `<div class="empty">No lead matches “${esc(q)}”.</div>`; }
    catch (e) { el.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  }

  // ── lead panel ──
  async function openLead(key) {
    const p = $("#panel"); p.hidden = false; document.body.style.overflow = "hidden";
    $("#p-name").textContent = "…"; $("#p-sub").textContent = ""; $("#p-stage").textContent = ""; $("#panel-body").innerHTML = `<div class="skel">Loading…</div>`;
    try { const j = await api("/desk/api/lead/" + encodeURIComponent(key)); state.lead = j.lead; renderLead(j.lead); }
    catch (e) { $("#panel-body").innerHTML = `<div class="skel">${esc(e.message)}</div>`; }
  }
  function closeLead() { $("#panel").hidden = true; document.body.style.overflow = ""; state.lead = null; }
  function fact(k, v, wide) { if (v == null || v === "" || v === false) return ""; return `<div class="fact ${wide ? "wide" : ""}"><div class="k">${esc(k)}</div><div class="v">${v}</div></div>`; }
  function renderLead(L) {
    $("#p-name").textContent = L.name; $("#p-sub").textContent = [L.business && L.business !== L.name ? L.business : "", L.source].filter(Boolean).join(" · ");
    const st = $("#p-stage"); st.textContent = L.stage; st.dataset.s = L.stage;
    const ph = L.phone ? "+" + L.phone : "";
    const manual = !!(L.flags || []).includes("michael");
    const chasing = L.chase && !L.chase.stopped;
    const canResume = L.chase && (L.chase.stopped === "manual" || L.chase.stopped === "manual_paused");
    const acts = `<div class="actions">
      <a class="${ph ? "" : "off"}" href="tel:${esc(ph)}"><span class="ico">📞</span>Call</a>
      <a class="${ph ? "" : "off"}" href="sms:${esc(ph)}"><span class="ico">💬</span>Text</a>
      <a class="${ph ? "" : "off"}" href="https://wa.me/${esc(L.phone || "")}" target="_blank" rel="noopener"><span class="ico">🟢</span>WhatsApp</a>
      <a class="${L.email ? "" : "off"}" href="mailto:${esc(L.email || "")}"><span class="ico">✉️</span>Email</a>
    </div>
    <div class="actions acts2">
      <button class="act" data-act="report"><span class="ico">📋</span>Report</button>
      <button class="act" data-act="move"><span class="ico">↔</span>Move</button>
      <button class="act" data-act="note"><span class="ico">✎</span>Note</button>
      ${L.chase ? `<button class="act ${(!chasing && !canResume) ? "off" : ""}" data-act="${chasing ? "chase-pause" : "chase-resume"}"><span class="ico">${chasing ? "⏸" : "▶"}</span>${chasing ? "Pause chase" : "Resume chase"}</button>`
                : `<button class="act off"><span class="ico">⏸</span>No chase</button>`}
      <button class="act ${ph ? "" : "off"}" data-act="${manual ? "release" : "takeover"}"><span class="ico">${manual ? "🤖" : "🙋"}</span>${manual ? "Give back" : "Take over"}</button>
    </div>
    ${manual && L.manual_until ? `<div class="hint">You have this conversation; Maya holds replies until ${when(L.manual_until)}.</div>` : ""}`;
    const ft = L.first_touch || {};
    const ftTxt = ft.whatsapp ? `WhatsApp ${esc(ft.whatsapp.status)}${ft.whatsapp.at ? " · " + when(ft.whatsapp.at) : ""}` :
      ft.sms ? `SMS · ${when(ft.sms.at)}` : (ft.sms_pending ? `SMS waiting (${esc(ft.sms_pending.reason)})` : (ft.whatsapp_pending ? "WhatsApp waiting for the window" : ""));
    const ch = L.chase ? `${esc(L.chase.kind || "chase")} · ${L.chase.sent} sent${L.chase.stopped ? " · stopped: " + esc(L.chase.stopped) : (L.chase.armed_at ? " · armed " + rel(L.chase.armed_at) + " ago" : "")}` : "";
    const consent = L.consent && Object.keys(L.consent).length ? Object.entries(L.consent).map(([k, v]) => `${esc(k.replace(/_/g, " "))}: ${v === true ? "yes" : v === false ? "no" : esc(String(v))}`).join(" · ") : "";
    const facts = `<div class="facts">
      ${fact("Phone", ph ? `<a href="tel:${esc(ph)}">${esc(phoneFmt(L.phone))}</a>` : "")}
      ${fact("Email", L.email ? `<a href="mailto:${esc(L.email)}">${esc(L.email)}</a>` : "")}
      ${fact("Business", esc(L.business))}
      ${fact("Source", esc(L.source) + (L.channel && L.channel !== (L.source || "").toLowerCase() ? ` · ${esc(L.channel)}` : ""))}
      ${fact("First seen", L.first_seen ? when(L.first_seen) : "")}
      ${fact("Last activity", L.last_activity ? when(L.last_activity) : "")}
      ${fact("Qualified", L.qualified ? "yes" + (L.form && L.form.qualified_reason ? " — " + esc(L.form.qualified_reason) : "") : "")}
      ${fact("Maya's read", L.temperature ? (TEMP[L.temperature] || esc(L.temperature)) : "")}
      ${L.quiet_days != null && L.quiet_days >= 7 ? fact("Quiet for", Math.round(L.quiet_days) + " days") : ""}
      ${L.booking ? fact("Booked", esc(L.booking.when || (L.booking.at ? "on " + when(L.booking.at) + " (time not on record)" : "see calendar")) + (L.booking.kind ? ` · ${esc(L.booking.kind.replace(/_/g, " "))}` : "") + (L.booking.passed && !L.outcome ? " · <b>the visit is behind us — outcome not recorded</b>" : ""), true) : ""}
      ${L.outcome ? fact("Visit outcome", esc(L.outcome.last.replace(/_/g, " ")) + (L.outcome.at ? " · " + when(L.outcome.at) : ""), true) : ""}
      ${L.paid ? fact("Client since", when(L.paid.at) + (L.paid.product ? " · " + esc(L.paid.product) : ""), true) : ""}
      ${ftTxt ? fact("First touch", ftTxt, true) : ""}
      ${ch ? fact("Chase", ch, true) : ""}
      ${L.offers && L.offers.slots && L.offers.slots.length ? fact("Times offered", L.offers.slots.map(s => esc(typeof s === "object" ? (s.display || s.id) : s)).join(" · "), true) : ""}
      ${consent ? fact("Consent", consent, true) : ""}
      ${L.form && L.form.role_raw ? fact("Role", esc(L.form.role_raw)) : ""}
      ${L.form && L.form.revenue_raw ? fact("Revenue band", esc(L.form.revenue_raw)) : ""}
      ${L.form && L.form.must_understand ? fact("Customers must understand", esc(L.form.must_understand), true) : ""}
      ${L.form && L.form.ad_name ? fact("Ad", esc(L.form.ad_name), true) : ""}
    </div>`;
    const flags = (L.flags || []).map(f => { const m = FLAG[f]; return m ? `<span class="tag ${m[0]}">${esc(m[1])}</span>` : ""; }).join(" ");
    const notes = (L.notes || []).length ? `<div class="section"><h3>Notes</h3></div>` + L.notes.map(n => `<div class="note">${esc(typeof n === "object" ? (n.text || JSON.stringify(n)) : n)}</div>`).join("") : "";
    const tl = L.timeline || { events: [], turns: [] };
    const events = tl.events.length ? `<div class="tl">${tl.events.map(e => `<div class="ev ${esc(e.kind)}"><div class="t">${e.at ? when(e.at) : "—"}${e.by ? ` · ${esc(e.by)}` : ""}</div><div class="x">${esc(e.text)}</div></div>`).join("")}</div>` : `<div class="muted">No dated events on this record yet.</div>`;
    const turns = tl.turns.length ? `<div class="conv">${tl.turns.map(t => `<div class="bub ${t.role}"><span class="who">${t.role === "lead" ? L.name : (t.role === "michael" ? "Michael" : "Maya")}</span>${esc(t.text)}${t.at ? `<span class="at">${when(t.at)}</span>` : ""}</div>`).join("")}</div>`
      : `<div class="muted">No conversation on this channel yet.</div>`;
    const chan = L.key.startsWith("instagram:") ? "Instagram DM" : (L.channel === "sms" ? "SMS" : "WhatsApp");
    const sendBox = L.stage === "Lost" && (L.consent || {}).do_not_contact ? `<div class="hint">Do-not-contact: no messages from here.</div>` :
      `<div class="sendbox"><textarea id="send-text" rows="2" placeholder="Write to ${esc(L.name)} on ${chan}…"></textarea>
       <div class="send-row"><span class="muted">${chan}</span><span class="grow"></span>
       <button class="btn ghost" data-act="send-maya">Send as Maya</button><button class="btn" data-act="send-michael">Send as Michael</button></div></div>`;
    $("#panel-body").innerHTML = acts + (flags ? `<div class="meta" style="margin:-4px 0 12px;display:flex;gap:6px;flex-wrap:wrap">${flags}</div>` : "") + facts + notes +
      `<div class="section"><h3>Timeline</h3><span class="n">${tl.events.length} ${tl.events.length === 1 ? "event" : "events"}</span></div>${events}` +
      `<div class="section"><h3>Conversation</h3><span class="n">${tl.turns.length} ${tl.turns.length === 1 ? "message" : "messages"}</span></div>${turns}` + sendBox;
  }

  // ── actions (slice 2) ──
  async function act(path, body, okMsg) {
    if (state.busy) return; state.busy = true;
    try { const j = await api(path, body || {}); if (j.lead) { state.lead = j.lead; renderLead(j.lead); } toast(okMsg || "Done"); state.board = null; return j; }
    catch (e) { toast(e.message || "That did not work"); }
    finally { state.busy = false; }
  }
  function leadPath(suffix) { return "/desk/api/lead/" + encodeURIComponent(state.lead.key) + "/" + suffix; }
  function sheet(html) { const s = $("#sheet"); $("#sheet-body").innerHTML = html; s.hidden = false; }
  function closeSheet() { $("#sheet").hidden = true; }
  function moveSheet(L) {
    sheet(`<h3>Move ${esc(L.name)}</h3><p class="muted">Booked, Visited and Client come from a booking, a report or a payment — this parks or closes a lead by hand.</p>
      <div class="opts">
        <button class="opt" data-stage="Paused"><b>Paused</b><span>Park it; the chase stops; it stays searchable</span></button>
        <button class="opt" data-stage="Lost"><b>Lost</b><span>Close it; the chase stops; no do-not-contact</span></button>
        <button class="opt" data-stage="Reopen"><b>Reopen</b><span>Back to where the facts put it; a paused chase resumes</span></button>
        <button class="opt danger" data-dnc="${(L.consent || {}).do_not_contact ? "0" : "1"}"><b>${(L.consent || {}).do_not_contact ? "Lift do-not-contact" : "Do not contact"}</b><span>${(L.consent || {}).do_not_contact ? "Allow messages again" : "Blocks every automated message and SMS to this person"}</span></button>
      </div><input id="move-reason" placeholder="Reason (optional)">`);
  }
  function noteSheet(L) { sheet(`<h3>Note on ${esc(L.name)}</h3><textarea id="note-text" rows="4" placeholder="What you want the record to remember…"></textarea><div class="send-row"><span class="grow"></span><button class="btn" data-act="note-save">Save note</button></div>`); setTimeout(() => $("#note-text").focus(), 50); }
  function takeoverSheet(L) { sheet(`<h3>Take over ${esc(L.name)}</h3><p class="muted">Maya holds her replies on this phone while you talk. She picks the thread back up when the time runs out, or when you hand it back.</p>
    <div class="opts"><button class="opt" data-hours="1"><b>1 hour</b></button><button class="opt" data-hours="2"><b>2 hours</b></button><button class="opt" data-hours="8"><b>Rest of the day</b><span>8 hours</span></button><button class="opt" data-hours="24"><b>Until tomorrow</b><span>24 hours</span></button></div>`); }
  const OUTCOMES = [["client_won", "🎉 Client won"], ["follow_up", "🔄 Follow-up needed"], ["studio_package_pitched", "📦 Studio package pitched"], ["completed", "✅ Completed (existing client)"], ["not_interested", "❌ Not interested"], ["no_show", "🚫 No-show"]];
  function reportSheet(pre) {
    state.report = pre;
    sheet(`<h3>Daily Event Report</h3><p class="muted">${esc(pre.name)}${pre.business ? " · " + esc(pre.business) : ""}${pre.event_id ? "" : " · no calendar event linked"}</p>
      <div class="opts outcomes">${OUTCOMES.map(([v, l]) => `<button class="opt" data-outcome="${v}"><b>${l}</b></button>`).join("")}</div>
      <input id="rep-service" placeholder="Service discussed (optional)">
      <textarea id="rep-notes" rows="3" placeholder="Notes"></textarea>
      <textarea id="rep-next" rows="2" placeholder="Next steps (optional)"></textarea>
      <div class="send-row"><span class="muted" id="rep-chosen">Pick the outcome</span><span class="grow"></span><button class="btn" data-act="report-submit" disabled>File report</button></div>`);
  }
  async function submitReport() {
    const pre = state.report || {}; const outcome = pre.outcome; if (!outcome) { toast("Pick the outcome first"); return; }
    const body = { name: pre.name, business: pre.business || "", outcome, notes: $("#rep-notes").value.trim(), service: $("#rep-service").value.trim(), next_steps: $("#rep-next").value.trim(), event_id: pre.event_id || "" };
    try {
      state.busy = true;
      const r = await fetch(withAuth("/desk/api/report/submit"), { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "Accept": "application/json" }, body: JSON.stringify(body) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || !j.ok) throw new Error(j.message || j.error || "The report was not accepted");
      toast(j.message || "Report filed"); closeSheet(); state.board = null;
      if (state.lead && pre.key === state.lead.key) openLead(state.lead.key); else refresh();
    } catch (e) { toast(e.message); } finally { state.busy = false; }
  }

  // ── tabs & wiring ──
  function show(tab) {
    state.tab = tab; $$(".tab").forEach(t => t.classList.toggle("on", t.dataset.tab === tab));
    $$(".view").forEach(v => v.hidden = v.id !== "view-" + tab);
    if (tab === "board") loadBoard(); else if (tab === "inbox") loadInbox(); else if (tab === "search") setTimeout(() => $("#q").focus(), 50);
    try { localStorage.setItem("desk.tab", tab); } catch (e) {}
  }
  function refresh() { if (state.tab === "board") loadBoard(); else if (state.tab === "inbox") loadInbox(); else doSearch(); }

  document.addEventListener("click", e => {
    const c = e.target.closest(".card"); if (c) { openLead(c.dataset.key); return; }
    const t = e.target.closest(".tab"); if (t) { show(t.dataset.tab); return; }
    const ch = e.target.closest(".chip"); if (ch) { $$(".chip").forEach(x => x.classList.toggle("on", x === ch)); state.only = ch.dataset.only || ""; state.inbox = null; loadInbox(); return; }
    if (e.target.closest("#panel-close")) { closeLead(); return; }
    if (e.target.closest("#refresh")) { refresh(); toast("Refreshed"); return; }
    if (e.target.closest("#sheet-close") || e.target === $("#sheet")) { closeSheet(); return; }
    const rev = e.target.closest(".report-ev"); if (rev) { reportSheet({ name: rev.dataset.name, business: rev.dataset.business, event_id: rev.dataset.event }); return; }
    const a = e.target.closest("[data-act]"); if (a && state.lead) {
      const L = state.lead, act_ = a.dataset.act;
      if (act_ === "report") reportSheet({ key: L.key, name: L.name, business: L.business, event_id: L.booking ? L.booking.event_id : "" });
      else if (act_ === "move") moveSheet(L);
      else if (act_ === "note") noteSheet(L);
      else if (act_ === "note-save") { const t = $("#note-text").value.trim(); if (t) { closeSheet(); act(leadPath("note"), { text: t }, "Note saved"); } }
      else if (act_ === "chase-pause") act(leadPath("chase"), { action: "pause" }, "Chase paused");
      else if (act_ === "chase-resume") act(leadPath("chase"), { action: "resume" }, "Chase resumed");
      else if (act_ === "takeover") takeoverSheet(L);
      else if (act_ === "release") act(leadPath("takeover"), { action: "release" }, "Handed back to Maya");
      else if (act_ === "send-maya" || act_ === "send-michael") { const t = $("#send-text").value.trim(); if (!t) { toast("Write something first"); return; }
        act(leadPath("send"), { text: t, as: act_ === "send-maya" ? "maya" : "michael" }, "Sent").then(j => { if (j && j.ok) { const tb = $("#send-text"); if (tb) tb.value = ""; } }); }
      else if (act_ === "report-submit") submitReport();
      return;
    }
    const oc0 = e.target.closest(".opt[data-outcome]"); if (oc0) {
      $$(".outcomes .opt").forEach(x => x.classList.toggle("on", x === oc0)); state.report = Object.assign(state.report || {}, { outcome: oc0.dataset.outcome });
      $("#rep-chosen").textContent = oc0.querySelector("b").textContent; const b = $("[data-act='report-submit']"); if (b) b.disabled = false; return;
    }
    const rs = e.target.closest("[data-act='report-submit']"); if (rs) { submitReport(); return; }
    const opt = e.target.closest(".opt"); if (opt && state.lead) {
      if (opt.dataset.stage) { const reason = ($("#move-reason") || {}).value || ""; closeSheet(); act(leadPath("stage"), { stage: opt.dataset.stage, reason }, "Moved"); }
      else if (opt.dataset.dnc !== undefined) { closeSheet(); act(leadPath("dnc"), { on: opt.dataset.dnc === "1" }, opt.dataset.dnc === "1" ? "Do-not-contact set" : "Do-not-contact lifted"); }
      else if (opt.dataset.hours) { closeSheet(); act(leadPath("takeover"), { action: "take", hours: opt.dataset.hours }, "You have the conversation"); }
      return;
    }
    const oc = e.target.closest(".opt[data-outcome]"); if (oc) {
      $$(".outcomes .opt").forEach(x => x.classList.toggle("on", x === oc)); state.report = Object.assign(state.report || {}, { outcome: oc.dataset.outcome });
      $("#rep-chosen").textContent = oc.querySelector("b").textContent; const b = $("[data-act='report-submit']"); if (b) b.disabled = false; return;
    }
  });
  $("#q").addEventListener("input", () => { clearTimeout(qTimer); qTimer = setTimeout(doSearch, 220); });
  document.addEventListener("keydown", e => { if (e.key === "Escape") { if (!$("#sheet").hidden) closeSheet(); else if (!$("#panel").hidden) closeLead(); } });
  window.addEventListener("popstate", () => { if (!$("#panel").hidden) closeLead(); });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });

  let saved = "board"; try { saved = localStorage.getItem("desk.tab") || "board"; } catch (e) {}
  show(saved);
  state.timer = setInterval(() => { if (!document.hidden && $("#panel").hidden) refresh(); }, 30000);
})();
