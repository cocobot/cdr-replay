// Shared helpers for the cdr-replay static site.
const qs = (k) => new URLSearchParams(location.search).get(k);
const fetchJSON = (p) => fetch(p).then((r) => { if (!r.ok) throw new Error(p); return r.json(); });

function fmt(s) {
  s = Math.max(0, Math.round(s));
  const m = Math.floor(s / 60), sec = s % 60;
  return `${m}:${String(sec).padStart(2, "0")}`;
}
function seriesLabel(s) { return /^\d+$/.test(s) ? `Série ${s}` : s.charAt(0).toUpperCase() + s.slice(1); }
function slugOf(cat, year, series) { return `${cat}_${year}_${String(series).replace(/[^A-Za-z0-9]/g, "")}`; }

function header(active) {
  const links = [["index.html", "Accueil"]];
  return `<header class="top"><div class="wrap" style="display:flex;align-items:center;gap:14px;width:100%">
    <a class="logo" href="index.html"><span class="dot"></span>CDR&nbsp;<b>Replay</b></a>
    <nav>${links.map(([h, t]) => `<a href="${h}">${t}</a>`).join("")}</nav>
  </div></header>`;
}

// YouTube IFrame API: returns a promise resolving to a player controller.
function loadYouTube(containerId, videoId, startSeconds) {
  return new Promise((resolve) => {
    function create() {
      const p = new YT.Player(containerId, {
        videoId,
        playerVars: { autoplay: 0, rel: 0, modestbranding: 1, start: Math.floor(startSeconds || 0) },
        events: { onReady: () => resolve(p) },
      });
    }
    if (window.YT && window.YT.Player) return create();
    window.onYouTubeIframeAPIReady = create;
    if (!document.getElementById("yt-api")) {
      const s = document.createElement("script");
      s.id = "yt-api"; s.src = "https://www.youtube.com/iframe_api";
      document.head.appendChild(s);
    }
  });
}
