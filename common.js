// Utilidades compartidas
const SHAPES = [
  '<svg class="shape" viewBox="0 0 24 24"><path d="M12 3 22 21H2z" fill="#fff"/></svg>',
  '<svg class="shape" viewBox="0 0 24 24"><path d="M12 2 22 12 12 22 2 12z" fill="#fff"/></svg>',
  '<svg class="shape" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" fill="#fff"/></svg>',
  '<svg class="shape" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2" fill="#fff"/></svg>',
];

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function api(method, params) {
  let url = "/api/game";
  const opt = { method, headers: { "Content-Type": "application/json" } };
  if (method === "GET") url += "?" + new URLSearchParams(params || {}).toString() + "&_=" + Date.now();
  else opt.body = JSON.stringify(params || {});
  const r = await fetch(url, opt);
  let data = {};
  try { data = await r.json(); } catch {}
  if (!r.ok) { const e = new Error(data.error || "Error de conexión"); e.status = r.status; throw e; }
  return data;
}

function store(key, val) {
  try { if (val === undefined) return localStorage.getItem(key); if (val === null) localStorage.removeItem(key); else localStorage.setItem(key, val); } catch {}
  return null;
}

const fmt = (n) => Number(n || 0).toLocaleString("es-PE");

// Enunciado completo: escenario, imagen, tabla y pregunta
function questionHTML(q) {
  let h = "";
  if (q.context) h += `<div class="ctx"><span class="ctx-tag">Escenario</span>${esc(q.context)}</div>`;
  if (q.table) h += `<div class="qtable"><div class="qt-title">${esc(q.table.title)}</div>${q.table.rows
    .map((r) => `<div class="qt-row"><span>${esc(r[0])}</span><b>${esc(r[1])}</b></div>`).join("")}</div>`;
  if (q.image) h += `<img class="qimg" src="${esc(q.image)}" alt="">`;
  if (q.svg) h += `<div class="qimg">${q.svg}</div>`; // diagrama definido en el propio banco de preguntas
  if (q.caption) h += `<div class="qcap">${esc(q.caption)}</div>`;
  h += `<div class="qmain">${esc(q.text)}</div>`;
  return `<div class="qtext fade${q.context || q.table || q.image || q.svg ? " rich" : ""}">${h}</div>`;
}
const LETTERS = ["A", "B", "C", "D"];
function optionClass(o) { return o.length > 110 ? " xlong" : o.length > 60 ? " long" : ""; }

function timerSVG(durationMs = 30000) {
  const C = 2 * Math.PI * 27;
  return `<div class="timer" id="timer"><svg width="64" height="64" viewBox="0 0 64 64"><circle class="track" cx="32" cy="32" r="27"/>
    <circle class="bar" id="timerBar" cx="32" cy="32" r="27" stroke-dasharray="${C}" stroke-dashoffset="0"/></svg>
    <div class="num" id="timerNum">${Math.round(durationMs / 1000)}</div></div>`;
}
function updateTimer(remainingMs, durationMs) {
  const bar = document.getElementById("timerBar"), num = document.getElementById("timerNum"), t = document.getElementById("timer");
  if (!bar) return;
  const C = 2 * Math.PI * 27;
  const frac = Math.max(0, Math.min(1, remainingMs / durationMs));
  bar.style.strokeDashoffset = String(C * (1 - frac));
  num.textContent = Math.ceil(remainingMs / 1000);
  t.classList.toggle("low", remainingMs <= 5000);
}

function confetti(duration = 5000) {
  let c = document.getElementById("confetti");
  if (!c) { c = document.createElement("canvas"); c.id = "confetti"; document.body.appendChild(c); }
  const ctx = c.getContext("2d");
  const resize = () => { c.width = innerWidth; c.height = innerHeight; };
  resize(); addEventListener("resize", resize);
  const colors = ["#e5374f", "#2f6fe4", "#f2a618", "#22a05b", "#ffcc3d", "#ff5e8a", "#ffffff"];
  const parts = Array.from({ length: 180 }, () => ({
    x: Math.random() * c.width, y: -20 - Math.random() * c.height, w: 6 + Math.random() * 6, h: 10 + Math.random() * 8,
    vy: 2 + Math.random() * 3, vx: -1.5 + Math.random() * 3, r: Math.random() * 6, vr: -.15 + Math.random() * .3,
    color: colors[(Math.random() * colors.length) | 0],
  }));
  const end = Date.now() + duration;
  (function frame() {
    ctx.clearRect(0, 0, c.width, c.height);
    const alive = Date.now() < end;
    parts.forEach((p) => {
      p.x += p.vx; p.y += p.vy; p.r += p.vr;
      if (p.y > c.height + 20 && alive) { p.y = -20; p.x = Math.random() * c.width; }
      ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.r); ctx.fillStyle = p.color;
      ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h); ctx.restore();
    });
    if (alive || parts.some((p) => p.y < c.height + 20)) requestAnimationFrame(frame);
    else ctx.clearRect(0, 0, c.width, c.height);
  })();
}
