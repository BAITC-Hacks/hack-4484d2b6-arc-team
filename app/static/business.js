/* Owner dashboard. All persisted decisions and awarded points come from API responses. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const api = window.SanaBusinessApi;
  const statuses = { submitted: "На рассмотрении", selected: "Команда выбрана", rejected: "Отклонено" };
  const levels = { draft: "Черновик", working: "Рабочая", ready: "Готовая", priority: "Приоритетная" };
  const topics = { retail: "Торговля", logistics: "Логистика", education: "Образование", agriculture: "Сельское хозяйство", services: "Услуги", other: "Другое" };
  let profile = "";
  let teams = new Map();
  let tasks = [];
  let selectedTask = null;
  let proposals = [];
  let capabilities = {};
  let compared = new Set();
  let loading = false;
  let mutating = false;
  let mustRefresh = false;
  let epoch = 0;
  let controller;

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function button(label, className, handler) {
    const node = el("button", className, label);
    node.type = "button";
    node.addEventListener("click", handler);
    return node;
  }
  function empty(title, text) {
    const box = el("div", "business-empty");
    box.append(el("h3", "", title), el("p", "", text));
    return box;
  }
  function status(text) { $("business-status").textContent = text; }
  function teamName(item) { return item.team_name || teams.get(item.team_id)?.name || "Команда без названия"; }
  function taskTitle(task) { return task.proposed_card?.title?.trim() || task.draft_text || "Без названия"; }
  function externalLink(value, label, absent) {
    if (!value) return el("span", "", absent);
    try {
      const url = new URL(value);
      if (!["https:", "http:"].includes(url.protocol)) throw new Error("scheme");
      const link = el("a", "business-link", label);
      link.href = url.href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      return link;
    } catch { return el("span", "", "Ссылка имеет неподдерживаемый формат."); }
  }
  function fail(error) {
    $("business-error-message").textContent = error.message;
    $("business-error").hidden = false;
    if (!$("page-business").hidden) $("business-error").focus();
  }
  function lock() {
    $("business-workspace").setAttribute("aria-busy", String(loading || mutating));
    for (const id of ["business-profile", "business-refresh", "business-filter", "business-error-retry", "business-create", "business-empty-create"]) $(id).disabled = loading || mutating;
    $("demo-profile").disabled = mutating || window.SanaBuilder.context().busy;
    $("business-compare").disabled = loading || mutating || mustRefresh || compared.size < 2;
    $("business-compare").textContent = compared.size ? `Сравнить выбранные (${compared.size})` : "Сравнить выбранные";
    $("business-tasks").querySelectorAll("button").forEach((node) => { node.disabled = loading || mutating; });
    $("business-task-detail").querySelectorAll("button").forEach((node) => { node.disabled = loading || mutating; });
    $("business-proposals").querySelectorAll("input").forEach((node) => { node.disabled = loading || mutating || mustRefresh; });
    $("business-proposals").querySelectorAll("button").forEach((node) => {
      node.disabled = loading || mutating || mustRefresh || node.dataset.unavailable === "true";
    });
  }
  function beginLoad() {
    controller?.abort();
    controller = new AbortController();
    epoch += 1;
    loading = true;
    mustRefresh = false;
    $("business-error").hidden = true;
    lock();
    return { revision: epoch, signal: controller.signal };
  }
  function showRole() {
    const isTeam = document.documentElement.dataset.demoRole === "team";
    $("business-team-notice").hidden = !isTeam;
    $("business-workspace").hidden = isTeam;
    $("business-create").hidden = isTeam;
    if (isTeam) $("business-comparison").close();
    return !isTeam;
  }
  function visibleTasks() {
    const filter = $("business-filter").value;
    return tasks.filter((task) => filter === "all" || task.status === filter);
  }
  function renderTasks() {
    $("business-total").textContent = tasks.length;
    $("business-published").textContent = tasks.filter((task) => task.status === "published").length;
    $("business-drafts").textContent = tasks.filter((task) => task.status === "draft").length;
    $("business-totals").hidden = false;
    const visible = visibleTasks();
    $("business-layout").hidden = !visible.length;
    $("business-empty").hidden = Boolean(visible.length);
    $("business-empty-text").textContent = tasks.length ? "Нет задач с таким статусом. Выберите «Все задачи» или создайте новую." : "У этого бизнеса пока нет задач. Начните с короткого описания.";
    $("business-tasks").replaceChildren();
    for (const task of visible) {
      const row = button("", "business-task", () => selectTask(task));
      row.dataset.taskId = task.id;
      row.setAttribute("aria-pressed", String(task.id === selectedTask?.id));
      row.append(el("span", `badge ${task.status === "published" ? "badge-mint" : "badge-yellow"}`, task.status === "published" ? "Опубликована" : "Не опубликована"), el("h3", "", taskTitle(task)));
      const rating = task.confirmed_rating;
      row.append(el("p", "business-task-score", rating ? `Подтверждено: ${rating.score} / 100 · ${levels[rating.level] || rating.level}` : "Рейтинг ещё не рассчитан"));
      if (task.has_unconfirmed_changes && task.confirmed_card) row.append(el("p", "", "Есть неподтверждённые правки"));
      else if (task.has_unpublished_changes) row.append(el("p", "", "Подтверждённая версия ещё не опубликована"));
      $("business-tasks").append(row);
    }
  }
  function renderTaskDetail() {
    const box = $("business-task-detail");
    box.replaceChildren();
    if (!selectedTask) return;
    box.append(el("span", "badge badge-blue", topics[selectedTask.topic] || selectedTask.topic || "Тема не указана"), el("h2", "", taskTitle(selectedTask)),
      el("p", "", selectedTask.proposed_card.need || selectedTask.draft_text), button("Открыть в конструкторе →", "button button-outline", () => openEditor(selectedTask.id)));
    if (selectedTask.status === "published" && selectedTask.published_rating) box.append(el("p", "", `Опубликованный рейтинг: ${selectedTask.published_rating.score} / 100. Рабочие правки не меняют публикацию автоматически.`));
  }
  function renderProposals() {
    const container = $("business-proposals");
    container.replaceChildren();
    $("business-proposal-count").textContent = capabilities.proposals && !loading && !mustRefresh ? `· ${proposals.length}` : "";
    $("business-proposals-notice").hidden = Boolean(capabilities.proposals);
    $("business-proposals-notice").replaceChildren(el("h3", "", "Отклики ещё не подключены"), el("p", "", "Задачи уже доступны. Просмотр предложений и решения по ним появятся после подключения серверной части."));
    if (!capabilities.proposals || !selectedTask) return;
    if (!proposals.length && !loading && !mustRefresh) {
      container.append(empty("Пока нет предложений", selectedTask.status === "published" ? "Когда команды отправят предложения, вы сможете сравнить их здесь." : "Сначала подтвердите и опубликуйте задачу через конструктор."));
      return;
    }
    for (const proposal of proposals) {
      const card = el("article", "panel business-proposal");
      card.dataset.proposalId = proposal.id;
      const header = el("div", "business-proposal-header");
      const identity = el("div");
      identity.append(el("h3", "", teamName(proposal)), el("span", `badge ${proposal.status === "selected" ? "badge-mint" : proposal.status === "rejected" ? "badge-yellow" : "badge-blue"}`, statuses[proposal.status]));
      const comparison = el("label", "business-compare-label");
      const check = el("input"); check.type = "checkbox"; check.checked = compared.has(proposal.id); check.dataset.compareId = proposal.id;
      check.addEventListener("change", () => { if (check.checked) compared.add(proposal.id); else compared.delete(proposal.id); lock(); });
      comparison.append(check, document.createTextNode("Сравнить"));
      header.append(identity, comparison);
      const details = el("dl");
      for (const [key, label] of [["idea", "Идея решения"], ["plan", "План"], ["timeline", "Срок"], ["questions", "Вопросы бизнесу"]]) {
        details.append(el("dt", "", label), el("dd", "", proposal[key]?.trim() || "Не указано"));
      }
      const link = el("dd"); link.append(externalLink(proposal.prototype_url, "Открыть прототип ↗", "Прототип пока не представлен"));
      details.append(el("dt", "", "Прототип"), link);
      const actions = el("div", "business-actions");
      for (const [value, label] of proposal.status === "submitted" ? [["selected", "Выбрать команду"], ["rejected", "Отклонить"]] : []) {
        const action = button(label, `button ${value === "selected" ? "button-primary" : "button-outline"}`, () => decide(proposal, value));
        action.dataset.decision = value;
        action.dataset.unavailable = String(!capabilities.decision);
        actions.append(action);
      }
      card.append(header, details, actions);
      if (proposal.status !== "submitted") card.append(el("p", "field-hint", "Решение принято. Изменение решения в этой версии не предусмотрено."));
      if (!capabilities.decision) card.append(el("p", "field-hint", "Решения по предложениям пока недоступны. Список получен с сервера."));
      if (proposal.status === "selected" || proposal.milestones.length) {
        const stages = el("section", "business-milestones");
        stages.append(el("h4", "", "Результаты этапов"));
        if (!proposal.milestones.length) stages.append(el("p", "field-hint", "Команда ещё не отправила результат этапа. Нажмите «Обновить», чтобы проверить новые результаты."));
        for (const milestone of proposal.milestones) {
          const stage = el("div", "business-milestone"); stage.dataset.milestoneId = milestone.id;
          stage.append(el("span", `badge ${milestone.status === "confirmed" ? "badge-mint" : "badge-yellow"}`, milestone.status === "confirmed" ? "Этап подтверждён" : "Ожидает проверки"),
            el("p", "", milestone.description), externalLink(milestone.result_url, "Открыть результат ↗", "Ссылка не представлена; результат описан текстом."));
          if (milestone.status === "confirmed") stage.append(el("p", "business-milestone-points", `Начислено за этап: ${milestone.points_awarded} баллов`));
          else {
            stage.append(el("p", "field-hint", "Проверьте результат перед подтверждением. Баллы команде начислит сервер."));
            const confirm = button("Подтвердить этап", "button button-primary", () => confirmMilestone(proposal, milestone));
            confirm.dataset.confirmMilestone = milestone.id;
            confirm.dataset.unavailable = String(!capabilities.confirm || proposal.status !== "selected");
            stage.append(confirm);
            if (!capabilities.confirm) stage.append(el("p", "field-hint", "Подтверждение этапов пока недоступно."));
          }
          stages.append(stage);
        }
        card.append(stages);
      }
      container.append(card);
    }
  }

  async function loadWorkspace(chosenProfile) {
    if (mutating || !showRole()) return;
    const { revision, signal } = beginLoad();
    $("business-layout").hidden = true; $("business-empty").hidden = true; $("business-totals").hidden = true;
    status("Загружаем ваши задачи…");
    try {
      await window.SanaBuilder.initialized;
      const profiles = await api.profiles(signal);
      if (!Array.isArray(profiles.businesses) || !Array.isArray(profiles.teams)) throw new Error("Не удалось прочитать демонстрационные профили.");
      if (revision !== epoch) return;
      teams = new Map(profiles.teams.map((team) => [team.id, team]));
      const preferred = chosenProfile || window.SanaBuilder.context().businessId || profile;
      profile = profiles.businesses.find((item) => item.id === preferred)?.id || profiles.businesses[0]?.id || "";
      $("business-profile").replaceChildren(...profiles.businesses.map((business) => { const option = el("option", "", business.name); option.value = business.id; return option; }));
      $("business-profile").value = profile;
      if (!profile) throw new Error("Демонстрационные профили ещё не подготовлены.");
      const [records, available] = await Promise.all([api.tasks(profile, signal), api.capabilities(signal)]);
      if (revision !== epoch) return;
      if (!Array.isArray(records) || records.some((item) => !item?.id || item.business_id !== profile || !item.proposed_card)) throw new Error("Не удалось прочитать задачи выбранного бизнеса.");
      tasks = records; capabilities = available;
      const visible = visibleTasks();
      selectedTask = visible.find((task) => task.id === selectedTask?.id) || visible[0] || null;
      compared.clear(); proposals = [];
      renderTasks(); renderTaskDetail(); renderProposals(); lock();
      const received = selectedTask && capabilities.proposals ? await api.proposals(selectedTask.id, profile, signal) : [];
      if (revision !== epoch) return;
      proposals = received;
      status(capabilities.proposals ? "Данные получены с сервера. Выбор команд остаётся за вами." : "Задачи получены с сервера. Отклики и результаты этапов ожидают подключения.");
    } catch (error) { if (revision === epoch && error.name !== "AbortError") { mustRefresh = true; fail(error); status("Не удалось обновить данные."); } }
    finally { if (revision === epoch) { loading = false; renderProposals(); lock(); } }
  }

  async function selectTask(task) {
    if (mutating || loading) return;
    const { revision, signal } = beginLoad();
    selectedTask = task; proposals = []; compared.clear();
    renderTasks(); renderTaskDetail(); renderProposals(); lock();
    status("Загружаем предложения выбранной задачи…");
    try {
      const received = capabilities.proposals ? await api.proposals(task.id, profile, signal) : [];
      if (revision !== epoch) return;
      proposals = received;
      if (revision === epoch) status(capabilities.proposals ? "Предложения получены с сервера." : "Отклики ещё не подключены. Задачу можно редактировать в конструкторе.");
    } catch (error) { if (revision === epoch && error.name !== "AbortError") { mustRefresh = true; fail(error); } }
    finally { if (revision === epoch) { loading = false; renderProposals(); lock(); } }
  }
  async function mutate(action) {
    if (mutating || loading || mustRefresh) return;
    mutating = true; $("business-error").hidden = true; lock();
    status("Ждём подтверждения сервера…");
    try { await action(); }
    catch (error) { mustRefresh = true; fail(error); status("Ответ сервера не подтверждён. Обновите данные перед следующим действием."); }
    finally { mutating = false; renderProposals(); lock(); }
  }
  function decide(item, decision) {
    if (!capabilities.decision || item.status !== "submitted") return;
    mutate(async () => {
      const result = await api.decide(item, decision, profile);
      proposals = proposals.map((current) => current.id === result.id ? result : current);
      status(`${teamName(result)}: ${statuses[result.status]}. Решения по остальным командам принимаются отдельно.`);
    });
  }
  function confirmMilestone(proposal, milestone) {
    if (!capabilities.confirm || proposal.status !== "selected" || milestone.status !== "submitted") return;
    mutate(async () => {
      const result = await api.confirm(milestone, profile, capabilities.confirmBody);
      proposals = proposals.map((item) => item.id === proposal.id
        ? { ...item, milestones: item.milestones.map((stage) => stage.id === result.id ? result : stage) } : item);
      status(result.status === "confirmed" ? `Этап подтверждён. Начислено за этот этап: ${result.points_awarded} баллов. Рейтинг задачи не изменён.` : "Сервер вернул этап на проверку. Баллы не подтверждены.");
    });
  }
  async function openEditor(taskId = "") {
    if (mutating || loading) return;
    loading = true; lock();
    try {
      if (!await window.SanaBuilder.open(profile || window.SanaBuilder.context().businessId, taskId)) throw new Error("Не удалось открыть конструктор. Дождитесь завершения текущего запроса и повторите.");
    } catch (error) { fail(error); }
    finally { loading = false; lock(); }
  }

  function compare() {
    const chosen = proposals.filter((item) => compared.has(item.id));
    if (chosen.length < 2) return;
    const table = el("table");
    table.append(el("caption", "", "Сравните идею, план и срок. Порядок предложений не является рейтингом команд."));
    const head = el("thead"); const headings = el("tr"); headings.append(el("th", "", "Предложение"));
    for (const item of chosen) { const cell = el("th", "", teamName(item)); cell.scope = "col"; headings.append(cell); }
    head.append(headings); table.append(head);
    const body = el("tbody");
    for (const [key, label] of [["status", "Статус"], ["idea", "Идея решения"], ["plan", "План"], ["timeline", "Срок"], ["prototype_url", "Прототип"], ["questions", "Вопросы бизнесу"]]) {
      const row = el("tr"); const heading = el("th", "", label); heading.scope = "row"; row.append(heading);
      for (const item of chosen) {
        const cell = el("td");
        if (key === "prototype_url") cell.append(externalLink(item[key], "Открыть прототип ↗", "Прототип пока не представлен"));
        else cell.textContent = key === "status" ? statuses[item.status] : item[key] || "Не указано";
        row.append(cell);
      }
      body.append(row);
    }
    table.append(body); $("business-comparison-content").replaceChildren(table); $("business-comparison").showModal();
  }
  $("business-compare").addEventListener("click", compare);
  $("business-comparison-close").addEventListener("click", () => $("business-comparison").close());
  $("business-refresh").addEventListener("click", () => loadWorkspace(profile));
  $("business-error-retry").addEventListener("click", () => loadWorkspace(profile));
  $("business-filter").addEventListener("change", () => {
    const visible = visibleTasks();
    if (visible.length) selectTask(visible.find((task) => task.id === selectedTask?.id) || visible[0]);
    else { controller?.abort(); epoch += 1; loading = false; selectedTask = null; renderTasks(); lock(); }
  });
  $("business-profile").addEventListener("change", async (event) => {
    const chosen = event.target.value;
    if (mutating) return;
    loading = true; lock();
    try {
      if (!await window.SanaBuilder.setBusiness(chosen)) throw new Error("Не удалось переключить бизнес. Повторите после завершения запроса конструктора.");
      await loadWorkspace(chosen);
    } catch (error) { fail(error); $("business-profile").value = profile; loading = false; lock(); }
  });
  for (const id of ["business-create", "business-empty-create"]) $(id).addEventListener("click", () => openEditor());
  $("business-switch-role").addEventListener("click", () => { $("demo-profile").value = "business"; $("demo-profile").dispatchEvent(new Event("change")); });
  function enter() { if (window.location.hash === "#business" && showRole()) loadWorkspace(); }
  window.addEventListener("hashchange", enter);
  window.addEventListener("sana:demo-role-change", () => { showRole(); enter(); });
  showRole(); enter();
})();
