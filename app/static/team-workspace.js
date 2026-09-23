/* Participant 3: own proposals, selected-team results and server-confirmed points. */
(() => {
  "use strict";
  const page = document.querySelector("#page-proposals");
  if (!page) return;
  const api = window.SanaTeam;
  const get = id => page.querySelector(`#team-${id}`);
  let generation = 0;
  let controller;
  let teamId = "";
  let offers = [];
  let busy = false;
  let filter = "";
  const active = () => location.hash.split("/")[0] === "#proposals";
  page.innerHTML = `
    <div class="page-heading"><div><p class="eyebrow">ОТ ИДЕИ К ПЕРВОМУ РЕЗУЛЬТАТУ</p><h1 id="proposals-title">Мои отклики</h1><p class="subtitle">Следите за решениями бизнеса и делитесь прогрессом команды.</p></div><a class="button button-outline" href="#catalog">Найти задачу ↗</a></div>
    <div id="team-role" class="panel empty-state" hidden><h2>Рабочее место команды</h2><p>Переключитесь на демонстрационную роль команды, чтобы увидеть её отклики.</p><button id="team-switch" type="button" class="button button-primary">Перейти к роли команды</button></div>
    <div id="team-content">
      <div class="team-toolbar panel"><div class="form-field"><label for="team-profile">Ваша команда</label><select id="team-profile" class="field-control" disabled><option>Загрузка команд…</option></select></div><div class="team-points"><span>Подтверждённые баллы</span><strong id="team-points">—</strong><small>За принятые бизнесом этапы</small></div><button id="team-refresh" class="button button-outline" type="button">Обновить</button></div>
      <p id="team-notice" class="team-notice" role="status" hidden></p>
      <p id="team-loading" role="status" hidden>Загружаем отклики команды…</p>
      <div id="team-error" class="panel team-error" role="alert" hidden><h2>Не удалось загрузить отклики</h2><p id="team-error-text"></p><button id="team-retry" class="button button-outline" type="button">Повторить загрузку</button></div>
      <div id="team-work" hidden><div class="team-filter-row"><p id="team-summary" role="status"></p><label for="team-filter">Статус</label><select id="team-filter" class="field-control"><option value="">Все отклики</option><option value="submitted">Ожидают решения</option><option value="selected">Команда выбрана</option><option value="rejected">Не выбраны</option></select></div>
        <div id="team-empty" class="panel empty-state" hidden><h2 id="team-empty-title"></h2><p id="team-empty-text"></p><a class="button button-outline" href="#catalog">Посмотреть задачи →</a></div>
        <div id="team-columns" class="team-columns"><div id="team-list" class="team-list" aria-label="Отклики команды"></div><article id="team-detail" class="panel team-detail" aria-labelledby="team-detail-title"></article></div>
      </div>
    </div><footer class="page-footer"><span>Демонстрационные профили · без авторизации</span><span>Решения принимает бизнес. Баллы подтверждает сервер.</span></footer>`;

  function notice(message) { get("notice").textContent = message; get("notice").hidden = !message; }
  function readDraft(key) {
    try {
      const value = JSON.parse(api.read(key));
      if (value && typeof value.description === "string" && typeof value.result_url === "string") {
        if (value.pending && (typeof value.pending.description !== "string"
          || (value.pending.result_url !== null && typeof value.pending.result_url !== "string"))) value.pending = null;
        return value;
      }
    } catch { /* Invalid local data is never submitted. */ }
    return { description: "", result_url: "", pending: null };
  }
  function resultLink(url, caption) {
    const href = api.safeUrl(url);
    if (!href) return api.text("span", "Ссылка не указана или имеет неподдерживаемый формат", "team-muted");
    const link = api.text("a", caption, "team-link");
    link.href = href; link.target = "_blank"; link.rel = "noopener noreferrer";
    return link;
  }
  function stageList(proposal) {
    const section = api.text("section", "", "team-stages");
    section.append(api.text("h3", "Результаты этапов"));
    if (!proposal.milestones.length) section.append(api.text("p", "Пока нет отправленных результатов. Начните с первого небольшого этапа.", "team-muted"));
    proposal.milestones.forEach((stage, index) => {
      const card = api.text("div", "", "team-stage");
      const head = api.text("div", "", "team-stage-heading");
      const confirmed = stage.status === "confirmed";
      head.append(api.text("strong", `Этап ${index + 1}`), api.text("span", confirmed
        ? `Подтверждён · +${stage.points_awarded} баллов` : "На проверке · 0 баллов", `badge ${confirmed ? "badge-mint" : "badge-yellow"}`));
      card.append(head, api.text("p", stage.description, "team-text"));
      if (stage.result_url) card.append(resultLink(stage.result_url, "Открыть результат ↗"));
      card.append(api.text("small", confirmed ? `Подтверждён ${api.date(stage.confirmed_at)}` : `Отправлен ${api.date(stage.created_at)}`, "team-muted"));
      section.append(card);
    });
    return section;
  }
  function resultForm(proposal) {
    const key = `ai-sana:milestone-draft:v1:${JSON.stringify([teamId, proposal.id])}`;
    let draft = readDraft(key);
    if (draft.pending && proposal.milestones.some(m => m.description.trim() === draft.pending.description
      && (api.safeUrl(m.result_url) || null) === (api.safeUrl(draft.pending.result_url) || null))) {
      draft = { description: "", result_url: "", pending: null };
      api.write(key, JSON.stringify(draft));
    }
    const form = document.createElement("form");
    form.className = "team-result-form"; form.noValidate = true;
    form.innerHTML = `<h3>Поделиться результатом</h3><p class="team-muted">Опишите сделанный этап. Баллы появятся после подтверждения бизнесом.</p>
      <div class="form-field"><label for="team-result-description">Что сделали</label><textarea id="team-result-description" class="field-control" rows="5" maxlength="20000" required aria-describedby="team-result-feedback" placeholder="Что готово, как это проверить и какой результат получили?"></textarea></div>
      <div class="form-field"><label for="team-result-url">Ссылка на результат <span class="team-muted">необязательно</span></label><input id="team-result-url" class="field-control" type="url" maxlength="20000" aria-describedby="team-result-feedback" placeholder="https://github.com/your-team/project"></div>
      <p id="team-result-storage" class="team-muted" role="status"></p><p id="team-result-feedback" role="status" class="team-notice" hidden></p>
      <button id="team-result-send" class="button button-primary" type="submit">Отправить результат</button>`;
    const description = form.querySelector("textarea");
    const url = form.querySelector("input");
    const feedback = form.querySelector("#team-result-feedback");
    const submit = form.querySelector("button");
    const storage = form.querySelector("#team-result-storage");
    description.value = draft.description; url.value = draft.result_url;
    function save() {
      storage.textContent = api.write(key, JSON.stringify(draft)) ? "Черновик результата сохранён на этом устройстве."
        : "Хранилище недоступно. Черновик остаётся в памяти вкладки — не закрывайте её.";
    }
    function pendingState() {
      description.disabled = url.disabled = Boolean(draft.pending);
      submit.textContent = draft.pending ? "Повторить отправку результата" : "Отправить результат";
      if (draft.pending) {
        feedback.hidden = false;
        feedback.textContent = "Предыдущая отправка ещё не подтверждена. Обновите отклики или повторите тот же запрос: сервер не создаст дубликат.";
      }
    }
    pendingState();
    form.addEventListener("input", () => {
      draft.description = description.value; draft.result_url = url.value;
      description.removeAttribute("aria-invalid"); url.removeAttribute("aria-invalid");
      feedback.hidden = true; save();
    });
    form.addEventListener("submit", async event => {
      event.preventDefault();
      if (busy || !api.isTeam()) return;
      const body = draft.pending || { description: description.value.trim(), result_url: url.value.trim() || null };
      const invalid = !body.description || body.description.length > 20000;
      if (invalid || (body.result_url && !api.safeUrl(body.result_url))) {
        feedback.hidden = false;
        feedback.textContent = invalid ? "Опишите результат этапа (до 20 000 символов)." : "Нужна полная ссылка с https:// или http://, без логина и пароля.";
        const field = invalid ? description : url;
        field.setAttribute("aria-invalid", "true"); field.focus(); return;
      }
      const owner = generation;
      const selectedTeam = teamId;
      draft.pending = body; save(); pendingState();
      busy = true;
      get("profile").disabled = get("filter").disabled = get("refresh").disabled = submit.disabled = true;
      feedback.hidden = false; feedback.textContent = "Отправляем результат…";
      try {
        const result = await api.mutate(`/api/proposals/${encodeURIComponent(proposal.id)}/milestones`, selectedTeam, body);
        if (!result?.id || result.proposal_id !== proposal.id || !["submitted", "confirmed"].includes(result.status)) throw new Error("Не удалось прочитать подтверждение сервера.");
        draft = { description: "", result_url: "", pending: null };
        api.write(key, JSON.stringify(draft));
        if (owner === generation && active() && api.isTeam()) {
          busy = false;
          await load(selectedTeam);
          notice("Результат сохранён на сервере. Бизнес увидит его и сможет подтвердить этап.");
        }
      } catch (error) {
        if (error.status >= 400 && error.status < 500) { draft.pending = null; api.write(key, JSON.stringify(draft)); }
        if (owner !== generation) return;
        pendingState();
        feedback.hidden = false;
        feedback.textContent = `${error.message} Черновик сохранён.${draft.pending ? " Повторите тот же запрос или обновите отклики, чтобы проверить отправку." : ""}`;
      } finally {
        if (owner === generation) {
          busy = false;
          get("profile").disabled = get("filter").disabled = get("refresh").disabled = submit.disabled = false;
        }
      }
    });
    return form;
  }
  function detail(proposal) {
    const box = get("detail");
    const heading = api.text("h2", proposal.task_title); heading.id = "team-detail-title";
    const link = api.text("a", "Открыть задачу ↗", "team-link"); link.href = `#task/${encodeURIComponent(proposal.task_id)}`;
    box.replaceChildren(api.text("span", api.statuses[proposal.status], `badge ${proposal.status === "selected" ? "badge-mint" : "badge-yellow"}`), heading, link);
    const notes = { submitted: "Отклик у бизнеса. Можно вернуться позже или обновить страницу, чтобы узнать решение.",
      selected: "Бизнес выбрал вашу команду. Договоритесь о работе и отправляйте результаты этапов ниже.",
      rejected: "Бизнес не выбрал этот отклик. Вы можете предложить свой подход к другой задаче." };
    box.append(api.text("p", notes[proposal.status], "team-next"));
    const details = document.createElement("details"); details.className = "team-offer-text";
    details.append(api.text("summary", "Ваше предложение"));
    const fields = document.createElement("dl");
    for (const [key, label] of [["idea", "Идея"], ["plan", "План работы"], ["timeline", "Сроки"], ["questions", "Вопросы бизнесу"]]) {
      fields.append(api.text("dt", label), api.text("dd", proposal[key] || "Не указано", "team-text"));
    }
    details.append(fields);
    if (proposal.prototype_url) details.append(resultLink(proposal.prototype_url, "Открыть прототип ↗"));
    box.append(details);
    if (proposal.status === "selected" || proposal.milestones.length) box.append(stageList(proposal));
    if (proposal.status === "selected") box.append(resultForm(proposal));
  }
  function render() {
    get("summary").textContent = `${offers.length} откликов · ${offers.filter(p => p.status === "selected").length} в работе`;
    const visible = offers.filter(p => !filter || p.status === filter);
    get("empty").hidden = Boolean(visible.length);
    get("columns").hidden = !visible.length;
    if (!visible.length) {
      get("empty-title").textContent = offers.length ? "В этом статусе пока нет откликов" : "Начните с интересной задачи";
      get("empty-text").textContent = offers.length ? "Выберите другой статус или посмотрите новые задачи в каталоге."
        : "Найдите задачу и отправьте идею решения. Локальные черновики остаются в форме на странице соответствующей задачи.";
      get("list").replaceChildren(); get("detail").replaceChildren(); return;
    }
    let requested;
    try { requested = decodeURIComponent(location.hash.split("/")[1] || ""); } catch { requested = ""; }
    const selected = visible.find(p => p.id === requested) || visible[0];
    if (requested && !offers.some(p => p.id === requested)) notice("Этот отклик недоступен выбранной команде. Показаны её собственные отклики.");
    get("list").replaceChildren(...visible.map(proposal => {
      const button = document.createElement("button"); button.type = "button";
      button.className = "team-offer";
      button.setAttribute("aria-pressed", String(proposal.id === selected.id));
      button.append(api.text("span", api.statuses[proposal.status], `badge ${proposal.status === "selected" ? "badge-mint" : "badge-yellow"}`),
        api.text("strong", proposal.task_title), api.text("small", `Отправлен ${api.date(proposal.created_at)}`));
      button.addEventListener("click", () => { if (!busy) location.hash = `proposals/${encodeURIComponent(proposal.id)}`; });
      return button;
    }));
    detail(selected);
  }
  async function load(preferred) {
    const current = ++generation;
    controller?.abort(); controller = new AbortController();
    busy = false;
    if (!active()) return;
    get("role").hidden = api.isTeam(); get("content").hidden = !api.isTeam();
    if (!api.isTeam()) return;
    offers = [];
    get("work").hidden = get("error").hidden = true;
    get("points").textContent = "—";
    get("loading").hidden = false;
    get("profile").disabled = get("refresh").disabled = true;
    get("filter").disabled = false;
    notice("");
    try {
      const teams = api.teams(await api.request("/api/demo/profiles", { signal: controller.signal }));
      if (current !== generation) return;
      if (!teams.length) throw new Error("Профили команд пока не подготовлены. После добавления демонстрационных данных повторите загрузку.");
      const preference = preferred || api.read(api.preference);
      teamId = teams.some(t => t.id === preference) ? preference : teams[0].id;
      get("profile").replaceChildren(...teams.map(t => new Option(t.name, t.id)));
      get("profile").value = teamId;
      api.write(api.preference, teamId);
      const data = api.proposals(await api.request("/api/my/proposals", { teamId, signal: controller.signal }));
      if (current !== generation) return;
      if (data.some(p => p.team_id !== teamId)) throw new Error("Ответ сервера не соответствует выбранной команде.");
      offers = data;
      get("points").textContent = String(teams.find(t => t.id === teamId).points);
      get("work").hidden = false;
      render();
    } catch (error) {
      if (current !== generation) return;
      get("error-text").textContent = `${error.message} Сохранённые на устройстве черновики останутся на месте.`;
      get("error").hidden = false;
    } finally {
      if (current === generation) {
        get("loading").hidden = true;
        get("profile").disabled = !teamId;
        get("refresh").disabled = false;
      }
    }
  }
  get("switch").addEventListener("click", api.chooseTeam);
  get("profile").addEventListener("change", event => {
    filter = ""; get("filter").value = "";
    load(event.target.value);
  });
  get("filter").addEventListener("change", event => { if (!busy) { filter = event.target.value; render(); } });
  get("refresh").addEventListener("click", () => load(teamId));
  get("retry").addEventListener("click", () => load(teamId));
  window.addEventListener("hashchange", () => load());
  window.addEventListener("sana:demo-role-change", () => load());
  load();
})();
