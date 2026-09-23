/* Public published snapshots only. Readiness is calculated by the server. */
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
  let generation = 0;
  let controller;
  const stateKey = "ai-sana:catalog-filters";
  let saved = {};
  try { saved = JSON.parse(sessionStorage.getItem(stateKey)) || {}; } catch { /* Optional tab state. */ }
  if (!saved || typeof saved !== "object") saved = {};
  query.value = typeof saved.query === "string" ? saved.query.slice(0, 200) : "";
  readiness.value = Object.hasOwn(levels, saved.readiness) ? saved.readiness : "";
  let returnScroll = Number.isFinite(saved.scroll) ? Math.max(0, saved.scroll) : 0;

  function saveState() {
    saved = { query: query.value, topic: topic.value, readiness: readiness.value, scroll: returnScroll };
    try { sessionStorage.setItem(stateKey, JSON.stringify(saved)); } catch { /* Works without storage. */ }
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
    top.append(element("span", "catalog-card-topic", window.SanaTeam.topics[task.topic] || task.topic || "Без темы"), element("span", "catalog-card-number", "↗"));
    const body = element("div", "catalog-card-body");
    body.append(element("h2", "", data.title || "Название нужно уточнить"), element("p", "catalog-card-description", data.need || "Потребность нужно уточнить с бизнесом."));
    const result = element("div", "catalog-deliverable");
    result.append(element("span", "", "Что ждём от команды"), element("p", "", data.expected_result || "Ожидаемый результат нужно уточнить."));
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
        && `${data.title} ${data.need} ${data.expected_result} ${task.topic} ${window.SanaTeam.topics[task.topic] || ""}`.toLocaleLowerCase("ru").includes(term);
    }).sort((a, b) => (b.published_rating?.score ?? -1) - (a.published_rating?.score ?? -1)
      || a.published_at.localeCompare(b.published_at) || a.id.localeCompare(b.id));
    grid.replaceChildren(...visible.map(card));
    count.textContent = `Показано ${visible.length} из ${tasks.length} задач`;
    empty.hidden = visible.length !== 0;
    empty.querySelector("h2").textContent = tasks.length ? "Пока ничего не нашлось" : "Первые задачи скоро появятся";
    empty.querySelector("p").textContent = tasks.length ? "Попробуйте другую тему или уберите часть фильтров."
      : "В каталоге пока нет публикаций. Бизнесу нужно подтвердить и опубликовать карточку в конструкторе.";
    document.querySelector("#catalog-empty-reset").hidden = !tasks.length;
  }

  function reset() { form.reset(); returnScroll = 0; saveState(); render(); }

  async function load() {
    const current = ++generation;
    controller?.abort();
    controller = new AbortController();
    grid.setAttribute("aria-busy", "true");
    error.hidden = empty.hidden = true;
    count.textContent = "Загружаем задачи…";
    grid.replaceChildren();
    try {
      const data = await window.SanaTeam.request("/api/catalog", { signal: controller.signal });
      if (current !== generation) return;
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
        .sort((a, b) => a.localeCompare(b, "ru")).map(value => new Option(window.SanaTeam.topics[value] || value || "Без темы", value)));
      topic.value = [...topic.options].some(option => option.value === selected) ? selected : "";
      render();
      restorePosition();
    } catch {
      if (current !== generation) return;
      tasks = [];
      count.textContent = "Каталог недоступен";
      error.hidden = false;
    } finally { if (current === generation) grid.setAttribute("aria-busy", "false"); }
  }

  form.addEventListener("submit", event => event.preventDefault());
  form.addEventListener("input", () => { if (error.hidden) { returnScroll = 0; saveState(); render(); } });
  document.querySelector("#catalog-reset").addEventListener("click", () => { if (error.hidden) reset(); });
  document.querySelector("#catalog-empty-reset").addEventListener("click", reset);
  document.querySelector("#catalog-retry").addEventListener("click", load);
  document.querySelector("#catalog-refresh").addEventListener("click", load);
  window.addEventListener("hashchange", () => { if (location.hash === "#catalog") load(); });
  load();
})();
