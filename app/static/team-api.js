/* Shared participant-3 transport. No business endpoints or client-side points. */
(() => {
  "use strict";
  const memory = new Map();
  let mutations = 0;
  const statuses = { submitted: "Ожидает решения", selected: "Команда выбрана", rejected: "Не выбран" };
  const topics = { logistics: "Логистика", retail: "Торговля", education: "Образование",
    agriculture: "Сельское хозяйство", services: "Услуги", other: "Другое" };
  function read(key) {
    if (memory.has(key)) return memory.get(key);
    try { return localStorage.getItem(key); } catch { return null; }
  }
  function write(key, value) {
    memory.set(key, value);
    try { localStorage.setItem(key, value); return true; } catch { return false; }
  }
  function safeUrl(value) {
    try {
      const url = new URL(value);
      return ["http:", "https:"].includes(url.protocol) && url.hostname && !url.username && !url.password ? url.href : null;
    } catch { return null; }
  }
  async function request(path, { teamId, body, signal } = {}) {
    const abort = new AbortController();
    const cancel = () => abort.abort();
    if (signal?.aborted) cancel();
    signal?.addEventListener("abort", cancel, { once: true });
    const timer = setTimeout(cancel, 15000);
    try {
      const headers = { Accept: "application/json" };
      if (teamId) headers["X-Demo-Team-Id"] = teamId;
      if (body !== undefined) headers["Content-Type"] = "application/json";
      const response = await fetch(path, { method: body === undefined ? "GET" : "POST",
        headers, body: body === undefined ? undefined : JSON.stringify(body), signal: abort.signal, cache: "no-store" });
      let data;
      try { data = await response.json(); } catch { /* A proxy may return HTML instead of JSON. */ }
      if (!response.ok) {
        const error = new Error(data?.error?.message || "Сервис пока недоступен. Повторите запрос.");
        error.status = response.status;
        error.code = data?.error?.code;
        error.details = data?.error?.details || [];
        throw error;
      }
      if (data === undefined) throw new Error("Сервер вернул неполный ответ. Обновите данные.");
      return data;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("Ответ не получен вовремя. Проверьте соединение и повторите запрос.");
      if (error.name === "TypeError" && !error.status) throw new Error("Нет связи с сервером. Проверьте соединение и повторите запрос.");
      throw error;
    } finally { clearTimeout(timer); signal?.removeEventListener("abort", cancel); }
  }
  async function mutate(path, teamId, body) {
    ++mutations;
    window.SanaRole.setBusy("team", true);
    try { return await request(path, { teamId, body }); }
    finally { window.SanaRole.setBusy("team", --mutations > 0); }
  }
  const isTeam = () => document.documentElement.dataset.demoRole === "team";
  function chooseTeam() {
    const role = document.querySelector("#demo-profile");
    if (role.disabled || window.SanaRole.isBusy()) return;
    role.value = "team";
    role.dispatchEvent(new Event("change", { bubbles: true }));
  }
  function text(tag, value, className = "") {
    const el = document.createElement(tag); el.textContent = value; el.className = className; return el;
  }
  function date(value) {
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? "" : parsed.toLocaleDateString("ru", { day: "numeric", month: "short", year: "numeric" });
  }
  function proposals(data) {
    if (!Array.isArray(data) || !data.every(p => typeof p.id === "string" && typeof p.task_id === "string"
      && typeof p.team_id === "string" && typeof p.task_title === "string" && Object.hasOwn(statuses, p.status)
      && ["idea", "plan", "timeline", "questions"].every(k => typeof p[k] === "string")
      && Array.isArray(p.milestones) && p.milestones.every(m => typeof m.id === "string"
        && typeof m.description === "string" && ["submitted", "confirmed"].includes(m.status)
        && Number.isInteger(m.points_awarded) && m.points_awarded >= 0))) {
      throw new Error("Не удалось прочитать отклики. Обновите данные.");
    }
    return data;
  }
  function teams(data) {
    if (!Array.isArray(data?.teams) || !data.teams.every(t => typeof t.id === "string" && t.id
      && typeof t.name === "string" && Number.isInteger(t.points) && t.points >= 0)) {
      throw new Error("Не удалось прочитать профили команд.");
    }
    return data.teams;
  }
  window.SanaTeam = Object.freeze({ request, mutate, read, write, safeUrl, text, date, statuses, topics,
    proposals, teams, isTeam, chooseTeam, preference: "ai-sana:proposal-team" });
})();
