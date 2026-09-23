/* Shell-only behavior: no API, challenge data, or client-side scoring. */
(() => {
  "use strict";

  const pageLabels = {
    builder: "Конструктор задачи",
    catalog: "Каталог задач",
    task: "Описание задачи",
    business: "Мои задачи",
    proposals: "Мои отклики",
    leaderboard: "Лидеры команд",
  };
  const profileSelect = document.querySelector("#demo-profile");
  const announcement = document.querySelector("#shell-announcement");
  const storageKey = "ai-sana:demo-role";

  function showPage(moveFocus = false) {
    const requested = window.location.hash.slice(1).split("/")[0];
    const page = Object.hasOwn(pageLabels, requested) ? requested : "builder";
    document.querySelectorAll(".page").forEach((section) => {
      section.hidden = section.id !== `page-${page}`;
    });
    document.querySelectorAll("[data-page]").forEach((link) => {
      if (link.dataset.page === (page === "task" ? "catalog" : page)) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    document.querySelector("#page-label").textContent = pageLabels[page];
    document.title = `${pageLabels[page]} · AI Sana Challenge Hub`;
    if (moveFocus) document.querySelector("#main-content").focus();
    if (page === "task") window.scrollTo(0, 0);
  }

  function applyDemoRole(announce = false) {
    const role = profileSelect.value;
    document.documentElement.dataset.demoRole = role;
    if (announce) {
      announcement.textContent = `Выбран демопрофиль: ${profileSelect.selectedOptions[0].textContent}. Это демонстрация без авторизации.`;
      // Local role intent only; server profile IDs and authorization remain server-owned.
      window.dispatchEvent(new CustomEvent("sana:demo-role-change", { detail: { role } }));
    }
  }

  try {
    const saved = localStorage.getItem(storageKey);
    if (saved === "business" || saved === "team") profileSelect.value = saved;
  } catch { /* The shell also works when browser storage is unavailable. */ }

  profileSelect.addEventListener("change", () => {
    try { localStorage.setItem(storageKey, profileSelect.value); } catch { /* Optional preference. */ }
    applyDemoRole(true);
  });
  window.addEventListener("hashchange", () => showPage(true));
  applyDemoRole();
  showPage();
})();
