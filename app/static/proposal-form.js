/* Team proposal form: isolated local drafts, explicit server submission. */
(() => {
  "use strict";
  const fields = [
    ["idea", "Идея решения", "Что предлагаете и чем это поможет бизнесу?", true],
    ["plan", "План работы", "Опишите основные шаги: от изучения данных до проверки результата.", true],
    ["timeline", "Сроки", "Например: прототип за две недели, проверка — ещё три дня.", true],
    ["prototype_url", "Ссылка на прототип", "https://github.com/your-team/project", false],
    ["questions", "Вопросы бизнесу", "Что нужно уточнить перед началом работы?", false],
  ];
  const blank = () => Object.fromEntries(fields.map(([key]) => [key, ""]));
  const memory = new Map();
  const teamPreference = "ai-sana:proposal-team";
  let host = null;
  let task = null;
  let teamId = "";
  let values = blank();
  let teams = null;
  let generation = 0;
  let storageBlocked = false;
  let controller = null;
  let checked = false;
  let lookupGeneration = 0;
  let sending = false;
  let ready = false;
  const api = window.SanaTeam;
  const get = id => host?.querySelector(`#proposal-${id}`);
  const draftKey = () => `ai-sana:proposal-draft:v1:${JSON.stringify([task.source, task.id, teamId])}`;

  function read(key) {
    if (memory.has(key)) return memory.get(key);
    try { return localStorage.getItem(key); }
    catch { storageBlocked = true; return null; }
  }
  function write(key, value) {
    memory.set(key, value);
    try { localStorage.setItem(key, value); storageBlocked = false; }
    catch { storageBlocked = true; }
    return !storageBlocked;
  }
  function storageNotice() {
    if (get("storage-warning")) get("storage-warning").hidden = !storageBlocked;
  }
  function text(tag, value, className = "") {
    const el = document.createElement(tag);
    el.textContent = value;
    el.className = className;
    return el;
  }
  function remember() {
    if (!host || !task || !teamId) return false;
    const saved = write(draftKey(), JSON.stringify({ version: 1, source: task.source,
      task_id: task.id, team_id: teamId, values, updated_at: new Date().toISOString() }));
    storageNotice();
    get("save-status").textContent = saved
      ? "Черновик сохранён на этом устройстве. Бизнес его ещё не видит."
      : "Черновик сохранён в памяти вкладки. Не закрывайте её — постоянное хранилище недоступно.";
    return saved;
  }
  function restore() {
    values = blank();
    let restored = false;
    try {
      const saved = JSON.parse(read(draftKey()) || "null");
      if (saved?.version === 1 && saved.task_id === task.id && saved.team_id === teamId
        && saved.source === task.source && fields.every(([key]) => typeof saved.values?.[key] === "string")) {
        values = { ...saved.values };
        restored = true;
      }
    } catch { /* Invalid browser data is not treated as a submitted proposal. */ }
    fields.forEach(([key]) => { get(key).value = values[key]; });
    checked = false;
    get("review").hidden = true;
    clearErrors();
    get("save-status").textContent = restored
      ? "Восстановлен ваш черновик для этой команды и задачи."
      : "Черновик сохраняется автоматически по мере заполнения.";
    storageNotice();
    const team = teams.find(item => item.id === teamId);
    get("team-info").textContent = team?.skills?.filter(item => typeof item === "string").join(" · ") || "Демонстрационный профиль команды";
    updateCompletion();
  }
  function validate() {
    const errors = {};
    fields.forEach(([key, label, , required]) => {
      if (required && !values[key].trim()) errors[key] = `Заполните поле «${label}».`;
      if (values[key].length > 20000) errors[key] = "Сократите текст до 20 000 символов.";
    });
    if (values.prototype_url.trim()) {
      try {
        const url = new URL(values.prototype_url.trim());
        if (!["https:", "http:"].includes(url.protocol) || !url.hostname || url.username || url.password) throw new Error();
      } catch { errors.prototype_url = "Введите полный адрес с https:// или http://, без логина и пароля в ссылке."; }
    }
    return errors;
  }
  function clearErrors() {
    fields.forEach(([key]) => {
      get(key).removeAttribute("aria-invalid");
      get(`${key}-error`).textContent = "";
      get(`${key}-error`).hidden = true;
    });
  }
  function showErrors(errors) {
    clearErrors();
    for (const [key, message] of Object.entries(errors)) {
      get(key).setAttribute("aria-invalid", "true");
      get(`${key}-error`).textContent = message;
      get(`${key}-error`).hidden = false;
    }
  }
  function updateCompletion() {
    const complete = fields.filter(([key, , , required]) => required && values[key].trim()).length;
    get("completion").textContent = `Заполнено ${complete} из 3 основных полей`;
  }
  function review() {
    remember();
    checked = true;
    const errors = validate();
    showErrors(errors);
    get("review").hidden = false;
    const failed = Object.keys(errors);
    get("review").classList.toggle("proposal-review-error", Boolean(failed.length));
    if (failed.length) {
      get("review").textContent = "Проверьте отмеченные поля. Ваш черновик остаётся сохранённым.";
      get(failed[0]).focus();
    } else {
      get("review").textContent = "Основные поля заполнены, формат ссылки подходит. Нажмите «Отправить отклик», когда будете готовы.";
    }
  }
  function showRole() {
    if (!host) return;
    const isTeam = document.documentElement.dataset.demoRole === "team";
    get("role-notice").hidden = isTeam;
    get("workspace").hidden = !isTeam;
    if (teamId && !sending) checkExisting();
  }
  function showExisting(proposal) {
    get("form").hidden = get("footer").hidden = get("save-status").hidden = true;
    get("review").hidden = true;
    const box = get("existing");
    const link = text("a", "Посмотреть в моих откликах →", "button button-outline");
    link.href = `#proposals/${encodeURIComponent(proposal.id)}`;
    box.replaceChildren(text("h3", api.statuses[proposal.status]),
      text("p", "Ваш отклик сохранён на сервере. Бизнес принимает решение о сотрудничестве. Повторно отправлять его не нужно."), link);
    box.hidden = false;
    get("badge").textContent = "Отклик отправлен";
  }
  async function checkExisting() {
    const current = ++lookupGeneration;
    const owner = host;
    const selectedTeam = teamId;
    const selectedTask = task?.id;
    ready = false;
    get("send").disabled = true;
    get("existing").hidden = true;
    get("form").hidden = get("footer").hidden = get("save-status").hidden = false;
    get("badge").textContent = "Черновик отклика";
    if (!api.isTeam() || !selectedTeam) return;
    get("send-note").textContent = "Проверяем, отправляла ли команда отклик…";
    try {
      const own = api.proposals(await api.request("/api/my/proposals", { teamId: selectedTeam }));
      if (host !== owner || current !== lookupGeneration || teamId !== selectedTeam) return;
      if (own.some(p => p.team_id !== selectedTeam)) throw new Error("Ответ сервера не соответствует выбранной команде.");
      const existing = own.find(p => p.task_id === selectedTask);
      if (existing) showExisting(existing);
      else {
        ready = true;
        get("send").disabled = false;
        get("send-note").textContent = "Один отклик от команды на задачу. После отправки изменить его нельзя. Решение принимает бизнес.";
      }
    } catch (error) {
      if (host !== owner || current !== lookupGeneration) return;
      get("load-message").textContent = `${error.message} Черновик доступен, но отправка заблокирована до проверки откликов.`;
      get("load-error").hidden = false;
      get("send-note").textContent = "Нажмите «Повторить», чтобы проверить соединение. Введённый текст сохранён.";
    }
  }
  async function send() {
    if (!ready || sending || !api.isTeam() || task.source !== "public") return;
    review();
    if (Object.keys(validate()).length) return;
    const owner = host;
    const selectedTeam = teamId;
    const selectedTask = task.id;
    const current = generation;
    const body = Object.fromEntries(fields.map(([key]) => [key, values[key].trim()]));
    body.prototype_url ||= null;
    sending = true;
    get("fields").disabled = get("team").disabled = get("send").disabled = true;
    get("send").textContent = "Отправляем…";
    get("review").textContent = "Сохраняем отклик на сервере…";
    try {
      const result = await api.mutate(`/api/tasks/${encodeURIComponent(selectedTask)}/proposals`, selectedTeam, body);
      api.proposals([result]);
      if (result.task_id !== selectedTask || result.team_id !== selectedTeam) throw new Error("Ответ сервера не соответствует вашему отклику.");
      if (owner !== host || generation !== current) return;
      showExisting(result);
    } catch (error) {
      if (owner !== host || generation !== current) return;
      get("review").classList.add("proposal-review-error");
      get("review").textContent = `${error.message} Ваш черновик сохранён. Если ответ потерялся, повторная отправка того же отклика не создаст дубликат.`;
      if (error.status === 409) await checkExisting();
    } finally {
      if (owner === host && generation === current) {
        sending = false;
        get("fields").disabled = get("team").disabled = false;
        get("send").disabled = !ready;
        get("send").textContent = "Отправить отклик";
      }
    }
  }
  async function loadTeams() {
    const current = ++generation;
    const owner = host;
    controller?.abort();
    get("load-error").hidden = true;
    get("fields").disabled = true;
    get("team").disabled = true;
    get("team").replaceChildren(new Option("Загрузка команд…", ""));
    const request = new AbortController();
    controller = request;
    const timeout = setTimeout(() => request.abort(), 12000);
    try {
      if (!teams) {
        const response = await fetch("/api/demo/profiles", { signal: request.signal });
        if (!response.ok) throw new Error();
        const data = await response.json();
        if (!Array.isArray(data.teams) || !data.teams.every(item => typeof item.id === "string"
          && item.id && typeof item.name === "string" && (!item.skills || Array.isArray(item.skills)))) throw new Error();
        if (current !== generation || host !== owner) return;
        teams = data.teams;
      }
      if (current !== generation || host !== owner) return;
      if (!teams.length) {
        teams = null;
        get("load-message").textContent = "Профили команд ещё не добавлены. После подготовки демонстрационных данных нажмите «Повторить».";
        get("load-error").hidden = false;
        get("team").replaceChildren(new Option("Команд пока нет", ""));
        return;
      }
      const preferred = api.read(teamPreference);
      teamId = teams.some(item => item.id === preferred) ? preferred : teams[0].id;
      get("team").replaceChildren(...teams.map(item => new Option(item.name, item.id)));
      get("team").value = teamId;
      get("team").disabled = false;
      get("fields").disabled = false;
      restore();
      checkExisting();
    } catch {
      if (current !== generation || host !== owner) return;
      get("load-message").textContent = "Не удалось загрузить команды. Проверьте соединение и повторите попытку.";
      get("load-error").hidden = false;
      get("team").replaceChildren(new Option("Команды недоступны", ""));
    } finally { clearTimeout(timeout); }
  }
  function unmount() {
    ++generation;
    ++lookupGeneration;
    sending = ready = false;
    controller?.abort();
    host?.replaceChildren();
    host = task = null;
    teamId = "";
  }
  function mount(container, currentTask) {
    unmount();
    host = container;
    task = currentTask;
    values = blank();
    // Static markup only; user text is always assigned via textContent/value.
    host.innerHTML = `
      <section class="panel proposal-panel" aria-labelledby="proposal-title">
        <header class="proposal-heading"><div><p class="eyebrow">ОТ ИДЕИ К СОТРУДНИЧЕСТВУ</p><h2 id="proposal-title" tabindex="-1">Предложите свой подход</h2><p>Не нужно готовое решение. Начните с идеи и понятного плана.</p></div><span id="proposal-badge" class="badge badge-mint">Черновик отклика</span></header>
        <div id="proposal-role-notice" class="proposal-role-note" hidden><p>Отклик готовится от имени студенческой команды. Черновики бизнеса останутся на месте.</p><button id="proposal-switch-role" class="button button-outline" type="button">Перейти к роли команды</button></div>
        <div id="proposal-workspace">
          <div class="proposal-demo-note">Выберите демонстрационную команду. Сохранённый черновик виден только в этом браузере; отправленный отклик появится у бизнеса.</div>
          <div id="proposal-load-error" class="proposal-load-error" role="alert" hidden><p id="proposal-load-message"></p><button id="proposal-retry" class="button button-outline" type="button">Повторить</button></div>
          <div class="proposal-team-row"><div class="form-field"><label for="proposal-team">Ваша команда</label><select id="proposal-team" class="field-control" disabled><option>Загрузка команд…</option></select></div><p id="proposal-team-info"></p></div>
          <p id="proposal-storage-warning" class="proposal-storage-warning" role="status" hidden>Хранилище браузера недоступно. Черновик останется только в памяти этой вкладки до её закрытия или перезагрузки.</p>
          <div id="proposal-existing" class="proposal-review" role="status" hidden></div>
          <form id="proposal-form" novalidate><fieldset id="proposal-fields" disabled><legend class="sr-only">Черновик предложения команды</legend><div id="proposal-inputs" class="proposal-inputs"></div>
            <div class="proposal-actions"><button class="button button-primary" type="submit">Сохранить черновик</button><button id="proposal-check" class="button button-outline" type="button">Проверить отклик</button></div>
          </fieldset></form>
          <p id="proposal-save-status" class="proposal-save-status" role="status" aria-live="polite"></p>
          <p id="proposal-review" class="proposal-review" role="status" hidden></p>
          <footer id="proposal-footer" class="proposal-footer"><span id="proposal-completion"></span><button id="proposal-send" class="button button-primary" type="button" disabled aria-describedby="proposal-send-note">Отправить отклик</button><p id="proposal-send-note"></p></footer>
        </div>
      </section>`;
    for (const [key, label, hint, required] of fields) {
      const wrapper = text("div", "", `form-field proposal-field proposal-field-${key}`);
      const caption = text("label", label);
      caption.htmlFor = `proposal-${key}`;
      caption.append(text("span", required ? "Обязательно" : "Необязательно", "proposal-optional"));
      const input = document.createElement(key === "prototype_url" || key === "timeline" ? "input" : "textarea");
      input.id = `proposal-${key}`;
      input.name = key;
      input.className = "field-control";
      input.maxLength = 20000;
      input.required = required;
      input.placeholder = hint;
      if (key === "prototype_url") { input.type = "url"; input.autocomplete = "off"; }
      if (input.tagName === "TEXTAREA") input.rows = key === "questions" ? 3 : 4;
      const help = text("p", key === "prototype_url" ? "Нет прототипа? Оставьте поле пустым — для отклика достаточно идеи." : hint, "proposal-field-hint");
      help.id = `proposal-${key}-hint`;
      const error = text("p", "", "field-error");
      error.id = `proposal-${key}-error`;
      error.hidden = true;
      input.setAttribute("aria-describedby", `${help.id} ${error.id}`);
      input.addEventListener("input", () => {
        values[key] = input.value;
        remember();
        updateCompletion();
        get("review").hidden = true;
        if (checked) showErrors(validate());
      });
      wrapper.append(caption, help, input, error);
      get("inputs").append(wrapper);
    }
    get("team").addEventListener("change", event => {
      teamId = event.target.value;
      write(teamPreference, teamId);
      api.write(teamPreference, teamId);
      restore();
      checkExisting();
    });
    get("form").addEventListener("submit", event => { event.preventDefault(); remember(); });
    get("check").addEventListener("click", review);
    get("send").addEventListener("click", send);
    get("retry").addEventListener("click", loadTeams);
    get("switch-role").addEventListener("click", () => {
      const role = document.querySelector("#demo-profile");
      role.value = "team";
      role.dispatchEvent(new Event("change", { bubbles: true }));
    });
    showRole();
    loadTeams();
  }
  window.addEventListener("sana:demo-role-change", showRole);
  window.SanaProposalForm = Object.freeze({ mount, unmount });
})();
