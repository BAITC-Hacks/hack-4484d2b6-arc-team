/* Read-only progress from server ratings and confirmed milestones. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const node = (tag, text, className = "") => {
    const item = document.createElement(tag);
    item.textContent = text;
    item.className = className;
    return item;
  };
  let nextField = null;
  window.SanaGamification = {
    renderMissions(rating, pending) {
      $("builder-missions").hidden = !rating;
      if (!rating) return;
      const completed = rating.categories.filter((item) => item.points === item.maximum).length;
      $("mission-progress").textContent = `Подтверждено шагов: ${completed} из ${rating.categories.length}`;
      // Weight and completion come from the server, never from form values.
      const missing = rating.categories.flatMap((item) => item.fields)
        .filter((item) => item.points < item.maximum)
        .sort((a, b) => (b.maximum - b.points) - (a.maximum - a.points));
      const next = missing[0];
      nextField = next?.field;
      $("mission-action").hidden = !next;
      $("mission-next").textContent = next
        ? `Следующий шаг: ${next.label}. Можно получить +${next.maximum - next.points} баллов после заполнения и подтверждения.${pending ? " Если поле уже исправлено, подтвердите правки." : ""}`
        : "Все семь шагов подтверждены. Карточка содержит сведения по каждой категории!";
    },
  };
  $("mission-action").addEventListener("click", () => {
    // Reuse the editor's existing field navigation and busy guard.
    [...document.querySelectorAll("[data-missing-field]")]
      .find((button) => button.dataset.missingField === nextField)?.click();
  });

  let teams = [];
  let loading = false;
  function showAchievements() {
    const team = teams.find((item) => item.team_id === $("achievement-team").value);
    $("achievement-cards").replaceChildren();
    for (const award of team?.achievements || []) {
      const card = node("article", "", `achievement-card${award.earned ? " is-earned" : ""}`);
      const status = node("p", award.earned ? "✓ Получено" : "Впереди", "achievement-status");
      const progress = document.createElement("progress");
      progress.max = award.target;
      progress.value = award.progress;
      progress.setAttribute("aria-label", award.title);
      card.append(status, node("h3", award.title), node("p", award.description), progress,
        node("p", `${award.progress} из ${award.target}`, "field-hint"));
      $("achievement-cards").append(card);
    }
  }
  async function loadLeaderboard() {
    if (loading) return;
    loading = true;
    $("leaderboard-refresh").disabled = true;
    $("leaderboard-content").hidden = true;
    $("leaderboard-status").textContent = "Загружаем подтверждённые результаты…";
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch("/api/leaderboard", { signal: controller.signal, cache: "no-store" });
      if (!response.ok) throw new Error("Не удалось загрузить рейтинг.");
      teams = await response.json();
      if (!Array.isArray(teams)) throw new Error("Неожиданный ответ сервера.");
      const selected = $("achievement-team").value;
      $("leaderboard-rows").replaceChildren();
      $("achievement-team").replaceChildren();
      for (const team of teams) {
        const row = document.createElement("tr");
        if (team.rank === 1 && team.completed_tasks > 0) row.className = "is-leader";
        row.append(node("td", team.rank));
        const name = node("th", team.name);
        name.scope = "row";
        row.append(name, node("td", team.completed_tasks), node("td", team.confirmed_milestones), node("td", team.points));
        $("leaderboard-rows").append(row);
        const option = node("option", team.name);
        option.value = team.team_id;
        $("achievement-team").append(option);
      }
      if (teams.some((team) => team.team_id === selected)) $("achievement-team").value = selected;
      showAchievements();
      $("leaderboard-content").hidden = !teams.length;
      $("leaderboard-status").textContent = !teams.length ? "Команды пока не добавлены."
        : teams.every((team) => team.completed_tasks === 0)
          ? "Пока нет подтверждённых результатов. Первый этап откроет первое достижение!"
          : "Результаты обновлены. Выберите команду, чтобы увидеть её достижения.";
    } catch (error) {
      $("leaderboard-status").textContent = "Не удалось загрузить рейтинг. Проверьте соединение и нажмите «Обновить».";
    } finally {
      clearTimeout(timer);
      loading = false;
      $("leaderboard-refresh").disabled = false;
    }
  }
  $("achievement-team").addEventListener("change", showAchievements);
  $("leaderboard-refresh").addEventListener("click", loadLeaderboard);
  const onRoute = () => { if (location.hash.split("/")[0] === "#leaderboard") loadLeaderboard(); };
  window.addEventListener("hashchange", onRoute);
  onRoute();
})();
