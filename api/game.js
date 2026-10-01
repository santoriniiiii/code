// API del juego en vivo. Estado guardado en Upstash Redis (REST).
const QUESTIONS = require("./_questions");

const DURATION = 30000; // 30 segundos por pregunta
const MAX_POINTS = 1000;
const TTL = 60 * 60 * 24; // 1 día
const P = "quiz:";

const REDIS_URL = process.env.KV_REST_API_URL || process.env.UPSTASH_REDIS_REST_URL;
const REDIS_TOKEN = process.env.KV_REST_API_TOKEN || process.env.UPSTASH_REDIS_REST_TOKEN;
const HOST_PIN = String(process.env.HOST_PIN || "").trim();

async function redis(cmds) {
  if (!REDIS_URL || !REDIS_TOKEN) {
    const e = new Error("La base de datos no está conectada todavía.");
    e.status = 503;
    throw e;
  }
  const r = await fetch(REDIS_URL.replace(/\/$/, "") + "/pipeline", {
    method: "POST",
    headers: { Authorization: "Bearer " + REDIS_TOKEN, "Content-Type": "application/json" },
    body: JSON.stringify(cmds),
  });
  if (!r.ok) throw new Error("Error de base de datos (" + r.status + ")");
  const out = await r.json();
  return out.map((x) => {
    if (x.error) throw new Error(x.error);
    return x.result;
  });
}

const rid = () => Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);
const k = (g, name) => P + g + ":" + name;

function hashToObj(arr) {
  const o = {};
  if (!arr) return o;
  for (let i = 0; i < arr.length; i += 2) o[arr[i]] = arr[i + 1];
  return o;
}

async function getState() {
  const [raw] = await redis([["GET", P + "state"]]);
  if (raw) return JSON.parse(raw);
  const s = { gameId: rid(), phase: "lobby", q: -1, startedAt: 0 };
  await redis([["SET", P + "state", JSON.stringify(s)]]);
  return s;
}

async function saveState(s) {
  await redis([["SET", P + "state", JSON.stringify(s)]]);
}

// Pasa a "reveal" si se acabó el tiempo o ya respondieron todos.
async function settle(s, now) {
  if (s.phase !== "question") return s;
  let done = now - s.startedAt >= DURATION;
  if (!done) {
    const [answered, players] = await redis([
      ["HLEN", k(s.gameId, "ans:" + s.q)],
      ["HLEN", k(s.gameId, "players")],
    ]);
    done = players > 0 && answered >= players;
  }
  if (done) {
    s = { ...s, phase: "reveal" };
    await saveState(s);
  }
  return s;
}

function publicQuestion(i) {
  const q = QUESTIONS[i];
  if (!q) return null;
  const { correct, ...pub } = q; // nunca enviar la respuesta correcta durante la pregunta
  return pub;
}
const isCorrect = (q, c) => (Array.isArray(q.correct) ? q.correct : [q.correct]).includes(c);
const correctList = (q) => (Array.isArray(q.correct) ? q.correct : [q.correct]);

async function ranking(g) {
  const [players, scores] = await redis([
    ["HGETALL", k(g, "players")],
    ["HGETALL", k(g, "scores")],
  ]);
  const pl = hashToObj(players);
  const sc = hashToObj(scores);
  return Object.keys(pl)
    .map((id) => ({ id, name: pl[id], score: Number(sc[id] || 0) }))
    .sort((a, b) => b.score - a.score || a.name.localeCompare(b.name));
}

function body(req) {
  if (req.body && typeof req.body === "object") return req.body;
  try {
    return JSON.parse(req.body || "{}");
  } catch {
    return {};
  }
}

module.exports = async (req, res) => {
  res.setHeader("Cache-Control", "no-store");
  try {
    const now = Date.now();
    if (req.method === "GET") return await handleGet(req, res, now);
    if (req.method === "POST") return await handlePost(req, res, now);
    res.status(405).json({ error: "Método no permitido" });
  } catch (e) {
    res.status(e.status || 500).json({ error: e.message || "Error" });
  }
};

async function handleGet(req, res, now) {
  const { role, pid, pin } = req.query || {};
  let s = await settle(await getState(), now);
  const base = {
    phase: s.phase,
    gameId: s.gameId,
    q: s.q,
    total: QUESTIONS.length,
    duration: DURATION,
    remaining: s.phase === "question" ? Math.max(0, DURATION - (now - s.startedAt)) : 0,
  };

  if (role === "host") {
    if (!HOST_PIN || pin !== HOST_PIN) return res.status(401).json({ error: "PIN incorrecto" });
    const out = { ...base };
    const rank = await ranking(s.gameId);
    out.players = rank.map((p) => p.name);
    out.playerCount = rank.length;
    if (s.phase === "question" || s.phase === "reveal") {
      out.question = { ...publicQuestion(s.q), correct: correctList(QUESTIONS[s.q]) };
      const [ans] = await redis([["HVALS", k(s.gameId, "ans:" + s.q)]]);
      const list = (ans || []).map((x) => JSON.parse(x));
      out.answered = list.length;
      if (s.phase === "reveal") {
        const dist = QUESTIONS[s.q].options.map(() => 0);
        list.forEach((a) => dist[a.c] !== undefined && dist[a.c]++);
        out.distribution = dist;
        out.leaderboard = rank.slice(0, 5);
      }
    }
    if (s.phase === "podium") out.leaderboard = rank.slice(0, 10);
    return res.status(200).json(out);
  }

  // Jugador
  const out = { ...base };
  let name = null;
  if (pid) {
    const [n] = await redis([["HGET", k(s.gameId, "players"), pid]]);
    name = n;
  }
  out.joined = !!name;
  out.name = name;
  if (!name) return res.status(200).json(out);

  if (s.phase === "question" || s.phase === "reveal") {
    out.question = publicQuestion(s.q);
    const [a] = await redis([["HGET", k(s.gameId, "ans:" + s.q), pid]]);
    out.myAnswer = a ? JSON.parse(a) : null;
    if (s.phase === "reveal") out.correct = correctList(QUESTIONS[s.q]);
  }
  if (s.phase === "reveal" || s.phase === "podium") {
    const rank = await ranking(s.gameId);
    const idx = rank.findIndex((p) => p.id === pid);
    out.myScore = idx >= 0 ? rank[idx].score : 0;
    out.myRank = idx + 1;
    out.playerCount = rank.length;
    if (s.phase === "podium") out.podium = rank.slice(0, 3).map(({ name, score }) => ({ name, score }));
  }
  return res.status(200).json(out);
}

async function handlePost(req, res, now) {
  const b = body(req);
  const action = b.action;

  if (action === "join") {
    const name = String(b.name || "").replace(/\s+/g, " ").trim().slice(0, 20);
    if (name.length < 2) return res.status(400).json({ error: "Escribe un nombre de al menos 2 letras" });
    const s = await getState();
    if (s.phase === "podium") return res.status(400).json({ error: "El juego ya terminó" });
    const pid = rid();
    const [ok] = await redis([["HSETNX", k(s.gameId, "names"), name.toLowerCase(), pid]]);
    if (!ok) return res.status(409).json({ error: "Ese nombre ya está en uso, prueba otro" });
    await redis([
      ["HSET", k(s.gameId, "players"), pid, name],
      ["HSET", k(s.gameId, "scores"), pid, 0],
      ["EXPIRE", k(s.gameId, "names"), TTL],
      ["EXPIRE", k(s.gameId, "players"), TTL],
      ["EXPIRE", k(s.gameId, "scores"), TTL],
    ]);
    return res.status(200).json({ pid, name, gameId: s.gameId });
  }

  if (action === "answer") {
    const pid = String(b.pid || "");
    const choice = Number(b.choice);
    const s = await settle(await getState(), now);
    if (s.phase !== "question" || Number(b.q) !== s.q)
      return res.status(400).json({ error: "Se acabó el tiempo" });
    const q = QUESTIONS[s.q];
    if (!(choice >= 0 && choice < q.options.length)) return res.status(400).json({ error: "Opción inválida" });
    const [exists] = await redis([["HEXISTS", k(s.gameId, "players"), pid]]);
    if (!exists) return res.status(400).json({ error: "Jugador no encontrado" });
    const elapsed = Math.max(0, now - s.startedAt);
    const correct = isCorrect(q, choice);
    const points = correct ? Math.round(MAX_POINTS * (1 - (elapsed / DURATION) / 2)) : 0;
    const key = k(s.gameId, "ans:" + s.q);
    const [set] = await redis([
      ["HSETNX", key, pid, JSON.stringify({ c: choice, t: elapsed, p: points })],
      ["EXPIRE", key, TTL],
    ]);
    if (set && points > 0) await redis([["HINCRBY", k(s.gameId, "scores"), pid, points]]);
    return res.status(200).json({ ok: true });
  }

  if (["start", "next", "reveal", "reset"].includes(action)) {
    if (!HOST_PIN || String(b.pin || "") !== HOST_PIN) return res.status(401).json({ error: "PIN incorrecto" });
    let s = await settle(await getState(), now);
    const fromQ = Number(b.fromQ);
    if (action === "reset") {
      s = { gameId: rid(), phase: "lobby", q: -1, startedAt: 0 };
    } else if (action === "start" && s.phase === "lobby") {
      s = { ...s, phase: "question", q: 0, startedAt: now };
    } else if (action === "reveal" && s.phase === "question" && s.q === fromQ) {
      s = { ...s, phase: "reveal" };
    } else if (action === "next" && s.phase === "reveal" && s.q === fromQ) {
      s = s.q + 1 < QUESTIONS.length
        ? { ...s, phase: "question", q: s.q + 1, startedAt: now }
        : { ...s, phase: "podium" };
    } else {
      return res.status(200).json({ ok: true, ignored: true });
    }
    await saveState(s);
    return res.status(200).json({ ok: true });
  }

  res.status(400).json({ error: "Acción desconocida" });
}
