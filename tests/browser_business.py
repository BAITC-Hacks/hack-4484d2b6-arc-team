"""Run: python tests/browser_business.py (requires local chromedriver on :9515).

Checks the actual backend and uses the real workflow API when available.
On v0.3 only, explicitly attaches a TEST-ONLY fixture for workflow interactions.
No real DB or external AI use.
"""
import argparse
from pathlib import Path
import socket
import tempfile
import threading
import time

import uvicorn

from browser_builder import Browser
from business_api_fixture import DashboardFixture
from app.ai import AIService
from app.config import AISettings
from app.db import Database
from app.main import create_app
from app.repository import Repository
from seed import seed_database


def idle(b):
    b.wait('document.querySelector("#business-workspace").getAttribute("aria-busy") === "false"')


def click(b, selector):
    b.js("document.querySelector(arguments[0]).click()", selector)
    idle(b)


def verify_current(b, url, output, workflow=False):
    b.request("POST", b.path + "/window/rect", {"width": 1440, "height": 1100})
    b.request("POST", b.path + "/url", {"url": url + "/ui"})
    b.idle()
    b.js('window.dashboardCalls=[];window.originalFetch=window.fetch;window.fetch=(url,options)=>{window.dashboardCalls.push(url);return window.originalFetch(url,options)}')
    click(b, '[data-page="business"]')
    b.wait('document.querySelector("#business-total").textContent === "3"')
    idle(b)
    b.check('document.querySelectorAll(".business-task").length === 3', "actual backend: business sees its real tasks")
    if workflow:
        b.check('document.querySelector("#business-proposals-notice").hidden && document.querySelector("#business-proposals").textContent.includes("Пока нет предложений")', "real workflow API returns an honest empty proposals state")
    else:
        b.check('!document.querySelector("#business-proposals-notice").hidden', "missing proposal API is explicitly unavailable")
        b.check('!window.dashboardCalls.some(url=>url.endsWith("/proposals"))', "missing endpoints are not called or silently simulated")
    b.screenshot(output / "business-task-list.png")
    click(b, '#business-task-detail button')
    b.wait('location.hash === "#builder"')
    b.fill("#builder-draft", "Несохранённая правка перед кабинетом")
    click(b, '[data-page="business"]')
    idle(b)
    click(b, '#business-task-detail button')
    b.wait('location.hash === "#builder"')
    b.check('document.querySelector("#builder-draft").value === "Несохранённая правка перед кабинетом"', "dashboard handoff preserves unsaved constructor input")
    click(b, '[data-page="business"]')
    idle(b)
    b.fill("#business-filter", "published", "change")
    idle(b)
    b.check('!document.querySelector("#business-empty").hidden', "empty publication filter has an honest empty state")
    b.fill("#business-filter", "all", "change")
    idle(b)
    b.fill("#business-profile", "business-2", "change")
    idle(b)
    b.check('document.querySelectorAll(".business-task").length === 2 && window.SanaBuilder.context().businessId === "business-2"', "business switch isolates tasks and synchronizes constructor")
    click(b, '#business-create')
    b.wait('location.hash === "#builder"')
    b.fill("#builder-draft", "Новая задача из кабинета")
    b.click("#builder-save-draft")
    click(b, '[data-page="business"]')
    b.wait('document.querySelector("#business-total").textContent === "3"')
    b.check('document.querySelector("#business-tasks").textContent.includes("Новая задача из кабинета")', "new constructor task appears in owner list")
    b.fill("#business-profile", "business-1", "change")
    idle(b)
    b.js('window.fetch=(url,options)=>url==="/openapi.json"?Promise.reject(new TypeError("offline")):window.originalFetch(url,options)')
    click(b, '#business-refresh')
    b.check('!document.querySelector("#business-error").hidden', "capability network error is not presented as no proposals")
    b.js('window.fetch=window.originalFetch')
    click(b, '#business-error-retry')
    b.check('document.querySelector("#business-error").hidden', "read-only refresh recovers dashboard")


def verify_fixture(b, fixture, repository, output):
    click(b, '#business-refresh')
    b.wait('document.querySelectorAll(".business-proposal").length === 6')
    b.check('document.querySelectorAll(".business-proposal").length === 6', "fixture API: every proposal is displayed without a cap")
    b.check('!window.dashboardXss && !document.querySelector(".business-proposal dd img")', "proposal text is safely escaped")
    b.check('document.querySelector("[data-proposal-id=proposal-1]").textContent.includes("Прототип пока не представлен")', "missing prototype is explicit")
    b.check('!document.querySelector("[data-proposal-id=proposal-2] a[href^=javascript]")', "unsafe prototype link is not clickable")
    b.check('[...document.querySelectorAll(".business-proposal a")].every(a=>a.rel.includes("noopener"))', "external links use safe relationship attributes")
    click(b, '[data-compare-id="proposal-1"]')
    click(b, '[data-compare-id="proposal-2"]')
    click(b, '#business-compare')
    b.check('document.querySelector("#business-comparison").open && document.querySelectorAll("#business-comparison tbody tr").length === 6', "same-field comparison opens for selected proposals")
    b.screenshot(output / "business-comparison.png")
    click(b, '#business-comparison-close')

    first = '[data-proposal-id="proposal-1"] [data-decision="selected"]'
    b.js('const e=document.querySelector(arguments[0]);e.click();e.click()', first)
    b.check('document.querySelector("[data-proposal-id=proposal-1] .badge").textContent === "На рассмотрении"', "no optimistic decision before server response")
    idle(b)
    assert fixture.decisions.count(("proposal-1", "selected")) == 1
    click(b, '[data-proposal-id="proposal-2"] [data-decision="selected"]')
    b.check('document.querySelector("[data-proposal-id=proposal-1] .badge").textContent === "Команда выбрана" && document.querySelector("[data-proposal-id=proposal-2] .badge").textContent === "Команда выбрана"', "multiple teams can be selected independently")
    assert fixture.proposals[2]["status"] == "selected" and fixture.proposals[4]["status"] == "submitted"
    click(b, '[data-proposal-id="proposal-6"] [data-decision="rejected"]')
    b.check('document.querySelector("[data-proposal-id=proposal-6] .badge").textContent === "Отклонено"', "business can reject an individual proposal")

    fixture.fail_decision = True
    click(b, '[data-proposal-id="proposal-5"] [data-decision="selected"]')
    b.check('!document.querySelector("#business-error").hidden && document.querySelector("[data-proposal-id=proposal-5] .badge").textContent === "На рассмотрении"', "failed decision retains previous status")
    b.check('[...document.querySelectorAll("[data-decision]")].every(e=>e.disabled)', "uncertain outcome requires refreshing before another write")
    click(b, '#business-error-retry')
    fixture.bad_response = True
    click(b, '[data-proposal-id="proposal-5"] [data-decision="selected"]')
    b.check('!document.querySelector("#business-error").hidden && document.querySelector("[data-proposal-id=proposal-5] .badge").textContent === "На рассмотрении"', "malformed decision response cannot claim success")
    click(b, '#business-error-retry')
    b.check('document.querySelector("[data-proposal-id=proposal-5] .badge").textContent === "Команда выбрана"', "refresh obtains canonical status after uncertain response")

    b.wait('document.querySelectorAll(".business-milestone").length === 3')
    b.check('document.querySelector("[data-milestone-id=milestone-2]").textContent.includes("13 баллов") && !document.querySelector("[data-milestone-id=milestone-2] button")', "confirmed milestone uses server points and cannot be confirmed again")
    rating_before = repository.get_task("draft-1", "business-1").confirmed_rating
    fixture.fail_confirmation = True
    click(b, '[data-confirm-milestone="milestone-1"]')
    b.check('!document.querySelector("#business-error").hidden && document.querySelector("[data-milestone-id=milestone-1] .badge").textContent === "Ожидает проверки"', "failed milestone confirmation does not award points")
    click(b, '#business-error-retry')
    b.wait('document.querySelectorAll(".business-milestone").length === 3')
    b.js('const e=document.querySelector("[data-confirm-milestone=milestone-1]");e.click();e.click()')
    idle(b)
    assert fixture.confirmations == ["milestone-1"]
    b.check('document.querySelector("[data-milestone-id=milestone-1]").textContent.includes("7 баллов") && !document.querySelector("[data-confirm-milestone=milestone-1]")', "milestone confirms once and displays exact returned points")
    assert repository.get_task("draft-1", "business-1").confirmed_rating == rating_before
    b.js('document.querySelector("[data-proposal-id=proposal-3]").scrollIntoView({block:"start"})')
    b.screenshot(output / "business-milestones.png")
    click(b, '#business-refresh')
    b.check('document.querySelector("[data-proposal-id=proposal-1] .badge").textContent === "Команда выбрана"', "refresh retains server decisions")

    # Future endpoints can exist with different required payloads. Do not guess them.
    fixture.proposals[-1]["status"] = "submitted"
    b.js('''window.fetch=async(url,options)=>{
      const response=await window.originalFetch(url,options);
      if(url!=="/openapi.json")return response;
      const spec=await response.json();
      spec.paths["/api/proposals/{proposal_id}"].patch.requestBody.content["application/json"].schema={type:"object",required:["status","version"],properties:{status:{enum:["selected","rejected"]},version:{type:"string"}}};
      const requiredBody={type:"object",required:["token"],properties:{token:{type:"string"}}};
      spec.paths["/api/milestones/{milestone_id}/confirm"].post.requestBody={required:true,content:{"application/json":{schema:requiredBody}}};
      return new Response(JSON.stringify(spec),{status:200,headers:{"Content-Type":"application/json"}});
    }''')
    click(b, '#business-refresh')
    b.check('document.querySelectorAll("[data-decision]").length === 2 && [...document.querySelectorAll("[data-decision]")].every(e=>e.disabled)', "unagreed required decision fields keep writes disabled")
    b.wait('document.querySelectorAll(".business-milestone").length === 3')
    b.check('document.querySelector("[data-confirm-milestone=milestone-3]").disabled', "unagreed milestone payload is not guessed")
    b.js('window.fetch=window.originalFetch')
    click(b, '#business-refresh')

    b.fill("#demo-profile", "team", "change")
    b.check('document.querySelector("#business-workspace").hidden && !document.querySelector("#business-team-notice").hidden', "team role does not show owner dashboard")
    click(b, '#business-switch-role')
    b.fill("#business-profile", "business-2", "change")
    idle(b)
    b.check('document.querySelectorAll(".business-proposal").length === 0 && document.querySelector("#business-proposals-notice").hidden', "second business sees its own empty proposals, not another owner's records")
    b.fill("#business-profile", "business-1", "change")
    idle(b)
    for width in [1440, 1086, 768, 390]:
        b.request("POST", b.path + "/window/rect", {"width": width, "height": 1000})
        b.check('document.documentElement.scrollWidth <= innerWidth', f"dashboard fits {width}px")
    logs = b.request("POST", b.path + "/log", {"type": "browser"})
    assert not [entry for entry in logs if entry["source"] == "javascript" and entry["level"] == "SEVERE"], logs
    print("PASS: real task API and explicit test-fixture proposal/milestone interactions", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--webdriver", default="http://127.0.0.1:9515")
    parser.add_argument("--screenshots", type=Path, default=Path(tempfile.gettempdir()) / "sana-business-screenshots")
    args = parser.parse_args()
    args.screenshots.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sana-business-") as directory:
        database = Database(Path(directory) / "test.sqlite3")
        seed_database(database)
        repository = Repository(database)
        app = create_app(database.path, AIService(AISettings(mode="local", api_key="")))
        sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start(); browser = None
        try:
            deadline = time.monotonic() + 10
            while not server.started and time.monotonic() < deadline: time.sleep(.05)
            assert server.started
            browser = Browser(args.webdriver)
            url = f"http://127.0.0.1:{port}"
            workflow = "/api/my/proposals" in app.openapi()["paths"]
            verify_current(browser, url, args.screenshots, workflow)
            if workflow:
                from browser_business_workflow import verify_workflow
                verify_workflow(browser, url, repository, args.screenshots)
            else:
                # Deliberate test-only installation after checking missing-API state.
                fixture = DashboardFixture(app, repository)
                verify_fixture(browser, fixture, repository, args.screenshots)
        finally:
            if browser: browser.request("DELETE", browser.path)
            server.should_exit = True; thread.join(timeout=5); sock.close()


if __name__ == "__main__":
    main()
