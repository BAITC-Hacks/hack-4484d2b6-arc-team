/* Participant 3, step 1. Explicit preview fixtures; never reads private draft APIs.
   Scores/levels are display examples, not client-calculated business ratings. */
(() => {
  "use strict";
  const levels = { draft: "Требует уточнения", working: "Рабочая", ready: "Готовая", priority: "Приоритетная" };
  const form = document.querySelector("#catalog-filters");
  if (!form) return;
  const query = document.querySelector("#catalog-query");
  const topic = document.querySelector("#catalog-topic");
  const readiness = document.querySelector("#catalog-readiness");
  const grid = document.querySelector("#catalog-grid");
  const count = document.querySelector("#catalog-count");
  const empty = document.querySelector("#catalog-empty");
  const error = document.querySelector("#catalog-error");
  let tasks = [];
  const stateKey = "ai-sana:catalog-filters";
  let saved = {};
  try { saved = JSON.parse(sessionStorage.getItem(stateKey)) || {}; } catch { /* Optional tab state. */ }
  if (!saved || typeof saved !== "object") saved = {};
  query.value = typeof saved.query === "string" ? saved.query.slice(0, 200) : "";
  readiness.value = Object.hasOwn(levels, saved.readiness) ? saved.readiness : "";
  let returnScroll = Number.isFinite(saved.scroll) ? Math.max(0, saved.scroll) : 0;

  function saveState() {
    try { sessionStorage.setItem(stateKey, JSON.stringify({ query: query.value, topic: topic.value,
      readiness: readiness.value, scroll: returnScroll })); } catch { /* Works without storage. */ }
  }

  function restorePosition() {
    if (window.location.hash === "#catalog") requestAnimationFrame(() => {
      if (window.location.hash === "#catalog") window.scrollTo(0, returnScroll);
    });
  }

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function card(task) {
    const data = task.published_card;
    const rating = task.published_rating;
    const article = element("article", "catalog-card");
    article.dataset.level = rating?.level || "unknown";
    const top = element("div", "catalog-card-top");
    top.append(element("span", "catalog-card-topic", task.topic), element("span", "catalog-card-number", "↗"));
    const body = element("div", "catalog-card-body");
    body.append(element("h2", "", data.title), element("p", "catalog-card-description", data.need));
    const result = element("div", "catalog-deliverable");
    result.append(element("span", "", "Что ждём от команды"), element("p", "", data.expected_result));
    body.append(result);
    const score = element("div", "catalog-card-rating");
    score.append(element("span", "", rating ? levels[rating.level] : "Ещё не рассчитан"));
    if (rating) {
      const value = element("span");
      value.append(element("strong", "", String(rating.score)), element("small", "", " / 100"));
      score.append(value);
    }
    body.append(score);
    if (rating) {
      const meter = element("progress");
      meter.max = 100;
      meter.value = rating.score;
      meter.setAttribute("aria-label", `Готовность: ${rating.score} из 100`);
      body.append(meter);
    }
    const open = element("a", "button button-outline", "Посмотреть задачу →");
    open.href = `#task/${encodeURIComponent(task.id)}`;
    open.setAttribute("aria-label", `Посмотреть задачу: ${data.title}`);
    open.addEventListener("click", () => { returnScroll = window.scrollY; saveState(); });
    body.append(open);
    article.append(top, body);
    return article;
  }

  function render() {
    const term = query.value.trim().toLocaleLowerCase("ru");
    const visible = tasks.filter(task => {
      const data = task.published_card;
      return (!topic.value || task.topic === topic.value)
        && (!readiness.value || task.published_rating?.level === readiness.value)
        && `${data.title} ${data.need} ${data.expected_result} ${task.topic}`.toLocaleLowerCase("ru").includes(term);
    }).sort((a, b) => (b.published_rating?.score ?? -1) - (a.published_rating?.score ?? -1)
      || a.published_at.localeCompare(b.published_at) || a.id.localeCompare(b.id));
    grid.replaceChildren(...visible.map(card));
    count.textContent = `Показано ${visible.length} из ${tasks.length} задач`;
    empty.hidden = visible.length !== 0;
  }

  function reset() { form.reset(); returnScroll = 0; saveState(); render(); }

  async function load() {
    grid.setAttribute("aria-busy", "true");
    error.hidden = empty.hidden = true;
    count.textContent = "Загружаем задачи…";
    grid.replaceChildren();
    try {
      const response = await fetch("/static/catalog-demo.json");
      if (!response.ok) throw new Error("Catalog unavailable");
      const data = await response.json();
      if (!Array.isArray(data) || !data.every(task => typeof task.id === "string"
        && typeof task.topic === "string" && typeof task.published_at === "string"
        && task.status === "published" && typeof task.published_card?.title === "string"
        && typeof task.published_card?.need === "string" && typeof task.published_card?.expected_result === "string"
        && (task.published_rating === null || (Number.isInteger(task.published_rating?.score)
          && task.published_rating.score >= 0 && task.published_rating.score <= 100
          && Object.hasOwn(levels, task.published_rating.level))))) throw new Error("Invalid catalog data");
      tasks = data;
      const selected = topic.value || (typeof saved.topic === "string" ? saved.topic : "");
      topic.replaceChildren(new Option("Все темы", ""), ...[...new Set(tasks.map(task => task.topic))]
        .sort((a, b) => a.localeCompare(b, "ru")).map(value => new Option(value, value)));
      topic.value = [...topic.options].some(option => option.value === selected) ? selected : "";
      render();
      restorePosition();
    } catch {
      tasks = [];
      count.textContent = "Каталог недоступен";
      error.hidden = false;
    } finally { grid.setAttribute("aria-busy", "false"); }
  }

  form.addEventListener("submit", event => event.preventDefault());
  form.addEventListener("input", () => { if (error.hidden) { returnScroll = 0; saveState(); render(); } });
  document.querySelector("#catalog-reset").addEventListener("click", () => { if (error.hidden) reset(); });
  document.querySelector("#catalog-empty-reset").addEventListener("click", reset);
  document.querySelector("#catalog-retry").addEventListener("click", load);
  window.addEventListener("hashchange", restorePosition);
  load();
})();
