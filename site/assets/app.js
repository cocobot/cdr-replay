// Shared helpers — CDR Replay (zine style, multi-page static site).
const qs = (k) => new URLSearchParams(location.search).get(k);
const fetchJSON = (p) => fetch(p).then((r) => { if (!r.ok) throw new Error(p); return r.json(); });
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function fmt(sec) {
  sec = Math.max(0, Math.round(sec || 0));
  return Math.floor(sec / 60) + ":" + String(sec % 60).padStart(2, "0");
}
function seriesLabel(s) { return /^\d+$/.test(s) ? `Série ${s}` : (s.charAt(0).toUpperCase() + s.slice(1)); }
function catLabel(c) { return c === "junior" ? "Junior" : "Senior"; }
function slugOf(c, y, s) { return `${c}_${y}_${String(s).replace(/[^A-Za-z0-9]/g, "")}`; }
function isFinale(s) { return !/^\d+$/.test(s); }
function isUs(name) { return (name || "").toLowerCase().replace(/[^a-z]/g, "") === "cocotter"; }

// Header — text brand (no logo) + search. No footer anywhere (per design).
function header() {
  return `<header class="site-header"><div class="site-header__inner">
    <a class="brand" href="index.html"><span>Replays CDR <small>par Cocotter</small></span></a>
    <label class="search">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color:var(--muted)"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
      <input id="hsearch" type="text" placeholder="Équipe…" autocomplete="off">
    </label>
  </div></header>`;
}
function mountHeader() {
  document.getElementById("hdr").innerHTML = header();
  const inp = document.getElementById("hsearch");
  inp.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && inp.value.trim()) location.href = "index.html?q=" + encodeURIComponent(inp.value.trim());
  });
}

// A team link row (home / search / team lists).
function teamLinkHTML(t) {
  const cat = t.cat || t.category || "senior";
  return `<a class="team-link${t.us ? " is-us" : ""}" href="team.html?team=${encodeURIComponent(t.name)}">
    <span style="display:flex;align-items:center;min-width:0">
      <span class="team-link__name">${esc(t.name)}</span>
      <span class="team-link__cat team-link__cat--${cat}">${cat === "junior" ? "JR" : "SR"}</span>
    </span>
    <span class="team-link__city">${esc(t.city || "")}</span>
  </a>`;
}

// A team name inside a match row / head (highlight our team).
function teamSpan(name) {
  return isUs(name) ? `<span class="is-us">${esc(name)}</span>` : `<span class="winner">${esc(name || "?")}</span>`;
}
