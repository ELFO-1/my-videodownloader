"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

async function api(path, opts) {
  const r = await fetch(path, opts);
  let data = {};
  try { data = await r.json(); } catch (e) {}
  if (!r.ok) throw new Error(data.error || ("HTTP " + r.status));
  return data;
}
const postJSON = (path, body) =>
  api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });

// ---- Tabs ----
$$(".tab").forEach(t => t.addEventListener("click", () => {
  $$(".tab").forEach(x => x.classList.remove("active"));
  $$(".panel").forEach(x => x.classList.remove("active"));
  t.classList.add("active");
  $("#tab-" + t.dataset.tab).classList.add("active");
  if (t.dataset.tab === "waipu") refreshWaipuStatus();
}));

// ---- Config (Ordner/Qualitäten) ----
async function loadConfig() {
  const c = await api("/api/config");
  const qOpts = c.qualities.map(q => `<option value="${q}">${q === "best" ? "Beste" : q + "p"}</option>`).join("");
  const dOpts = c.dest_folders.map(d => `<option value="${d}">${d}</option>`).join("");
  $("#quality").innerHTML = qOpts;
  $("#dest").innerHTML = dOpts;
  $("#waipu-quality").innerHTML = qOpts;
  $("#waipu-dest").innerHTML = dOpts;
  // sinnvolle Defaults
  if (c.dest_folders.includes("downloads")) $("#dest").value = "downloads";
  if (c.dest_folders.includes("Aufnahmen")) $("#waipu-dest").value = "Aufnahmen";
  if (!c.waipu_available) $('.tab[data-tab="waipu"]').style.display = "none";
}

// ---- Download starten ----
$("#btn-download").addEventListener("click", async () => {
  const url = $("#url").value.trim();
  if (!url) { setMsg("#dl-msg", "Bitte eine URL eingeben.", true); return; }
  const btn = $("#btn-download"); btn.disabled = true;
  try {
    const r = await postJSON("/api/download", {
      url,
      quality: $("#quality").value,
      dest: $("#dest").value,
      audio_only: $("#audio_only").checked,
      playlist: $("#playlist").checked,
      subtitles: $("#subtitles").checked,
    });
    setMsg("#dl-msg", `${r.ids.length} Download(s) gestartet.`);
    $("#url").value = "";
    refreshJobs();
  } catch (e) {
    setMsg("#dl-msg", "Fehler: " + e.message, true);
  } finally { btn.disabled = false; }
});

// ---- waipu ----
let waipuPoll = null;

async function refreshWaipuStatus() {
  try {
    const s = await api("/api/waipu/status");
    $("#waipu-loggedin").classList.toggle("hidden", !s.logged_in);
    $("#waipu-loggedout").classList.toggle("hidden", s.logged_in);
  } catch (e) {}
}

$("#btn-waipu-login").addEventListener("click", async () => {
  try {
    const info = await postJSON("/api/waipu/login/start", {});
    $("#wl-url").textContent = info.verification_uri;
    $("#wl-url").href = info.verification_uri_complete || info.verification_uri;
    $("#wl-code").textContent = info.user_code;
    $("#waipu-login-box").classList.remove("hidden");
    setMsg("#wl-status", "Warte auf Bestätigung im Browser ...");
    if (waipuPoll) clearInterval(waipuPoll);
    waipuPoll = setInterval(async () => {
      try {
        const p = await api("/api/waipu/login/poll");
        if (p.state === "ok") {
          clearInterval(waipuPoll); waipuPoll = null;
          setMsg("#wl-status", "Login erfolgreich! ✅");
          refreshWaipuStatus();
        } else if (p.state === "error") {
          clearInterval(waipuPoll); waipuPoll = null;
          setMsg("#wl-status", p.message, true);
        }
      } catch (e) {}
    }, 3000);
  } catch (e) {
    setMsg("#wl-status", "Fehler: " + e.message, true);
  }
});

$("#btn-waipu-logout").addEventListener("click", async () => {
  await postJSON("/api/waipu/logout", {});
  refreshWaipuStatus();
});

let waipuRecs = [];
$("#btn-waipu-load").addEventListener("click", async () => {
  setMsg("#waipu-msg", "Lade Aufnahmen ...");
  try {
    const r = await api("/api/waipu/recordings");
    waipuRecs = r.recordings || [];
    renderRecs();
    setMsg("#waipu-msg", `${waipuRecs.length} Aufnahme(n) gefunden.`);
  } catch (e) {
    if (/angemeldet/i.test(e.message)) refreshWaipuStatus();
    setMsg("#waipu-msg", "Fehler: " + e.message, true);
  }
});

$("#waipu-filter").addEventListener("input", renderRecs);

function renderRecs() {
  const term = $("#waipu-filter").value.trim().toLowerCase();
  const list = $("#waipu-list");
  const recs = waipuRecs.filter(r => !term || r.label.toLowerCase().includes(term));
  if (!recs.length) {
    list.innerHTML = `<div class="empty" style="padding:.6rem .7rem">Keine Aufnahmen.</div>`;
    $("#btn-waipu-dl").classList.add("hidden");
    return;
  }
  list.innerHTML = recs.map(r => {
    const sub = [r.channel, r.start, r.duration].filter(Boolean).join(" · ");
    return `<label class="rec">
      <input type="checkbox" value="${r.id}">
      <span class="meta"><span class="t">${esc(r.label)}</span><span class="s">${esc(sub)}</span></span>
    </label>`;
  }).join("");
  $("#btn-waipu-dl").classList.remove("hidden");
}

$("#btn-waipu-dl").addEventListener("click", async () => {
  const ids = $$("#waipu-list input:checked").map(c => c.value);
  if (!ids.length) { setMsg("#waipu-msg", "Nichts ausgewählt.", true); return; }
  try {
    const r = await postJSON("/api/waipu/download", {
      ids, quality: $("#waipu-quality").value, dest: $("#waipu-dest").value,
    });
    setMsg("#waipu-msg", `${r.ids.length} Aufnahme(n) in Warteschlange.`);
    refreshJobs();
  } catch (e) {
    setMsg("#waipu-msg", "Fehler: " + e.message, true);
  }
});

// ---- Jobs ----
$("#btn-clear").addEventListener("click", async () => {
  await postJSON("/api/jobs/clear", {});
  refreshJobs();
});

async function refreshJobs() {
  let jobs = [];
  try { jobs = (await api("/api/jobs")).jobs || []; } catch (e) { return; }
  const box = $("#jobs");
  if (!jobs.length) { box.innerHTML = `<div class="empty">Noch keine Downloads.</div>`; return; }
  jobs.sort((a, b) => b.created - a.created);
  box.innerHTML = jobs.map(j => {
    const labels = { queued: "wartet", running: "läuft", done: "fertig", error: "Fehler", skipped: "übersprungen", canceled: "abgebrochen" };
    const sub = j.status === "running"
      ? `${j.percent}% ${j.speed ? "· " + j.speed : ""} ${j.eta ? "· ETA " + j.eta : ""}`
      : (j.message || j.filename || "");
    const cancelBtn = (j.status === "running" || j.status === "queued")
      ? `<button class="x" data-cancel="${j.id}" title="Abbrechen">✕</button>` : "";
    return `<div class="job">
      <div class="head">
        <span class="title" title="${esc(j.title)}">${esc(j.filename || j.title)}</span>
        <span class="badge ${j.status}">${labels[j.status] || j.status}</span>
        ${cancelBtn}
      </div>
      <div class="bar"><i style="width:${j.percent}%"></i></div>
      <div class="sub"><span>${esc(j.dest)}</span><span>${esc(sub)}</span></div>
    </div>`;
  }).join("");
  $$("[data-cancel]").forEach(b => b.addEventListener("click", async () => {
    await postJSON("/api/jobs/cancel", { id: b.dataset.cancel });
    refreshJobs();
  }));
}

// ---- Helfer ----
function setMsg(sel, text, isErr) {
  const el = $(sel); el.textContent = text;
  el.style.color = isErr ? "var(--err)" : "var(--muted)";
}
function esc(s) {
  return (s || "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---- Init ----
loadConfig();
refreshJobs();
setInterval(refreshJobs, 1500);
