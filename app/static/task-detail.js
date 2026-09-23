/* Public task view: published snapshots only, never private business drafts. */
(() => {
  "use strict";
  const main = document.querySelector("#main-content");
  if (!main) return;
  const page = document.createElement("section");
  page.id = "page-task";
  page.className = "page task-detail";
  page.hidden = true;
  page.setAttribute("aria-labelledby", "task-title");
  // Static markup only. All task content is assigned with textContent below.
  page.innerHTML = `
    <div class="task-breadcrumb"><a class="task-back" href="#catalog">← Назад в каталог</a><span class="badge badge-mint">Опубликована</span></div>
    <div class="page-heading"><div><p class="eyebrow" id="task-topic">КАТАЛОГ ЗАДАЧ</p><h1 id="task-title" tabindex="-1">Описание задачи</h1><p class="subtitle" id="task-subtitle">Разберитесь в задаче, прежде чем предложить свой подход.</p></div></div>
    <p id="task-loading" class="task-loading panel" role="status" hidden>Загружаем описание задачи…</p>
    <div id="task-failure" class="panel empty-state" role="alert" hidden><h2 id="task-failure-title"></h2><p id="task-failure-message"></p><button id="task-retry" class="button button-primary" type="button">Повторить загрузку</button><a class="task-back" href="#catalog">Вернуться к задачам</a></div>
    <div id="task-body" class="task-layout" hidden>
      <div class="task-sections" id="task-sections"></div>
      <aside class="task-aside" aria-label="Готовность и рекомендации">
        <section class="panel task-rating"><div class="task-panel-heading"><h2>Готовность задачи</h2><span id="task-level" class="badge badge-blue"></span></div><p id="task-score" class="task-score"></p><progress id="task-progress" max="100"></progress><p class="task-caption">Полнота описания опубликованной версии. Не оценка качества идеи.</p><div class="task-open-note">Задачи любого уровня доступны командам. Низкий рейтинг означает, что стоит уточнить детали.</div></section>
        <section class="panel task-ai"><div class="task-panel-heading"><h2>Рекомендации ИИ</h2><span aria-hidden="true">✳</span></div><p class="task-caption">Не требования бизнеса. Команда может предложить другой стек и подход.</p><ul id="task-recommendations"></ul></section>
        <section class="panel task-response"><h2>Есть идея решения?</h2><p class="task-caption">Подготовьте черновик от имени своей команды. Готовый прототип не обязателен.</p><button id="task-proposal-open" class="button button-primary" type="button">Подготовить отклик →</button></section>
      </aside>
    </div>
    <div id="task-proposal" hidden></div>
    <footer class="page-footer"><span>Демонстрационные профили · без авторизации</span><span>От понятной задачи — к полезному решению ↗</span></footer>`;
  main.append(page);
  const get = id => page.querySelector(`#${id}`);
  const labels = { draft: "Черновик", working: "Рабочая", ready: "Готовая", priority: "Приоритетная" };
  const groups = [
    { title: "Задача бизнеса", tone: "blue", fields: [["context", "Контекст"], ["need", "Что нужно изменить"], ["users", "Для кого создаём"]] },
    { title: "Данные и рамки работы", tone: "yellow", fields: [["data", "Доступные данные и материалы"], ["constraints", "Ограничения и сроки"]] },
    { title: "Ожидаемый результат", tone: "mint", fields: [["expected_result", "Что нужно получить"], ["success_criteria", "Как проверяется успех"]] },
    { title: "Взаимодействие с бизнесом", tone: "blue", fields: [["contact", "Контакт"], ["interaction_format", "Формат работы и обратная связь"]] },
  ];
  let controller;
  let generation = 0;

  function textElement(tag, text, className = "") {
    const el = document.createElement(tag);
    el.textContent = text;
    el.className = className;
    return el;
  }

  async function loadTask(id, signal) {
    let task;
    try { task = await window.SanaTeam.request(`/api/catalog/${encodeURIComponent(id)}`, { signal }); }
    catch (error) { if (error.status === 404) return null; throw error; }
    if (task.id !== id || task.status !== "published") throw new Error("invalid_data");
    const card = task.published_card;
    if (!card || typeof card.title !== "string" || typeof task.topic !== "string"
      || groups.some(group => group.fields.some(([key]) => card[key] != null && typeof card[key] !== "string"))
      || (card.ai_recommendations != null && (!Array.isArray(card.ai_recommendations)
        || card.ai_recommendations.some(item => typeof item !== "string")))) throw new Error("invalid_data");
    const rating = task.published_rating;
    if (rating != null && (!Number.isInteger(rating.score) || rating.score < 0 || rating.score > 100
      || !Object.hasOwn(labels, rating.level))) throw new Error("invalid_rating");
    return task;
  }

  function render(task) {
    const card = task.published_card;
    const title = card.title.trim() || "Название нужно уточнить";
    get("task-title").textContent = title;
    get("task-topic").textContent = window.SanaTeam.topics[task.topic] || task.topic || "Тема не указана";
    document.title = `${title} · AI Sana Challenge Hub`;
    const sections = groups.map((group, index) => {
      const section = document.createElement("section");
      section.className = `panel task-section task-tone-${group.tone}`;
      const heading = textElement("h2", group.title);
      heading.id = `task-section-${index}`;
      section.setAttribute("aria-labelledby", heading.id);
      section.append(heading);
      const fields = document.createElement("dl");
      group.fields.forEach(([key, label]) => {
        const value = (card[key] || "").trim();
        fields.append(textElement("dt", label), textElement("dd", value || "Нужно уточнить", value ? "" : "task-missing"));
      });
      section.append(fields);
      return section;
    });
    get("task-sections").replaceChildren(...sections);
    const rating = task.published_rating;
    get("task-level").textContent = rating ? labels[rating.level] : "Без оценки";
    get("task-score").replaceChildren(...(rating
      ? [textElement("strong", String(rating.score)), textElement("span", " / 100")]
      : [textElement("span", "Ещё не рассчитан")]));
    get("task-progress").hidden = !rating;
    if (rating) {
      get("task-progress").value = rating.score;
      get("task-progress").setAttribute("aria-label", `Готовность: ${rating.score} из 100`);
    }
    const recommendations = (card.ai_recommendations || []).filter(text => text.trim());
    get("task-recommendations").replaceChildren(...(recommendations.length ? recommendations : ["Рекомендации пока не добавлены."])
      .map(text => textElement("li", text)));
    get("task-body").hidden = false;
    get("task-proposal").hidden = false;
    window.SanaProposalForm.mount(get("task-proposal"), { id: task.id, title, source: "public" });
  }

  function failure(notFound) {
    get("task-failure-title").textContent = notFound ? "Задача не найдена" : "Не удалось загрузить задачу";
    get("task-failure-message").textContent = notFound
      ? "Такой опубликованной задачи нет. Вернитесь в каталог и выберите другую."
      : "Проверьте соединение и повторите попытку. Мы не подменяем ошибку другой карточкой.";
    get("task-retry").hidden = notFound;
    get("task-failure").hidden = false;
  }

  async function showTask() {
    const current = ++generation;
    controller?.abort();
    window.SanaProposalForm.unmount();
    get("task-proposal").hidden = true;
    if (window.location.hash.split("/")[0] !== "#task") return;
    get("task-body").hidden = get("task-failure").hidden = true;
    get("task-loading").hidden = false;
    get("task-title").textContent = "Описание задачи";
    get("task-topic").textContent = "КАТАЛОГ ЗАДАЧ";
    page.setAttribute("aria-busy", "true");
    let timeout;
    try {
      let id;
      try { id = decodeURIComponent(window.location.hash.slice(6)); } catch { id = ""; }
      if (!id || id.length > 200) { failure(true); return; }
      const requestController = new AbortController();
      controller = requestController;
      timeout = setTimeout(() => requestController.abort(), 12000);
      const task = await loadTask(id, requestController.signal);
      if (generation !== current) return;
      if (task) render(task); else failure(true);
    } catch {
      if (generation === current) failure(false);
    } finally {
      clearTimeout(timeout);
      if (generation === current) {
        get("task-loading").hidden = true;
        page.setAttribute("aria-busy", "false");
      }
    }
  }

  get("task-retry").addEventListener("click", showTask);
  get("task-proposal-open").addEventListener("click", () => {
    const heading = get("task-proposal").querySelector("#proposal-title");
    heading?.focus({ preventScroll: true });
    get("task-proposal").scrollIntoView({ block: "start" });
  });
  window.addEventListener("hashchange", showTask);
  showTask();
})();
