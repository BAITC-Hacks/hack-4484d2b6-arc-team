"""Readiness and publication checks run by tests/browser_builder.py.

Uses the actual backend in its temporary database. Direct repository writes only
simulate another browser editing the same task for version-conflict checks.
"""
from app.models import DraftUpdate


def verify_readiness(b, url, repository, output):
    b.request("POST", b.path + "/url", {"url": url + "/ui#builder"})
    b.idle()
    b.js("localStorage.clear()")
    b.request("POST", b.path + "/refresh", {})
    b.idle()
    b.request("POST", b.path + "/window/rect", {"width": 1440, "height": 1100})
    b.check('document.querySelector("#builder-rating").hidden && !document.querySelector("#builder-unrated").hidden', "null rating is shown as not calculated")
    b.fill("#builder-draft", "Нужна помощь с доставкой.")
    b.click("#builder-analyze")
    b.click('#builder-questions-form button[type="submit"]')
    task_id = b.js('return document.querySelector("#builder-task").value')
    get_task = lambda: repository.get_task(task_id, "business-1")
    b.js('document.querySelectorAll("[data-card-field]").forEach(e=>{e.value=e.dataset.cardField==="title"?"Доставка без опозданий":"";e.dispatchEvent(new Event("input",{bubbles:true}))})')
    b.check('document.querySelector("#builder-confirm").disabled', "typing a card does not confirm it")
    b.click("#builder-reviewed")
    # Record real requests to verify the reviewed timestamp and double-click guard.
    b.js('window.readinessRequests=[]; window.originalFetch=window.fetch; window.fetch=(url,options)=>{if(options?.method==="POST")window.readinessRequests.push({url,body:JSON.parse(options.body)});return window.originalFetch(url,options)}')
    reviewed_version = get_task().updated_at.isoformat()
    b.js('document.querySelector("#builder-confirm").click(); document.querySelector("#builder-confirm").click()')
    b.idle()
    requests = b.js('return window.readinessRequests.filter(r=>r.url.endsWith("/confirm"))')
    assert len(requests) == 1
    assert requests[0]["body"]["expected_updated_at"].replace("Z", "+00:00") == reviewed_version
    assert set(requests[0]["body"]) == {"expected_updated_at", "proposed_card"}, "client submitted a score"
    assert get_task().confirmed_rating.score == 0
    b.check('document.querySelector("#builder-score").textContent === "0" && document.querySelector("#builder-level").textContent === "Черновик"', "confirmed zero differs from absent rating")
    b.check('document.querySelectorAll(".builder-rating-category").length === 7', "all seven server categories are shown")
    assert b.js('return [...document.querySelectorAll("[data-missing-field]")].map(e=>e.dataset.missingField)') == get_task().confirmed_rating.missing_fields
    b.check('!document.querySelector("#builder-publish").disabled', "zero-point task can be published")
    b.click("#builder-publish")
    zero_publication = get_task()
    assert zero_publication.status == "published" and zero_publication.published_rating.score == 0
    b.check('document.querySelector("#builder-publication-state").textContent === "Опубликована" && document.querySelector("#builder-level").textContent === "Черновик"', "publication status and readiness level are independent")
    b.check('document.querySelector("#builder-publish").disabled', "repeated publication is disabled after success")

    # Missing-field links take the user to the corresponding editor without rating it.
    b.click('[data-missing-field="data"]')
    b.check('document.activeElement.id === "builder-card-data"', "missing-field action focuses the correct input")
    for field, text in {
        "context": "Диспетчер вручную распределяет заказы.",
        "need": "Сократить опоздания доставки.",
        "data": "Обезличенный CSV с заказами доступен для пилота.",
        "expected_result": "Прототип панели диспетчера.",
    }.items():
        b.fill("#builder-card-" + field, text)
    b.check('document.querySelector("#builder-score").textContent === "0" && document.querySelector("#builder-rating-changes").dataset.pending === "true"', "local changes keep the last confirmed score")
    b.check('document.querySelector("#builder-publish").disabled', "unsaved edits cannot be published")
    b.click('#builder-card-form button[type="submit"]')
    assert get_task().confirmed_rating.score == 0
    b.check('document.querySelector("#builder-score").textContent === "0"', "saving alone does not award points")
    b.click("#builder-reviewed")
    b.click("#builder-confirm")
    working = get_task()
    assert working.confirmed_rating.score == 55 and working.published_rating.score == 0
    b.check('document.querySelector("#builder-score").textContent === "55" && document.querySelector("#builder-level").textContent === "Рабочая"', "server 55-point rating uses working level")
    b.check('document.querySelector("#builder-published-snapshot").textContent.includes("0 / 100")', "confirmation leaves previous publication intact")
    categories = b.js('return [...document.querySelectorAll(".builder-rating-category")].map(e=>({key:e.dataset.category,score:e.querySelector(".category-score").textContent}))')
    assert categories == [{"key": c.key, "score": f"{c.points} / {c.maximum}"} for c in working.confirmed_rating.categories]
    b.click('.builder-rating-category summary')
    b.check('document.querySelector(".builder-rating-category").open', "category field breakdown is expandable")
    b.js('document.querySelector("#builder-readiness-heading").scrollIntoView({block:"start"})')
    b.screenshot(output / "readiness-working.png")
    b.click("#builder-publish")
    assert get_task().published_rating.score == 55
    first_publication_time = get_task().published_at

    # Client does not implement the placeholder rubric: a rejected title is 422.
    b.fill("#builder-card-title", "не знаю")
    b.click("#builder-reviewed")
    b.click("#builder-confirm")
    b.check('!document.querySelector("#builder-error").hidden && document.querySelector("#builder-card-title").value === "не знаю"', "confirmation validation error preserves input")
    assert get_task().confirmed_rating.score == 55
    b.fill("#builder-card-title", "Доставка с понятными критериями")
    b.check('!document.querySelector("#builder-reviewed").checked && document.querySelector("#builder-confirm").disabled', "editing invalidates the review checkbox")
    for field in ["success_criteria", "constraints", "users", "contact", "interaction_format"]:
        b.fill("#builder-card-" + field, "Подтверждённые сведения бизнеса: " + field)

    # An interrupted confirmation never updates the displayed or stored rating.
    b.click("#builder-reviewed")
    b.js('window.fetch=()=>Promise.reject(new TypeError("offline"))')
    b.click("#builder-confirm")
    b.check('document.querySelector("#builder-score").textContent === "55" && !document.querySelector("#builder-error").hidden', "failed confirmation does not update the score")
    b.js('window.fetch=window.originalFetch')
    b.click("#builder-retry")
    assert get_task().confirmed_rating.score == 100
    b.check('document.querySelector("#builder-score").textContent === "100" && document.querySelector("#builder-level").textContent === "Приоритетная" && !document.querySelector("#builder-missing-complete").hidden', "server 100-point rating clears missing fields")
    assert get_task().published_rating.score == 55

    # Another editor changes the task between rendering and a publication click.
    repository.update_draft(task_id, "business-1", DraftUpdate(topic="education"))
    b.click("#builder-publish")
    b.check('!document.querySelector("#builder-error").hidden && document.querySelector("#builder-publish").disabled', "stale publication is blocked")
    assert get_task().published_rating.score == 55
    b.click("#builder-retry")
    b.check('document.querySelector("#builder-publish").disabled && !document.querySelector("#builder-reviewed").checked', "refreshing a conflict does not auto-confirm or publish")

    # A concurrent edit cannot be hidden by a preliminary PATCH before confirm.
    b.fill("#builder-card-title", "Моя несохранённая правка")
    repository.update_draft(task_id, "business-1", DraftUpdate(topic="services"))
    prior = get_task()
    b.click("#builder-reviewed")
    b.click("#builder-confirm")
    b.check('document.querySelector("#builder-card-title").value === "Моя несохранённая правка" && !document.querySelector("#builder-error").hidden', "stale confirmation retains unsaved card")
    assert get_task().proposed_card == prior.proposed_card and get_task().confirmed_card == prior.confirmed_card
    b.click("#builder-retry")
    b.check('document.querySelector("#builder-card-title").value === "Моя несохранённая правка" && document.querySelector("#builder-topic").value === "services" && document.querySelector("#builder-confirm").disabled', "conflict refresh preserves local edits and adopts latest server topic")
    b.click("#builder-reviewed")
    b.click("#builder-confirm")
    assert get_task().confirmed_card.title == "Моя несохранённая правка"
    assert get_task().published_rating.score == 55
    b.click("#builder-publish")
    assert get_task().published_rating.score == 100 and get_task().published_topic == "services"
    assert get_task().published_at == first_publication_time

    # Deleting confirmed information can lower the server rating; no local forecast.
    b.fill("#builder-card-data", "")
    b.check('document.querySelector("#builder-score").textContent === "100"', "deleting a field does not prematurely lower confirmed score")
    b.click("#builder-reviewed")
    b.click("#builder-confirm")
    assert get_task().confirmed_rating.score == 80
    b.check('document.querySelector("#builder-score").textContent === "80" && document.querySelector("#builder-level").textContent === "Готовая"', "server recalculation can lower the score")
    b.request("POST", b.path + "/refresh", {})
    b.idle()
    b.check('document.querySelector("#builder-score").textContent === "80" && document.querySelector("#builder-published-snapshot").textContent.includes("100 / 100")', "confirmed and published scores survive reload separately")

    # Source text is not the card: saving it must not silently replace the review.
    b.click('[data-stage="draft"]')
    b.fill("#builder-topic", "logistics", "change")
    b.click('[data-stage="card"]')
    b.check('document.querySelector("#builder-reviewed").disabled && !document.querySelector("#builder-save-materials").hidden', "unsaved source changes require separate saving before review")
    b.click("#builder-save-materials")
    b.check('document.querySelector("#builder-score").textContent === "80" && !document.querySelector("#builder-reviewed").disabled', "source save keeps rating until explicit confirmation")
    b.fill("#builder-business", "business-2", "change")
    b.idle()
    b.check('document.querySelector("#builder-rating").hidden', "confirmed rating does not leak to another business")
    b.fill("#builder-business", "business-1", "change")
    b.idle()
    b.check('document.querySelector("#builder-score").textContent === "80"', "returning to business restores its server rating")
    for width in [1440, 1086, 768, 390]:
        b.request("POST", b.path + "/window/rect", {"width": width, "height": 1000})
        b.check('document.documentElement.scrollWidth <= innerWidth', f"readiness panel fits {width}px")
    logs = b.request("POST", b.path + "/log", {"type": "browser"})
    assert not [entry for entry in logs if entry["source"] == "javascript" and entry["level"] == "SEVERE"], logs
    print("PASS: readiness, explicit review, zero-score publication, version conflicts and snapshot isolation", flush=True)
