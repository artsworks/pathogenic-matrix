/* global EventSource */
const $ = (id) => document.getElementById(id);
let catalog = { source: "", bodyparts: [], mutations: [] };
let lastState = null;
let lastRec = { groups: [] };
const openDetails = new Set();

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

// Game tooltips use Godot BBCode plus {placeholders}; keep bold/italic, drop the rest.
function bbToHtml(s) {
  return esc(s)
    .replace(/\[b\]/g, "<b>").replace(/\[\/b\]/g, "</b>")
    .replace(/\[i\]/g, "<i>").replace(/\[\/i\]/g, "</i>")
    .replace(/\{hr\}/g, "<hr>")
    .replace(/\[\/?[^\]]*\]/g, "")
    .replace(/\{\/?[a-z_]+\}/gi, "")
    .replace(/\n/g, "<br>");
}

function connect() {
  const es = new EventSource("/events");
  es.onmessage = (e) => {
    const data = JSON.parse(e.data);
    if (data.catalog) catalog = data.catalog;
    lastState = data.state;
    lastRec = data.rec || lastRec;
    render();
  };
  es.onopen = () => setConn(true);
  es.onerror = () => setConn(false);
}

function setConn(live) {
  const el = $("conn");
  el.className = "conn " + (live ? "live" : "offline");
  el.textContent = live ? "connected" : "offline";
}

function render() {
  renderMeta(lastState);
  renderChoices(lastState, lastRec);
  renderVitals(lastState);
  renderBuild(lastState);
  renderCatalog();
}

function renderMeta(s) {
  if (!s) { $("meta").textContent = "waiting for the game…"; return; }
  $("meta").textContent = [
    s.parasite,
    s.room ? `${s.room.type || ""} ${s.room.name || ""}`.trim() : null,
    s.level_number ? `level ${s.level_number}` : null,
    s.shopkeeper_angered ? "shopkeeper angered" : null,
    `${catalog.source || "no"} catalog`,
    s.mod_version ? `mod ${s.mod_version}` : null,
  ].filter(Boolean).join(" · ");
}

function scoreText(p) {
  if (p.score_per_cost != null && p.score_per_cost !== p.score) return `${p.score_per_cost.toFixed(2)}/cost`;
  return p.score.toFixed(1);
}

function rawDetails(o) {
  const rows = [];
  if (o.type) rows.push(["Type", o.type]);
  if (o.rarity) rows.push(["Rarity", o.rarity]);
  if (o.rarity_range) rows.push(["Rarity range", o.rarity_range.join(" – ")]);
  if (o.cost != null) rows.push(["Cost", `${o.cost}${o.pay_with_blood ? " max HP" : "¢"}`]);
  if (o.tags && o.tags.length) rows.push(["Tags", o.tags.join(", ")]);
  if (o.needs_connection && o.needs_connection.length) rows.push(["Needs adjacent", o.needs_connection.join(", ")]);
  if (o.bonus_damage) rows.push(["Bonus damage", `${Math.round(o.bonus_damage * 100)}%`]);
  if (o.bonus_hp) rows.push(["Bonus HP", o.bonus_hp]);
  const table = rows.map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`).join("");
  const text = o.tooltip || o.description || "";
  return `<table class="raw">${table}</table>${text ? `<div class="tooltip">${bbToHtml(text)}</div>` : ""}`;
}

function renderChoices(s, rec) {
  const body = $("choices-body");
  if (!rec || !rec.ok || !rec.groups.length) {
    body.innerHTML = `<p class="dim">${s && s.in_run ? "No pending choices detected." : "Not in a run."}</p>`;
    return;
  }
  body.innerHTML = "";
  for (const g of rec.groups) {
    const div = document.createElement("div");
    div.className = "choice-group";
    const best = g.picks[0];
    const summary = g.picks.map((p) => esc(p.label.split(" — ")[0])).join(" &gt; ");
    div.innerHTML = `<h3>${esc(g.title)}</h3>
      <div class="summary">${best && g.picks.length > 1 ? `<b>${esc(best.label)}</b><br>` : ""}<span class="dim">${summary}</span></div>`;
    g.picks.forEach((p, i) => {
      const id = `${g.choice_id}|${p.key}`;
      const el = document.createElement("details");
      el.className = "pick" + (i === 0 && g.picks.length > 1 ? " best" : "");
      el.open = openDetails.has(id);
      el.addEventListener("toggle", () => (el.open ? openDetails.add(id) : openDetails.delete(id)));
      const firstReason = p.reasons[0] || "";
      const firstWarn = p.warnings[0] || "";
      el.innerHTML = `
        <summary><div class="head"><span>${esc(p.label)}</span><span class="score">${scoreText(p)}</span></div>
        <div class="sub">${esc(firstReason)}${firstWarn ? ` <span class="warn-inline">${esc(firstWarn)}</span>` : ""}</div></summary>
        ${p.reasons.length ? `<ul class="reasons">${p.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}
        ${p.warnings.length ? `<div class="warns">${p.warnings.map(esc).join("<br>")}</div>` : ""}
        ${rawDetails(p.option || {})}`;
      div.appendChild(el);
    });
    body.appendChild(div);
  }
}

function renderVitals(s) {
  const p = s && s.player;
  const setBar = (id, v, max, txt) => {
    $(id + "-bar").style.width = max ? Math.min(100, (v / max) * 100) + "%" : "0%";
    $(id + "-txt").textContent = txt != null ? txt : `${Math.round(v)}/${Math.round(max)}`;
  };
  if (!p) {
    setBar("hp", 0, 1, "—"); setBar("stam", 0, 1, "—"); setBar("dna", 0, 1, "—");
    $("armor").textContent = "—"; $("money").textContent = "—"; $("level").textContent = "—";
    return;
  }
  setBar("hp", p.hp, p.max_hp);
  setBar("stam", p.stamina, p.max_stamina);
  setBar("dna", p.dna, p.dna_to_level_up, `${p.dna}/${p.dna_to_level_up}`);
  $("armor").textContent = p.armor;
  $("money").textContent = `${p.money}¢`;
  $("level").textContent = p.level;
}

function renderBuild(s) {
  const slots = (s && s.player && s.player.slots) || [];
  const draw = (list, el) => {
    el.innerHTML = list.length ? "" : `<span class="dim">none</span>`;
    for (const sl of list) {
      const d = document.createElement("div");
      const b = sl.bodypart;
      d.className = "slot" + (b ? "" : " empty");
      d.title = b && b.tooltip ? bbToHtml(b.tooltip).replace(/<[^>]+>/g, " ") : "";
      d.innerHTML = `
        <div class="sname">${esc(sl.slot)}${sl.connects_to && sl.connects_to.length ? ` → ${esc(sl.connects_to.join(", "))}` : ""}</div>
        ${b ? `<div class="bname">${esc(b.name)}<span class="rarity ${esc(b.rarity)}">${esc(b.rarity)}</span></div>
          ${b.max_energy ? `<div class="charge">⚡ ${Number(b.energy).toFixed(1)}/${b.max_energy} (+${Number(b.charge).toFixed(1)}/s)</div>` : ""}
          <div class="tags">${(b.tags || []).map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</div>` : `<div class="dim">empty</div>`}`;
      el.appendChild(d);
    }
  };
  draw(slots.filter((x) => !x.internal), $("ext-slots"));
  draw(slots.filter((x) => x.internal), $("int-slots"));
  const muts = (s && s.player && s.player.mutations) || [];
  $("mutations").innerHTML = muts.length
    ? muts.map((m) => `<span class="mut ${m.type === "evolution" ? "evo" : ""}">${esc(m.name)}</span>`).join("")
    : `<span class="dim">none</span>`;
}

function renderCatalog() {
  const c = catalog;
  $("catalog-src").textContent = c.source ? `(${c.source}, ${c.bodyparts.length} organelles, ${c.mutations.length} mutations)` : "";
  const q = ($("cat-search").value || "").toLowerCase();
  const items = [
    ...c.bodyparts.map((b) => ({ n: b.name || b.id, d: b.description, t: b.tags || [] })),
    ...c.mutations.map((m) => ({ n: m.name || m.id, d: m.description, t: [m.kind || m.type].filter(Boolean) })),
  ].filter((x) => !q || x.n.toLowerCase().includes(q) || (x.d || "").toLowerCase().includes(q));
  $("catalog-body").innerHTML = items.slice(0, 200).map((x) => `
    <div class="cat-item"><span class="n">${esc(x.n)}</span>
    ${x.t.map((t) => `<span class="tag">${esc(t)}</span>`).join("")}
    <div class="d">${bbToHtml(x.d || "")}</div></div>`).join("");
}

$("cat-search").addEventListener("input", renderCatalog);
connect();
render();
