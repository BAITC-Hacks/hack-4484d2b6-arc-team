/* Business constructor, confirmation and publication via API v0.3. No client scoring. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const fields = [
    ["title", "Название", "Коротко: какую задачу нужно решить?"],
    ["context", "Текущая ситуация", "Как устроен процесс сейчас?"],
    ["need", "Потребность / проблема", "Что нужно изменить и почему?"],
    ["users", "Пользователи", "Кто и в какой ситуации будет пользоваться решением?"],
    ["data", "Данные и материалы", "Какие данные есть, в каком формате и как получить доступ?"],
    ["constraints", "Ограничения", "Сроки, доступы и другие границы проекта."],
    ["expected_result", "Ожидаемый результат", "Какой результат нужен и как он будет использоваться?"],
    ["success_criteria", "Критерии успеха", "Что и каким способом проверит бизнес?"],
    ["contact", "Контакт", "Для демонстрации используйте синтетические контакты."],
    ["interaction_format", "Взаимодействие и обратная связь", "Как часто и в каком формате бизнес сможет отвечать команде?"],
  ];
  const emptyCard = () => ({ ...Object.fromEntries(fields.map(([key]) => [key, ""])), ai_recommendations: [] });
  const fresh = () => ({ version: 1, task: null, text: "", topic: "", answers: {}, card: emptyCard(), cardReady: false, stage: "draft", dirty: { draft: false, answers: false, card: false } });
  let state = fresh();
  let profile = "";
  let tasks = [];
  let busy = false;
  let ready = false;
  let failedOperation = null;
  let aiStatus = null;
  let sourceMode = "local";
  let reviewed = false;
  let versionConflict = false;
  const memory = new Map();
  const levelLabels = { draft: "Черновик", working: "Рабочая", ready: "Готовая", priority: "Приоритетная" };
  const sourceEdits = () => state.dirty.draft || state.dirty.answers;
  const cardEdits = () => state.dirty.card || state.topic !== state.task?.topic || state.task?.has_unconfirmed_changes !== false;
  const canReview = () => Boolean(state.task && state.cardReady && state.stage === "card" && !sourceEdits() && !versionConflict && cardEdits());
  const canPublish = () => Boolean(state.task?.confirmed_rating && state.task.has_unpublished_changes && !cardEdits() && !sourceEdits() && !versionConflict);

  function storageGet(key) {
    if (memory.has(key)) return memory.get(key);
    try { return localStorage.getItem(key); } catch { $("builder-storage-warning").hidden = false; return null; }
  }
  function storageSet(key, value) {
    memory.set(key, value);
    try { localStorage.setItem(key, value); } catch { $("builder-storage-warning").hidden = false; }
  }
  const cacheKey = (taskId = "new") => `sana:builder:${profile}:${taskId}`;
  function persist() {
    if (!profile) return;
    storageSet(cacheKey(state.task?.id), JSON.stringify(state));
    storageSet(`sana:builder:active:${profile}`, state.task?.id || "");
  }
  function cached(taskId) {
    try {
      const value = JSON.parse(storageGet(cacheKey(taskId || "new")) || "null");
      if (value?.version === 1 && typeof value.text === "string" && typeof value.topic === "string"
          && value.dirty && value.card && value.answers && ["draft", "questions", "card"].includes(value.stage)
          && (!value.task || value.task.business_id === profile)) return value;
    } catch { /* Ignore an obsolete or invalid local copy. */ }
    return null;
  }
  function message(text) { $("builder-status").textContent = text; }
  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function option(value, label) { const node = element("option", "", label); node.value = value; return node; }

  async function api(path, method = "GET", body) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 90000);
    try {
      const response = await fetch(path, {
        method, signal: controller.signal,
        headers: { "Content-Type": "application/json", ...(profile ? { "X-Demo-Business-Id": profile } : {}) },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
      let data;
      try { data = await response.json(); } catch { throw new Error("Сервер вернул неожиданный ответ. Проверьте подключение и повторите действие."); }
      if (!response.ok) {
        const error = new Error(data.error?.message || "Не удалось выполнить запрос.");
        error.details = data.error?.details;
        error.localAvailable = data.error?.local_mode_available === true;
        error.code = data.error?.code;
        throw error;
      }
      return data;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("Сервер не ответил вовремя. Введённый текст остался в форме.");
      if (error instanceof TypeError) throw new Error("Нет соединения с сервером. Введённый текст остался в форме.");
      throw error;
    } finally { clearTimeout(timer); }
  }
  const taskPath = () => `/api/tasks/${encodeURIComponent(state.task.id)}`;

  function lock() {
    $("builder-fields").disabled = busy || !ready;
    $("builder-content").setAttribute("aria-busy", String(busy));
    for (const id of ["builder-business", "builder-task", "builder-new", "builder-mode"]) $(id).disabled = busy || !ready;
    $("demo-profile").disabled = busy;
    $("builder-retry").disabled = busy;
    $("builder-local").disabled = busy;
    $("builder-reviewed").disabled = busy || !ready || !canReview();
    $("builder-confirm").disabled = busy || !ready || !canReview() || !reviewed;
    $("builder-publish").disabled = busy || !ready || !canPublish();
    $("builder-save-materials").disabled = busy || !ready;
    $("builder-missing-fields").querySelectorAll("button").forEach((button) => { button.disabled = busy || !ready; });
    document.querySelectorAll("#page-builder [data-stage]").forEach((button) => {
      button.disabled = busy || !ready || (button.dataset.stage === "questions" && !state.task?.questions.length)
        || (button.dataset.stage === "card" && !state.cardReady);
    });
  }

  async function run(label, operation, allowsLocal = false) {
    if (busy) return false;
    const initialStage = state.stage;
    busy = true;
    failedOperation = null;
    $("builder-error").hidden = true;
    message(label);
    lock();
    try {
      await operation();
      return true;
    } catch (error) {
      if (["task_changed", "confirmation_required"].includes(error.code)) {
        versionConflict = true;
        reviewed = false;
      }
      persist();
      $("builder-error-message").textContent = `${error.message} Ввод сохранён в текущей форме.`;
      $("builder-error-details").replaceChildren();
      for (const detail of error.details || []) {
        $("builder-error-details").append(element("li", "", `${detail.field}: ${detail.message}`));
      }
      $("builder-local").hidden = !(allowsLocal && error.localAvailable);
      // Refresh conflicts for review; never retry a confirmation automatically.
      failedOperation = ["task_changed", "confirmation_required"].includes(error.code)
        ? () => run("Загружаем актуальные сведения…", async () => { await openTask(state.task.id); message("Сведения обновлены. Ваши несохранённые правки оставлены в форме; проверьте их перед повтором."); })
        : () => run(label, operation, allowsLocal);
      $("builder-retry").textContent = ["task_changed", "confirmation_required"].includes(error.code) ? "Обновить сведения" : "Повторить";
      $("builder-error").hidden = false;
      message("Действие не завершено. Можно повторить запрос.");
      return false;
    } finally {
      busy = false;
      render();
      lock();
      if (!$("page-builder").hidden) {
        if (!$("builder-error").hidden) $("builder-error").focus();
        else if (state.stage !== initialStage) focusStage();
      }
    }
  }

  function acceptTask(task) {
    reviewed = false;
    const wasNew = !state.task;
    state.task = task;
    const index = tasks.findIndex((item) => item.id === task.id);
    if (index >= 0) tasks[index] = task;
    else tasks.push(task);
    if (wasNew) {
      // Once POST succeeds, retries reuse this ID rather than creating another task.
      memory.delete(cacheKey());
      try { localStorage.removeItem(cacheKey()); } catch { /* Optional browser backup. */ }
    }
    persist();
  }

  async function ensureDraft() {
    if (!state.text.trim()) { state.stage = "draft"; throw new Error("Опишите задачу хотя бы одним предложением."); }
    if (!state.task) {
      acceptTask(await api("/api/tasks", "POST", { original_text: state.text, topic: state.topic }));
    } else if (state.dirty.draft) {
      acceptTask(await api(taskPath(), "PATCH", { draft_text: state.text, topic: state.topic }));
    }
    state.dirty.draft = false;
    persist();
  }
  async function saveAnswers() {
    await ensureDraft();
    if (state.dirty.answers) {
      acceptTask(await api(taskPath(), "PATCH", { answers: state.answers }));
      state.dirty.answers = false;
      persist();
    }
  }
  async function questions() {
    await saveAnswers();
    const result = await api(`${taskPath()}/questions`, "POST", { mode: sourceMode });
    acceptTask(result.task);
    state.answers = { ...result.task.answers };
    state.stage = "questions";
    persist();
    message("Вопросы готовы. Ответьте на них или укажите, что пока не знаете.");
  }
  async function generateCard() {
    await ensureDraft();
    const result = await api(`${taskPath()}/generate-card`, "POST", { mode: sourceMode, answers: state.answers });
    acceptTask(result.task);
    state.answers = { ...result.task.answers };
    state.card = structuredClone(result.task.proposed_card);
    state.cardReady = true;
    state.dirty.answers = false;
    state.dirty.card = false;
    state.stage = "card";
    persist();
    message("Рабочая карточка сформирована и сохранена. Проверьте сведения и внесите правки.");
  }

  async function confirmCard() {
    if (!canReview() || !reviewed) throw new Error("Сначала сохраните описание и ответы, затем проверьте карточку и отметьте подтверждение сведений.");
    // Send the card atomically with the version actually reviewed. A preliminary
    // PATCH here would hide a concurrent edit by acquiring a newer version first.
    const task = await api(`${taskPath()}/confirm`, "POST", {
      expected_updated_at: state.task.updated_at,
      proposed_card: state.card,
    });
    acceptTask(task);
    state.card = structuredClone(task.proposed_card);
    state.dirty.card = false;
    persist();
    message(`Карточка подтверждена. Готовность: ${task.confirmed_rating.score} / 100. Публикация выполняется отдельным действием.`);
  }

  async function publishCard() {
    if (!canPublish()) throw new Error("Проверьте и подтвердите текущую карточку перед публикацией.");
    acceptTask(await api(`${taskPath()}/publish`, "POST", { expected_updated_at: state.task.updated_at }));
    message("Подтверждённая версия опубликована на сервере. Каталог пока показывает демонстрационные примеры.");
  }

  async function openTask(taskId) {
    reviewed = false;
    const backup = cached(taskId);
    // Restore local input before the network call; a failed GET must not erase it.
    state = backup || fresh();
    if (!taskId) { versionConflict = false; persist(); return; }
    const task = await api(`/api/tasks/${encodeURIComponent(taskId)}`);
    state.task = task;
    versionConflict = false;
    if (!backup?.dirty.draft) { state.text = task.draft_text; state.topic = task.topic; state.dirty.draft = false; }
    if (!backup?.dirty.answers) { state.answers = { ...task.answers }; state.dirty.answers = false; }
    if (!backup?.dirty.card) { state.card = structuredClone(task.proposed_card); state.dirty.card = false; }
    state.cardReady = Boolean(task.card_ai || Object.values(state.card).some((value) => value.length));
    if (!backup) state.stage = state.cardReady ? "card" : task.questions.length ? "questions" : "draft";
    if (!task.questions.length && state.stage === "questions") state.stage = "draft";
    persist();
  }
  async function loadBusiness(id) {
    profile = id;
    ready = false;
    tasks = [];
    const activeId = storageGet(`sana:builder:active:${profile}`) || "";
    state = cached(activeId) || fresh();
    storageSet("sana:builder:business", profile);
    tasks = await api("/api/tasks");
    const taskId = tasks.some((task) => task.id === activeId) ? activeId : "";
    await openTask(taskId);
    ready = true;
    message(Object.values(state.dirty).some(Boolean) ? "Восстановлена локальная копия. Сохраните изменения на сервере." : "Можно продолжить сохранённый черновик или описать новую задачу.");
  }
  async function initialize() {
    const [profiles, status] = await Promise.all([api("/api/demo/profiles"), api("/api/ai/status")]);
    if (!profiles.businesses.length) throw new Error("Демонстрационные профили ещё не подготовлены. Попросите организатора демонстрации добавить их.");
    aiStatus = status;
    sourceMode = status.default_mode;
    $("builder-mode").value = sourceMode;
    $("builder-business").replaceChildren(...profiles.businesses.map((item) => option(item.id, item.name)));
    const saved = storageGet("sana:builder:business");
    const chosen = profiles.businesses.some((item) => item.id === saved) ? saved : profiles.businesses[0].id;
    $("builder-business").value = chosen;
    await loadBusiness(chosen);
  }

  function sourceText(meta, fallback) { return meta ? `${meta.message}${meta.model ? ` Модель: ${meta.model}.` : ""}` : fallback; }
  function renderReadiness() {
    const task = state.task;
    const rating = task?.confirmed_rating;
    const pending = cardEdits();
    $("builder-unrated").hidden = Boolean(rating);
    $("builder-rating").hidden = !rating;
    $("builder-level").hidden = !rating;
    $("builder-score").textContent = rating ? rating.score : "";
    $("builder-score-meter").value = rating ? rating.score : 0;
    $("builder-level").textContent = rating ? levelLabels[rating.level] || rating.level : "";
    $("builder-level").className = `badge ${rating && ["ready", "priority"].includes(rating.level) ? "badge-mint" : "badge-blue"}`;
    $("builder-card-state").textContent = pending ? "Рабочая версия" : "Подтверждена";
    $("builder-card-state").className = `badge ${pending ? "badge-yellow" : "badge-mint"}`;
    const changes = $("builder-rating-changes");
    changes.dataset.pending = String(pending);
    changes.textContent = !rating ? "Рейтинг появится после ручного подтверждения карточки. Незаполненные сведения не дают баллов."
      : pending ? "Есть неподтверждённые изменения. Показан прежний рейтинг; после проверки подтвердите новую версию."
        : sourceEdits() ? "Описание или ответы изменены. Они не меняют карточку и рейтинг автоматически. Проверьте, нужно ли обновить карточку."
          : "Карточка и тема подтверждены. Баллы рассчитаны сервером.";

    const expanded = new Set([...$("builder-rating-categories").querySelectorAll("details[open]")].map((node) => node.dataset.category));
    $("builder-rating-categories").replaceChildren();
    for (const category of rating?.categories || []) {
      const details = element("details", "builder-rating-category");
      details.dataset.category = category.key;
      details.open = expanded.has(category.key);
      const summary = element("summary");
      const complete = category.points === category.maximum;
      const indicator = element("span", `category-indicator${complete ? " complete" : category.points ? " partial" : ""}`, complete ? "✓" : category.points ? "◷" : "");
      indicator.setAttribute("aria-hidden", "true");
      const score = element("span", "category-score");
      score.append(element("strong", "", category.points), document.createTextNode(` / ${category.maximum}`));
      summary.append(indicator, element("span", "", category.label), score, element("span", "chevron", "›"));
      const list = element("ul");
      for (const field of category.fields) {
        const item = element("li");
        item.append(element("span", "", field.label), element("span", "", `${field.points} / ${field.maximum}`));
        list.append(item);
      }
      details.append(summary, list);
      $("builder-rating-categories").append(details);
    }
    $("builder-missing").hidden = !rating;
    $("builder-missing-fields").replaceChildren();
    const fieldLabels = Object.fromEntries(fields.map(([key, label]) => [key, label]));
    for (const key of rating?.missing_fields || []) {
      const item = element("li");
      const button = element("button", "", `${fieldLabels[key] || key} →`);
      button.type = "button";
      button.dataset.missingField = key;
      button.addEventListener("click", () => {
        if (busy) return;
        state.stage = "card";
        persist(); render(); lock();
        $(`builder-card-${key}`)?.focus();
      });
      item.append(button);
      $("builder-missing-fields").append(item);
    }
    $("builder-missing-complete").hidden = !rating || Boolean(rating.missing_fields.length);
    $("builder-reviewed").checked = reviewed;
    $("builder-reviewed").closest("label").hidden = Boolean(rating) && !pending;
    $("builder-review-card").hidden = state.stage === "card" || !state.cardReady;
    $("builder-confirm").textContent = rating && !pending ? "Сведения подтверждены" : rating ? "Подтвердить изменения" : "Сохранить и подтвердить";
    $("builder-save-materials").hidden = !sourceEdits();
    $("builder-confirm-help").textContent = versionConflict ? "Задача изменилась. Обновите сведения через сообщение об ошибке и проверьте карточку заново."
      : !state.cardReady ? "Сначала сформируйте карточку по описанию и ответам."
        : sourceEdits() ? "Сначала сохраните описание и ответы. Затем проверьте, что карточка отражает ваши изменения."
          : "Подтверждение сохранит карточку и пересчитает рейтинг. Публикация — отдельное действие.";

    const published = task?.status === "published";
    $("builder-publication-state").textContent = published ? "Опубликована" : "Не опубликована";
    $("builder-publication-state").className = `badge ${published ? "badge-mint" : "badge-yellow"}`;
    $("builder-publish").textContent = published ? task.has_unpublished_changes || pending ? "Обновить публикацию" : "Публикация актуальна" : "Опубликовать задачу";
    $("builder-publication-help").textContent = !rating ? "Сначала проверьте и подтвердите карточку в панели готовности."
      : pending || sourceEdits() ? published ? "Правки ещё не опубликованы. Предыдущая публикация сохранена; проверьте и подтвердите новую карточку."
        : "Проверьте и подтвердите текущие изменения перед публикацией."
        : task.has_unpublished_changes ? published ? "Новая версия подтверждена. Опубликуйте её, чтобы заменить предыдущую публикацию."
          : "Карточка подтверждена и готова к публикации. Низкий рейтинг не ограничивает публикацию."
          : "Опубликована последняя подтверждённая версия. Дальнейшие правки останутся рабочими до нового подтверждения и публикации.";
    $("builder-published-snapshot").hidden = !task?.published_card;
    $("builder-published-snapshot").textContent = task?.published_card
      ? `В публикации: «${task.published_card.title}» · ${task.published_rating.score} / 100 · ${levelLabels[task.published_rating.level] || task.published_rating.level}.` : "";
  }
  function render() {
    $("builder-draft").value = state.text;
    $("builder-char-count").textContent = state.text.length.toLocaleString("ru-RU");
    const topic = $("builder-topic");
    if (![...topic.options].some((item) => item.value === state.topic)) topic.append(option(state.topic, state.topic));
    topic.value = state.topic;
    $("builder-task").replaceChildren(option("", "Новая задача"), ...tasks.map((task) => option(task.id, task.proposed_card.title || task.draft_text.slice(0, 75))));
    $("builder-task").value = state.task?.id || "";
    document.querySelectorAll("[data-builder-step]").forEach((item) => {
      const active = item.dataset.builderStep === state.stage;
      item.classList.toggle("is-current", active);
      if (active) item.setAttribute("aria-current", "step");
      else item.removeAttribute("aria-current");
    });
    for (const stage of ["draft", "questions", "card"]) $("builder-stage-" + stage).hidden = state.stage !== stage;
    $("builder-questions").replaceChildren();
    for (const [index, question] of (state.task?.questions || []).entries()) {
      const wrapper = element("div", "question-card builder-question");
      const label = element("label");
      const input = element("textarea", "field-control");
      input.id = `builder-answer-${index}`;
      input.dataset.questionId = question.id;
      input.maxLength = 20000;
      input.value = state.answers[question.id] || "";
      input.placeholder = "Ваш ответ или «не знаю»";
      label.htmlFor = input.id;
      label.append(element("span", `question-number ${["number-blue", "number-mint", "number-yellow"][index % 3]}`, index + 1), element("span", "", question.text));
      wrapper.append(label, input);
      $("builder-questions").append(wrapper);
    }
    $("builder-card-fields").replaceChildren();
    for (const [key, labelText, hint] of fields) {
      const wrapper = element("div", "form-field");
      const label = element("label", "", labelText);
      const input = element(key === "title" ? "input" : "textarea", "field-control");
      input.id = `builder-card-${key}`;
      input.dataset.cardField = key;
      input.value = state.card[key];
      input.maxLength = 20000;
      input.placeholder = "Пока не указано";
      label.htmlFor = input.id;
      const description = element("p", "field-hint", hint);
      description.id = `${input.id}-hint`;
      input.setAttribute("aria-describedby", description.id);
      wrapper.append(label, description, input);
      $("builder-card-fields").append(wrapper);
    }
    $("builder-recommendations").replaceChildren(...(state.card.ai_recommendations.length ? state.card.ai_recommendations : ["Рекомендаций пока нет."]).map((text) => element("li", "", text)));
    $("builder-questions-source").textContent = sourceText(state.task?.questions_ai, "Источник вопросов не указан.");
    $("builder-card-source").textContent = state.dirty.card ? "Есть несохранённые правки. Они ещё не подтверждены бизнесом." : sourceText(state.task?.card_ai, "Рабочая карточка отредактирована вручную. Подтверждение выполняется отдельно.");
    $("builder-mode-description").textContent = sourceMode === "local"
      ? "Локальные шаблоны, без внешней AI-модели. Неизвестные сведения останутся пустыми."
      : aiStatus?.openai_configured ? "Описание и ответы будут переданы OpenAI. Проверьте результат перед подтверждением."
        : "OpenAI не настроен на сервере. Можно выбрать локальный режим или повторить после настройки.";
    renderReadiness();
    showRole();
  }
  function showRole() {
    const team = document.documentElement.dataset.demoRole === "team";
    $("builder-team-notice").hidden = !team;
    $("builder-workspace").hidden = team;
  }
  function focusStage() {
    $(state.stage === "draft" ? "builder-draft" : state.stage === "questions" ? "questions-heading" : "card-heading").focus();
  }
  function dirty(kind) {
    state.dirty[kind] = true;
    reviewed = false;
    persist();
    renderReadiness();
    lock();
    message("Есть несохранённые изменения. Сохраните их на сервере перед завершением работы.");
  }

  $("builder-draft").addEventListener("input", (event) => {
    state.text = event.target.value;
    $("builder-char-count").textContent = state.text.length.toLocaleString("ru-RU");
    dirty("draft");
  });
  $("builder-topic").addEventListener("change", (event) => { state.topic = event.target.value; dirty("draft"); });
  $("builder-questions").addEventListener("input", (event) => {
    if (!event.target.dataset.questionId) return;
    state.answers[event.target.dataset.questionId] = event.target.value;
    dirty("answers");
  });
  $("builder-card-fields").addEventListener("input", (event) => {
    if (!event.target.dataset.cardField) return;
    state.card[event.target.dataset.cardField] = event.target.value;
    dirty("card");
    $("builder-card-source").textContent = "Есть несохранённые правки. Они ещё не подтверждены бизнесом.";
  });
  $("builder-draft-form").addEventListener("submit", (event) => { event.preventDefault(); run("Сохраняем описание и готовим вопросы…", questions, true); });
  $("builder-save-draft").addEventListener("click", () => run("Сохраняем черновик…", async () => { await ensureDraft(); message("Черновик сохранён на сервере."); }));
  $("builder-more-questions").addEventListener("click", () => run("Обновляем вопросы…", questions, true));
  $("builder-save-answers").addEventListener("click", () => run("Сохраняем ответы…", async () => { await saveAnswers(); message("Ответы сохранены на сервере."); }));
  $("builder-questions-form").addEventListener("submit", (event) => {
    event.preventDefault();
    // Generating again replaces the working card only after an explicit decision.
    if (state.cardReady) { $("builder-regenerate-dialog").showModal(); return; }
    run("Сохраняем ответы и формируем карточку…", generateCard, true);
  });
  $("builder-card-form").addEventListener("submit", (event) => {
    event.preventDefault();
    run("Сохраняем правки…", async () => {
      await saveAnswers();
      acceptTask(await api(taskPath(), "PATCH", { proposed_card: state.card }));
      state.dirty.card = false;
      persist();
      message("Правки сохранены на сервере. Подтверждение и публикация выполняются отдельно.");
    });
  });
  $("builder-reviewed").addEventListener("change", (event) => { reviewed = event.target.checked; lock(); });
  $("builder-confirm").addEventListener("click", () => {
    if (!$("builder-card-form").reportValidity()) return;
    run("Сохраняем и подтверждаем карточку…", confirmCard);
  });
  $("builder-publish").addEventListener("click", () => run("Публикуем подтверждённую версию…", publishCard));
  $("builder-save-materials").addEventListener("click", () => run("Сохраняем описание и ответы…", async () => {
    await saveAnswers();
    message("Описание и ответы сохранены. Проверьте, что карточка отражает эти сведения, перед подтверждением.");
  }));
  document.querySelectorAll("#page-builder [data-stage]").forEach((button) => button.addEventListener("click", () => {
    if (busy) return;
    state.stage = button.dataset.stage;
    persist(); render(); lock();
    focusStage();
  }));
  $("builder-business").addEventListener("change", (event) => { persist(); run("Загружаем черновики бизнеса…", () => loadBusiness(event.target.value)); });
  $("builder-task").addEventListener("change", (event) => { persist(); const id = event.target.value; run("Открываем черновик…", async () => { await openTask(id); message("Черновик открыт. Несохранённые правки восстановлены, если они были."); }); });
  $("builder-new").addEventListener("click", () => {
    // Persist every draft before switching; the task selector can reopen it.
    persist();
    run("Открываем новую задачу…", async () => { await openTask(""); message("Новый черновик. Начните с описания задачи."); });
  });
  $("builder-mode").addEventListener("change", (event) => { sourceMode = event.target.value; render(); lock(); });
  $("builder-retry").addEventListener("click", () => failedOperation?.());
  $("builder-local").addEventListener("click", () => { sourceMode = "local"; $("builder-mode").value = "local"; failedOperation?.(); });
  $("builder-switch-business").addEventListener("click", () => {
    $("demo-profile").value = "business";
    $("demo-profile").dispatchEvent(new Event("change"));
  });
  window.addEventListener("sana:demo-role-change", showRole);
  window.addEventListener("beforeunload", (event) => {
    persist();
    if (busy || Object.values(state.dirty).some(Boolean)) { event.preventDefault(); event.returnValue = ""; }
  });

  const dialog = element("dialog", "builder-dialog");
  dialog.id = "builder-regenerate-dialog";
  dialog.setAttribute("aria-labelledby", "builder-regenerate-title");
  const title = element("h2", "", "Сформировать карточку заново?");
  title.id = "builder-regenerate-title";
  const description = element("p", "", "Новая карточка заменит текущую рабочую версию, включая ручные правки. Описание и ответы сохранятся.");
  const actions = element("div", "builder-actions");
  const cancel = element("button", "button button-outline", "Оставить текущую");
  const replace = element("button", "button button-primary", "Сформировать заново");
  cancel.type = replace.type = "button";
  cancel.addEventListener("click", () => dialog.close());
  replace.addEventListener("click", () => { dialog.close(); run("Формируем новую рабочую карточку…", generateCard, true); });
  actions.append(cancel, replace); dialog.append(title, description, actions); document.body.append(dialog);
  showRole();
  const initialized = run("Подключаем конструктор…", initialize);
  // In-page handoff preserves each task's unsaved local copy. No second editor or
  // independent copy of constructor state is maintained by the owner dashboard.
  window.SanaBuilder = Object.freeze({
    initialized,
    context: () => ({ businessId: profile, taskId: state.task?.id || "", busy, ready }),
    async setBusiness(businessId) {
      await initialized;
      if (busy) return false;
      if (profile === businessId && ready) return true;
      persist();
      return run("Загружаем задачи выбранного бизнеса…", async () => {
        await loadBusiness(businessId);
        $("builder-business").value = businessId;
      });
    },
    async open(businessId, taskId = "") {
      await initialized;
      if (busy) return false;
      persist();
      const opened = await run("Открываем задачу в конструкторе…", async () => {
        if (profile !== businessId || !ready) await loadBusiness(businessId);
        $("builder-business").value = businessId;
        await openTask(taskId);
        message("Задача открыта. Несохранённые правки восстановлены, если они были.");
      });
      if (opened) { window.location.hash = "#builder"; focusStage(); }
      return opened;
    },
  });
})();
