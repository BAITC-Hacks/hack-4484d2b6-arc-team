"""Real backend workflow checks, called by browser_business.py on API v0.4+.

Business actions use the browser. Team submissions use actual HTTP endpoints,
because member #3 owns those screens. No fixture endpoints are installed here.
"""
import json
import urllib.request


def verify_workflow(b, url, repository, output):
    from browser_business import click, idle

    def api(path, method="GET", body=None, team=None, business=None):
        headers = {"Content-Type": "application/json"}
        if team:
            headers["X-Demo-Team-Id"] = team
        if business:
            headers["X-Demo-Business-Id"] = business
        request = urllib.request.Request(url + path, method=method, headers=headers,
            data=json.dumps(body).encode() if body is not None else None)
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)

    # Create, clarify, edit, confirm and publish from the actual business UI.
    click(b, "#business-create")
    b.wait('location.hash === "#builder"')
    b.fill("#builder-draft", "У нас небольшая доставка. Хотим сократить опоздания.")
    b.fill("#builder-topic", "logistics", "change")
    b.click("#builder-analyze")
    b.check('document.querySelectorAll("[data-question-id]").length >= 3', "real workflow: business receives clarification questions")
    b.js('document.querySelectorAll("[data-question-id]").forEach(e=>{e.value="не знаю";e.dispatchEvent(new Event("input",{bubbles:true}))})')
    b.click('#builder-questions-form button[type="submit"]')
    b.js('document.querySelectorAll("[data-card-field]").forEach(e=>{e.value=e.dataset.cardField==="title"?"Доставка: пилот команды":"";e.dispatchEvent(new Event("input",{bubbles:true}))})')
    b.click("#builder-reviewed")
    b.click("#builder-confirm")
    b.click("#builder-publish")
    task_id = b.js('return document.querySelector("#builder-task").value')
    task = repository.get_task(task_id, "business-1")
    assert task.status == "published" and task.published_rating.score == 0
    assert api(f"/api/catalog/{task_id}")["published_rating"]["score"] == 0
    print("PASS: real workflow: zero-point task published through business UI", flush=True)

    # Team #3's API contract, no local frontend data or mock records.
    proposals = []
    for index in range(1, 6):
        proposals.append(api(f"/api/tasks/{task_id}/proposals", "POST", {
            "idea": f"Подход команды {index}: прототип диспетчерской панели",
            "plan": "Проверить доступность данных, согласовать пилот, показать результат",
            "timeline": f"{index + 1} недель", "prototype_url": None,
            "questions": "Какие данные можно использовать в пилоте?",
        }, team=f"team-{index}"))

    click(b, '[data-page="business"]')
    idle(b)
    click(b, f'[data-task-id="{task_id}"]')
    b.check('document.querySelectorAll(".business-proposal").length === 5', "real workflow: all submitted proposals are shown")
    assert all(item["status"] == "submitted" for item in api(f"/api/tasks/{task_id}/proposals", business="business-1"))
    for item in proposals[:2]:
        click(b, f'[data-compare-id="{item["id"]}"]')
    click(b, "#business-compare")
    b.check('document.querySelector("#business-comparison").open', "real workflow: business compares actual team proposals")
    b.screenshot(output / "business-real-comparison.png")
    click(b, "#business-comparison-close")
    for item in proposals[:2]:
        selector = f'[data-proposal-id="{item["id"]}"] [data-decision="selected"]'
        b.js('const button=document.querySelector(arguments[0]);button.click();button.click()', selector)
        idle(b)
    click(b, f'[data-proposal-id="{proposals[2]["id"]}"] [data-decision="rejected"]')
    actual = api(f"/api/tasks/{task_id}/proposals", business="business-1")
    assert {item["id"]: item["status"] for item in actual} == {
        item["id"]: "selected" if index < 2 else "rejected" if index == 2 else "submitted"
        for index, item in enumerate(proposals)
    }
    print("PASS: real workflow: select multiple, reject one, leave others undecided", flush=True)
    b.check('!document.querySelector(".business-proposal:has(.badge-mint) [data-decision]")', "terminal decision does not offer an unsupported reversal")

    milestone = api(f'/api/proposals/{proposals[0]["id"]}/milestones', "POST", {
        "description": "Учебный прототип проверен на синтетическом CSV.",
        "result_url": None,
    }, team="team-1")
    click(b, "#business-refresh")
    selector = f'[data-confirm-milestone="{milestone["id"]}"]'
    b.check('document.querySelectorAll(".business-milestone").length === 1', "real workflow: embedded milestone is visible to business")
    b.js('const button=document.querySelector(arguments[0]);button.click();button.click()', selector)
    idle(b)
    b.check('document.querySelector(".business-milestone").textContent.includes("10 баллов") && !document.querySelector("[data-confirm-milestone]")', "real workflow: business confirmation displays server-awarded points")
    assert api(f'/api/milestones/{milestone["id"]}/confirm', "POST", business="business-1")["points_awarded"] == 10
    profiles = api("/api/demo/profiles")
    assert next(item for item in profiles["teams"] if item["id"] == "team-1")["points"] == 10
    assert repository.get_task(task_id, "business-1").confirmed_rating == task.confirmed_rating
    assert api("/api/my/proposals", team="team-1")[0]["milestones"][0]["status"] == "confirmed"
    print("PASS: real workflow: repeat confirmation awards once, team API sees result, task rating unchanged", flush=True)
    b.js('document.querySelector(".business-milestone").scrollIntoView({block:"center"})')
    b.screenshot(output / "business-real-milestone.png")
    b.request("POST", b.path + "/refresh", {})
    b.idle(); idle(b)
    click(b, f'[data-task-id="{task_id}"]')
    b.check('document.querySelector(".business-milestone").textContent.includes("10 баллов")', "real workflow: decisions and confirmed points survive reload")
    b.fill("#business-profile", "business-2", "change")
    idle(b)
    b.check('document.querySelectorAll(".business-proposal").length === 0', "real workflow: another business cannot see these proposals")
    logs = b.request("POST", b.path + "/log", {"type": "browser"})
    assert not [entry for entry in logs if entry["source"] == "javascript" and entry["level"] == "SEVERE"], logs
    print("PASS: actual workflow backend; no proposal or milestone fixtures", flush=True)
