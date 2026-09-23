/* Business dashboard adapter: docs/API.md from feat/backend-workflow.
   Older servers keep unavailable workflow actions disabled. */
(() => {
  "use strict";
  const proposalStatuses = ["submitted", "selected", "rejected"];
  const milestoneStatuses = ["submitted", "confirmed"];
  function invalid() { return new Error("Сервер вернул неподдерживаемый формат данных. Обновите страницу или повторите позже."); }
  function proposal(value, taskId) {
    if (!value || typeof value.id !== "string" || value.task_id !== taskId || typeof value.team_id !== "string"
        || !proposalStatuses.includes(value.status)
        || ["idea", "plan", "timeline"].some((key) => typeof value[key] !== "string")
        || (value.questions != null && typeof value.questions !== "string")
        || (value.prototype_url != null && typeof value.prototype_url !== "string")
        || typeof value.team_name !== "string" || !Array.isArray(value.milestones)) throw invalid();
    value.milestones.forEach((item) => milestone(item, value.id));
    return value;
  }
  function milestone(value, proposalId) {
    if (!value || typeof value.id !== "string" || value.proposal_id !== proposalId
        || !milestoneStatuses.includes(value.status) || typeof value.description !== "string"
        || (value.result_url != null && typeof value.result_url !== "string")
        || !Number.isInteger(value.points_awarded) || value.points_awarded < 0) throw invalid();
    return value;
  }
  async function request(path, { businessId, method = "GET", body, signal } = {}) {
    const controller = new AbortController();
    const abort = () => controller.abort();
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) controller.abort();
    const timeout = setTimeout(abort, 30000);
    try {
      const response = await fetch(path, { method, signal: controller.signal,
        headers: { ...(businessId ? { "X-Demo-Business-Id": businessId } : {}), ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
      let data;
      try { data = await response.json(); } catch { throw invalid(); }
      if (!response.ok) throw new Error(data.error?.message || "Не удалось выполнить действие. Обновите данные и попробуйте снова.");
      return data;
    } catch (error) {
      if (error.name === "AbortError" && !signal?.aborted) throw new Error("Сервер не ответил вовремя. Обновите данные перед повторным действием.");
      if (error instanceof TypeError) throw new Error("Нет соединения с сервером. Статус действия неизвестен — обновите данные перед повтором.");
      throw error;
    } finally { clearTimeout(timeout); signal?.removeEventListener("abort", abort); }
  }
  function resolve(schema, specification) {
    if (!schema?.$ref) return schema || {};
    if (!schema.$ref.startsWith("#/components/schemas/")) return {};
    return specification.components?.schemas?.[schema.$ref.split("/").pop()] || {};
  }
  async function capabilities(signal) {
    const spec = await request("/openapi.json", { signal });
    const paths = spec.paths || {};
    const decision = paths["/api/proposals/{proposal_id}"]?.patch;
    const body = resolve(decision?.requestBody?.content?.["application/json"]?.schema, spec);
    const status = resolve(body.properties?.status, spec);
    const confirm = paths["/api/milestones/{milestone_id}/confirm"]?.post;
    const confirmBody = resolve(confirm?.requestBody?.content?.["application/json"]?.schema, spec);
    return {
      proposals: Boolean(paths["/api/tasks/{task_id}/proposals"]?.get),
      decision: Boolean(decision && body.type === "object" && (body.required || []).every((key) => key === "status")
        && ["selected", "rejected"].every((value) => status.enum?.includes(value))),
      confirm: Boolean(confirm && (!confirm.requestBody || (confirmBody.type === "object" && !(confirmBody.required || []).length))),
      confirmBody: confirm?.requestBody ? {} : undefined,
    };
  }
  const pathId = (value) => encodeURIComponent(value);
  window.SanaBusinessApi = Object.freeze({
    profiles: (signal) => request("/api/demo/profiles", { signal }),
    tasks: (businessId, signal) => request("/api/tasks", { businessId, signal }),
    capabilities,
    async proposals(taskId, businessId, signal) {
      const result = await request(`/api/tasks/${pathId(taskId)}/proposals`, { businessId, signal });
      if (!Array.isArray(result)) throw invalid();
      return result.map((value) => proposal(value, taskId));
    },
    async decide(item, status, businessId) {
      const result = await request(`/api/proposals/${pathId(item.id)}`, { businessId, method: "PATCH", body: { status } });
      const checked = proposal(result, item.task_id);
      if (checked.id !== item.id || checked.team_id !== item.team_id) throw invalid();
      return checked;
    },
    async confirm(item, businessId, body) {
      const result = await request(`/api/milestones/${pathId(item.id)}/confirm`, { businessId, method: "POST", body });
      const checked = milestone(result, item.proposal_id);
      if (checked.id !== item.id) throw invalid();
      return checked;
    },
  });
})();
