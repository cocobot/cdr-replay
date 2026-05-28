// Shared helpers — CDR Replay (zine v2, multi-page static).
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
function isUs(name) { return teamKey(name) === "cocotter"; }

// Normalise a team name for cross-source matching (sheet ↔ video OCR).
// "Coc'otter" / "coc'otter" / "COC OTTER" → "cocotter".
function teamKey(s) {
  return (s || "").toLowerCase().normalize("NFD")
    .replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]/g, "");
}

// ---------- Category state (persisted) ----------
const CAT = (() => {
  let c = (qs("c") || "").toLowerCase();
  if (c !== "senior" && c !== "junior") c = localStorage.getItem("cdr-cat") || "senior";
  return c === "junior" ? "junior" : "senior";
})();
function setCat(c) {
  localStorage.setItem("cdr-cat", c);
  // jump to home in the new cat
  location.href = "index.html";
}

// ---------- Legends marker (yellow star) ----------
function legendMark() {
  return `<span class="legend-mark" title="Legends — équipe légende">
    <svg viewBox="0 0 24 24" fill="currentColor" stroke="#1a1a14" stroke-width="1" stroke-linejoin="round" width="14" height="14"><path d="M12 2.6l2.84 5.76 6.36.92-4.6 4.49 1.09 6.35L12 17.1l-5.69 2.99 1.09-6.35-4.6-4.49 6.36-.92z"/></svg>
  </span>`;
}

// ---------- Header (brand + cat-switch + search). No logo, no footer. ----------
function header() {
  return `<header class="site-header"><div class="site-header__inner">
    <a class="brand" href="index.html"><span>Replays CDR <small>par Cocotter</small></span></a>
    <div class="cat-switch">
      <button class="cat-switch__btn${CAT === "senior" ? " is-active" : ""}" data-cat="senior">Senior</button>
      <button class="cat-switch__btn${CAT === "junior" ? " is-active" : ""}" data-cat="junior">Junior</button>
    </div>
    <label class="search">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color:var(--muted)"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
      <input id="hsearch" type="text" placeholder="Équipe…" autocomplete="off">
    </label>
  </div></header>`;
}
function mountHeader() {
  document.getElementById("hdr").innerHTML = header();
  document.querySelectorAll(".cat-switch__btn").forEach((b) => b.onclick = () => setCat(b.dataset.cat));
  const inp = document.getElementById("hsearch");
  inp.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && inp.value.trim()) location.href = "index.html?q=" + encodeURIComponent(inp.value.trim());
  });
}

// ---------- Team row in lists ----------
function teamLinkHTML(t) {
  // t : {name, city, cat, us, legend?, rank?}
  return `<a class="team-link${t.us ? " is-us" : ""}" href="team.html?team=${encodeURIComponent(t.name)}">
    <span class="team-link__name">${esc(t.name)}${t.legend ? legendMark() : ""}</span>
    ${t.rank ? `<span class="team-link__city">#${t.rank}</span>` : `<span class="team-link__city">${esc(t.city || "")}</span>`}
  </a>`;
}

// Clickable team name (inline, in MatchRow and match-head).
function teamLinkText(name, extra = "") {
  return `<a class="team-link-text${extra}" href="team.html?team=${encodeURIComponent(name || "")}">${esc(name || "?")}</a>`;
}

// Side ("yellow"|"blue") -> "winner" | "loser" | "" (unknown) given a match.
// Falls back to nothing when scores aren't joined yet.
function sideClass(m, side) {
  if (m.winner === side) return "winner";
  if (m.winner && m.winner !== side) return "loser";
  if (m.score_yellow != null && m.score_blue != null) {
    const a = m.score_yellow, b = m.score_blue;
    if (a === b) return "";
    const win = a > b ? "yellow" : "blue";
    return side === win ? "winner" : "loser";
  }
  return "";
}

// Score cell HTML: "98–35" with winner side bolded, or "Table X" when no scores.
function scoreCell(m) {
  const sy = m.score_yellow, sb = m.score_blue;
  if (sy == null || sb == null) {
    return m.table ? `Table ${esc(m.table)}` : "";
  }
  const wy = sideClass(m, "yellow") === "winner";
  const wb = sideClass(m, "blue") === "winner";
  const fy = wy ? `<span class="w">${sy}</span>` : `${sy}`;
  const fb = wb ? `<span class="w">${sb}</span>` : `${sb}`;
  return `${fy}<span class="match-row__score__sep">–</span>${fb}`;
}

// ---------- Standings (per cat/year, from the Google Sheet extraction) ----------
const _standingsCache = {};
async function loadStandings(cat, year) {
  const key = `${cat}_${year}`;
  if (_standingsCache[key] !== undefined) return _standingsCache[key];
  try {
    const d = await fetchJSON(`data/standings/${key}.json`);
    const map = {};
    for (const t of d.teams) map[teamKey(t.name)] = t;
    _standingsCache[key] = map;
    return map;
  } catch {
    return (_standingsCache[key] = null);
  }
}
