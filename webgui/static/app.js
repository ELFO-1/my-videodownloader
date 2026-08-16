"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (r.status === 401) throw new Error("Nicht angemeldet – bitte Seite neu laden.");
  let data = {};
  try { data = await r.json(); } catch (e) {}
  if (!r.ok) throw new Error(data.error || data.message || ("HTTP " + r.status));
  return data;
}
const postJSON = (path, body) =>
  api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });

// ---- Tabs ----
$$(".tab").forEach(t => t.addEventListener("click", () => {
  $$(".tab").forEach(x => {
    const on = x === t;
    x.classList.toggle("active", on);
    x.setAttribute("aria-selected", on ? "true" : "false");
    x.tabIndex = on ? 0 : -1;
  });
  $$(".panel").forEach(p => {
    const on = p.id === "tab-" + t.dataset.tab;
    p.classList.toggle("active", on);
    p.hidden = !on;
  });
  if (t.dataset.tab === "waipu") refreshWaipuStatus();
}));

// ---- Config (Ordner/Qualitäten) ----
async function loadConfig() {
  let c;
  try {
    c = await api("/api/config");
  } catch (e) {
    setMsg("#dl-msg", "Server nicht erreichbar: " + e.message, true);
    $("#btn-download").disabled = true;
    return;
  }
  const qOpts = c.qualities.map(q => `<option value="${esc(q)}">${q === "best" ? "Beste" : q + "p"}</option>`).join("");
  const dOpts = c.dest_folders.map(d => `<option value="${esc(d)}">${esc(d)}</option>`).join("");
  $("#quality").innerHTML = qOpts;
  $("#dest").innerHTML = dOpts;
  $("#waipu-quality").innerHTML = qOpts;
  $("#waipu-dest").innerHTML = dOpts;
  // sinnvolle Defaults
  if (c.dest_folders.includes("downloads")) $("#dest").value = "downloads";
  if (c.dest_folders.includes("Aufnahmen")) $("#waipu-dest").value = "Aufnahmen";
  if (!c.waipu_available) $('.tab[data-tab="waipu"]').style.display = "none";
  setYtdlpVersion(c.ytdlp_version);
  // Bei einem Distributions-Paket gibt es keinen sicheren Update-Weg aus der GUI.
  if (!c.ytdlp_updatable) {
    $("#btn-ytdlp-update").hidden = true;
    setMsg("#ytdlp-msg", "(Update über die Paketverwaltung)");
  }
}

function setYtdlpVersion(v) {
  $("#ytdlp-version").textContent = v || "nicht gefunden";
  $("#ytdlp-version").classList.toggle("bad", !v);
}

// ---- yt-dlp aktualisieren ----
$("#btn-ytdlp-update").addEventListener("click", async () => {
  const btn = $("#btn-ytdlp-update");
  btn.disabled = true;
  setMsg("#ytdlp-msg", "Aktualisiere ...");
  try {
    const r = await postJSON("/api/ytdlp/update", {});
    setYtdlpVersion(r.version);
    setMsg("#ytdlp-msg", r.message);
  } catch (e) {
    setMsg("#ytdlp-msg", e.message, true);
  } finally { btn.disabled = false; }
});

// ---- Download starten ----
// Bei Playlists ist das Archiv fast immer erwünscht -> vorschlagen.
$("#playlist").addEventListener("change", e => {
  if (e.target.checked) $("#archive").checked = true;
});

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
      archive: $("#archive").checked,
    });
    setMsg("#dl-msg", `${r.ids.length} Download(s) gestartet.`);
    $("#url").value = "";
    scheduleJobs(0);
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
      <input type="checkbox" value="${esc(r.id)}">
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
    scheduleJobs(0);
  } catch (e) {
    setMsg("#waipu-msg", "Fehler: " + e.message, true);
  }
});

// ---- Jobs ----
const STATUS_LABEL = {
  queued: "wartet", running: "läuft", done: "fertig",
  error: "Fehler", skipped: "übersprungen", canceled: "abgebrochen",
};
const jobEls = new Map();   // id -> {root, title, badge, bar, dest, info, cancel}

$("#btn-clear").addEventListener("click", async () => {
  await postJSON("/api/jobs/clear", {});
  scheduleJobs(0);
});

// Ein Listener statt einer pro Zeile (die Liste wird laufend aktualisiert).
$("#jobs").addEventListener("click", async e => {
  const btn = e.target.closest("[data-cancel]");
  if (!btn) return;
  btn.disabled = true;
  await postJSON("/api/jobs/cancel", { id: btn.dataset.cancel });
  scheduleJobs(0);
});

function createJobEl(id) {
  const root = document.createElement("div");
  root.className = "job";
  root.innerHTML = `<div class="head">
      <span class="title"></span><span class="badge"></span>
      <button class="x" data-cancel="${esc(id)}" title="Abbrechen" aria-label="Abbrechen">✕</button>
    </div>
    <div class="bar"><i></i></div>
    <div class="sub"><span class="dest"></span><span class="info"></span></div>`;
  return {
    root,
    title: $(".title", root), badge: $(".badge", root), bar: $(".bar > i", root),
    dest: $(".dest", root), info: $(".info", root), cancel: $(".x", root),
  };
}

function jobInfo(j) {
  if (j.status !== "running") return j.message || j.relpath || j.filename || "";
  const parts = [];
  if (j.total > 1) parts.push(`Video ${j.item || 1}/${j.total}`);
  parts.push(`${j.percent}%`);
  if (j.size) parts.push(j.size);
  if (j.speed) parts.push(j.speed);
  if (j.eta) parts.push("ETA " + j.eta);
  return parts.join(" · ");
}

// Nur schreiben, was sich geaendert hat - sonst bricht bei jedem Poll
// die Textmarkierung des Nutzers ab.
function setText(el, text) {
  if (el.textContent !== text) el.textContent = text;
}

function renderJobs(jobs) {
  const box = $("#jobs");
  const empty = $(".empty", box);
  if (!jobs.length) {
    jobEls.forEach(e => e.root.remove());
    jobEls.clear();
    if (!empty) box.innerHTML = `<div class="empty">Noch keine Downloads.</div>`;
    return;
  }
  if (empty) empty.remove();

  jobs.sort((a, b) => b.created - a.created);
  const seen = new Set(jobs.map(j => j.id));
  jobEls.forEach((el, id) => {
    if (!seen.has(id)) { el.root.remove(); jobEls.delete(id); }
  });

  jobs.forEach((j, i) => {
    let el = jobEls.get(j.id);
    if (!el) { el = createJobEl(j.id); jobEls.set(j.id, el); }
    setText(el.title, j.filename || j.title);
    el.root.title = j.relpath || j.title;
    setText(el.badge, STATUS_LABEL[j.status] || j.status);
    if (el.badge.dataset.status !== j.status) {
      el.badge.className = "badge " + j.status;
      el.badge.dataset.status = j.status;
    }
    const width = j.percent + "%";
    if (el.bar.style.width !== width) el.bar.style.width = width;
    setText(el.dest, j.dest);
    const info = jobInfo(j);
    setText(el.info, info);
    el.info.title = info;   // Volltext langer Fehlermeldungen
    const cancellable = j.status === "running" || j.status === "queued";
    el.cancel.hidden = !cancellable;
    if (cancellable) el.cancel.disabled = false;
    // Reihenfolge nur anfassen, wenn sie tatsaechlich abweicht
    if (box.children[i] !== el.root) box.insertBefore(el.root, box.children[i] || null);
  });
}

/** Liefert true, solange noch etwas laeuft (steuert das Poll-Intervall). */
async function refreshJobs() {
  let jobs;
  try {
    jobs = (await api("/api/jobs")).jobs || [];
  } catch (e) {
    return null;
  }
  renderJobs(jobs);
  return jobs.some(j => j.status === "running" || j.status === "queued");
}

// ---- Polling mit Backoff: schnell solange etwas laeuft, sonst sparsam ----
let jobsTimer = null;
function scheduleJobs(delay) {
  clearTimeout(jobsTimer);
  jobsTimer = setTimeout(pollJobs, delay);
}
async function pollJobs() {
  if (document.hidden) { scheduleJobs(10000); return; }
  const active = await refreshJobs();
  scheduleJobs(active === null ? 5000 : active ? 1000 : 8000);
}
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) scheduleJobs(0);
});

// ---- Helfer ----
function setMsg(sel, text, isErr) {
  const el = $(sel); el.textContent = text;
  el.style.color = isErr ? "var(--err)" : "var(--muted)";
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---- Init ----
loadConfig();
scheduleJobs(0);
