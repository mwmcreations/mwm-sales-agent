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
  function phoneFmt(d) { if (!d) return ""; if (d.length === 11 && d[0] === "1") return `(${d.slice(1, 4)}) ${d.slice(4, 7)}-${d.slice(7)}`; return "+" + d; }

  // an agent (or a test) may open the page with the admin secret in the URL; carry it to the API
  const SECRET = new URLSearchParams(location.search).get("secret") || "";
  function withAuth(path) { return SECRET ? path + (path.indexOf("?") >= 0 ? "&" : "?") + "secret=" + encodeURIComponent(SECRET) : path; }
  async function api(path) {
    const r = await fetch(withAuth(path), { credentials: "same-origin", headers: { "Accept": "application/json" } });
    if (r.status === 401) {
      let once = false; try { once = sessionStorage.getItem("desk.reloaded") === "1"; sessionStorage.setItem("desk.reloaded", "1"); } catch (e) {}
      if (!once) location.reload(); else toast("Signed out — open /desk/ to sign in again");
      throw new Error("signed out");
    }
    try { sessionStorage.removeItem("desk.reloaded"); } catch (e) {}
    const j = await r.json();
    if (!j.ok) throw new Error(j.error || "request failed");
    return j;
  }

  // ── badges ──
  const FLAG = {
    awaiting_reply: ["wait", "● awaiting reply"], michael: ["me", "Michael has it"], qualified: ["q", "qualified"],
    chasing: ["chase", "chasing"], first_touch_pending: ["chase", "first touch pending"], no_show: ["noshow", "no-show"],
    times_offered: ["wait", "times offered"], error: ["lost", "record error"],
  };
  function tags(c) {
    const out = [];
    if (c.booking && c.booking.when) out.push(`<span class="tag booked">📅 ${esc(c.booking.when)}</span>`);
    (c.flags || []).forEach(f => { const m = FLAG[f]; if (m) out.push(`<span class="tag ${m[0]}">${esc(m[1])}</span>`); });
    if (c.product && c.stage === "Client") out.push(`<span class="tag">${esc(c.product)}</span>`);
    if (c.test) out.push(`<span class="tag test">test</span>`);
    out.push(`<span class="tag src">${esc(c.source || "—")}</span>`);
    return out.join("");
  }
  function card(c) {
    const who = c.last_turn_role === "lead" ? "them" : (c.last_turn_role === "maya" ? "Maya" : "");
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
  function renderBoard() {
    const j = state.board; if (!j) return;
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
    const acts = `<div class="actions">
      <a class="${ph ? "" : "off"}" href="tel:${esc(ph)}"><span class="ico">📞</span>Call</a>
      <a class="${ph ? "" : "off"}" href="sms:${esc(ph)}"><span class="ico">💬</span>Text</a>
      <a class="${ph ? "" : "off"}" href="https://wa.me/${esc(L.phone || "")}" target="_blank" rel="noopener"><span class="ico">🟢</span>WhatsApp</a>
      <a class="${L.email ? "" : "off"}" href="mailto:${esc(L.email || "")}"><span class="ico">✉️</span>Email</a>
    </div>`;
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
      ${fact("Temperature", esc(L.temperature))}
      ${L.booking ? fact("Booked", esc(L.booking.when || "see calendar") + (L.booking.kind ? ` · ${esc(L.booking.kind.replace(/_/g, " "))}` : ""), true) : ""}
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
    const events = tl.events.length ? `<div class="tl">${tl.events.map(e => `<div class="ev ${esc(e.kind)}"><div class="t">${e.at ? when(e.at) : "—"}</div><div class="x">${esc(e.text)}</div></div>`).join("")}</div>` : `<div class="muted">No dated events on this record yet.</div>`;
    const turns = tl.turns.length ? `<div class="conv">${tl.turns.map(t => `<div class="bub ${t.role}"><span class="who">${t.role === "lead" ? L.name : "Maya"}</span>${esc(t.text)}${t.at ? `<span class="at">${when(t.at)}</span>` : ""}</div>`).join("")}</div>`
      : `<div class="muted">No conversation on this channel yet.</div>`;
    $("#panel-body").innerHTML = acts + (flags ? `<div class="meta" style="margin:-4px 0 12px;display:flex;gap:6px;flex-wrap:wrap">${flags}</div>` : "") + facts + notes +
      `<div class="section"><h3>Timeline</h3><span class="n">${tl.events.length} ${tl.events.length === 1 ? "event" : "events"}</span></div>${events}` +
      `<div class="section"><h3>Conversation</h3><span class="n">${tl.turns.length} ${tl.turns.length === 1 ? "message" : "messages"}</span></div>${turns}` +
      `<div class="soon">Actions (move stage, note, pause the chase, take over, send) arrive in slice 2.</div>`;
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
  });
  $("#q").addEventListener("input", () => { clearTimeout(qTimer); qTimer = setTimeout(doSearch, 220); });
  document.addEventListener("keydown", e => { if (e.key === "Escape" && !$("#panel").hidden) closeLead(); });
  window.addEventListener("popstate", () => { if (!$("#panel").hidden) closeLead(); });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });

  let saved = "board"; try { saved = localStorage.getItem("desk.tab") || "board"; } catch (e) {}
  show(saved);
  state.timer = setInterval(() => { if (!document.hidden && $("#panel").hidden) refresh(); }, 30000);
})();
