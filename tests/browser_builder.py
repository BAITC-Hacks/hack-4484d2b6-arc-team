"""Optional real-browser integration check; no Selenium or external AI calls.

Start chromedriver --port=9515, then run:
python tests/browser_builder.py --webdriver http://127.0.0.1:9515
The app uses an isolated temporary SQLite database and an explicit empty API key.
"""
import argparse
import base64
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import urllib.request

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.ai import AIService
from app.config import AISettings
from app.db import Database
from app.main import create_app
from app.repository import Repository
from seed import seed_database


class Browser:
    def __init__(self, base):
        self.base = base
        self.session = self.request("POST", "/session", {"capabilities": {"alwaysMatch": {
            "browserName": "chrome",
            "goog:chromeOptions": {"args": ["--headless=new", "--no-sandbox", "--disable-dev-shm-usage"]},
            "goog:loggingPrefs": {"browser": "ALL"}, "unhandledPromptBehavior": "accept",
        }}})["sessionId"]
        self.path = "/session/" + self.session

    def request(self, method, path, data=None):
        request = urllib.request.Request(self.base + path, method=method,
            data=json.dumps(data).encode() if data is not None else None,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=30) as response:
            value = json.load(response).get("value")
        if isinstance(value, dict) and "error" in value:
            raise RuntimeError(value)
        return value

    def js(self, code, *args):
        return self.request("POST", self.path + "/execute/sync", {"script": code, "args": list(args)})

    def wait(self, expression):
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if self.js("return " + expression):
                return
            time.sleep(.05)
        raise AssertionError("Timed out: " + expression)

    def idle(self):
        self.wait('document.querySelector("#builder-content").getAttribute("aria-busy") === "false"')

    def click(self, selector):
        self.js("document.querySelector(arguments[0]).click()", selector)
        self.idle()

    def fill(self, selector, value, event="input"):
        self.js("const e=document.querySelector(arguments[0]); e.value=arguments[1]; e.dispatchEvent(new Event(arguments[2],{bubbles:true}))", selector, value, event)

    def check(self, expression, label):
        assert self.js("return " + expression), label
        print("PASS:", label, flush=True)

    def screenshot(self, path):
        path.write_bytes(base64.b64decode(self.request("GET", self.path + "/screenshot")))


def verify(browser, url, repository, output):
    b = browser
    b.request("POST", b.path + "/window/rect", {"width": 1440, "height": 1100})
    b.request("POST", b.path + "/url", {"url": url + "/ui"})
    b.idle()
    b.check('!document.querySelector("#builder-fields").disabled', "real profiles initialize constructor")
    b.check('document.querySelector("#builder-business").options.length === 2', "business profiles come from API")
    b.check('document.querySelector(".builder-unrated").textContent.includes("Ещё не")', "unknown rating is not fabricated")
    b.screenshot(output / "builder-draft.png")

    before = len(repository.list_tasks("business-1"))
    text = "У нас небольшая доставка, хотим сократить опоздания."
    b.fill("#builder-draft", text)
    b.fill("#builder-topic", "logistics", "change")
    b.js('document.querySelector("#builder-analyze").click(); document.querySelector("#builder-analyze").click()')
    b.idle()
    b.check('!document.querySelector("#builder-stage-questions").hidden', "draft advances to questions")
    b.check('document.querySelectorAll("[data-question-id]").length >= 3', "server returns at least three questions")
    b.check('document.querySelector("#builder-questions-source").textContent.includes("Локальный режим")', "local source is clearly labeled")
    assert len(repository.list_tasks("business-1")) == before + 1, "double click created duplicate draft"
    task_id = b.js('return document.querySelector("#builder-task").value')
    b.js('document.querySelectorAll("[data-question-id]").forEach((e,i)=>{e.value=i===0?"не знаю":"Ответ бизнеса "+i;e.dispatchEvent(new Event("input",{bubbles:true}))})')
    b.screenshot(output / "builder-questions.png")
    b.click('#builder-questions-form button[type="submit"]')
    b.check('!document.querySelector("#builder-stage-card").hidden', "answers generate editable card")
    b.check('document.querySelectorAll("[data-card-field]").length === 10', "all contracted business fields are editable")
    task = repository.get_task(task_id, "business-1")
    assert getattr(task.proposed_card, task.questions[0].field) == "", "unknown answer became a fact"
    assert task.confirmed_card is None and task.published_card is None
    b.check('document.querySelector("#builder-confirm").disabled && document.querySelector("#builder-publish").disabled', "manual review is required before confirmation and publication")

    title = '<img src=x onerror="window.xss=true"> Доставка'
    b.fill("#builder-card-title", title)
    b.click('#builder-card-form button[type="submit"]')
    assert repository.get_task(task_id, "business-1").proposed_card.title == title
    b.check('!window.xss && !document.querySelector("#builder-task img")', "business content is rendered as text")
    b.screenshot(output / "builder-card.png")
    b.request("POST", b.path + "/refresh", {})
    b.idle()
    assert b.js('return document.querySelector("#builder-card-title").value') == title
    print("PASS: saved card survives reload", flush=True)

    b.fill("#builder-card-title", "Локальная правка первого бизнеса")
    b.fill("#builder-business", "business-2", "change")
    b.idle()
    b.check('document.querySelector("#builder-draft").value === ""', "second business has isolated local draft")
    b.fill("#builder-draft", "Черновик второго бизнеса")
    b.fill("#builder-business", "business-1", "change")
    b.idle()
    b.check('document.querySelector("#builder-card-title").value === "Локальная правка первого бизнеса"', "profile switching preserves unsaved card")
    b.fill("#demo-profile", "team", "change")
    b.check('document.querySelector("#builder-workspace").hidden', "team role cannot use business constructor")
    b.click("#builder-switch-business")
    b.check('!document.querySelector("#builder-workspace").hidden', "business role restores constructor")

    b.click('[data-stage="questions"]')
    b.fill("#builder-mode", "openai", "change")
    b.click("#builder-more-questions")
    b.check('!document.querySelector("#builder-error").hidden && !document.querySelector("#builder-local").hidden', "missing API key offers explicit local retry")
    b.check('document.querySelector("#builder-draft").value.includes("сократить опоздания")', "AI error keeps draft input")
    b.click("#builder-local")
    b.check('document.querySelector("#builder-error").hidden', "local retry recovers questions")
    b.check('document.querySelector("#builder-card-title").value === "Локальная правка первого бизнеса"', "question regeneration preserves manual card")

    b.fill("#builder-mode", "openai", "change")
    b.fill("[data-question-id]", "Новый ответ перед ошибкой")
    b.click('#builder-questions-form button[type="submit"]')
    b.check('document.querySelector("#builder-regenerate-dialog").open', "regeneration requires explicit replacement decision")
    b.click("#builder-regenerate-dialog .button-outline")
    b.check('document.querySelector("#builder-card-title").value === "Локальная правка первого бизнеса"', "cancel retains manual edits")
    b.click('#builder-questions-form button[type="submit"]')
    b.click("#builder-regenerate-dialog .button-primary")
    b.check('!document.querySelector("#builder-error").hidden && document.querySelector("[data-question-id]").value === "Новый ответ перед ошибкой"', "card AI failure preserves answers")
    stored = repository.get_task(task_id, "business-1")
    assert "Новый ответ перед ошибкой" in stored.answers.values(), "answers not stored before provider failure"
    b.click("#builder-local")
    b.check('!document.querySelector("#builder-stage-card").hidden', "card local retry completes")

    # A real 422 response must keep exactly what was entered, including overlong input.
    b.fill("#builder-card-title", "x" * 20001)
    b.js('document.querySelector("#builder-card-form").dispatchEvent(new Event("submit",{cancelable:true,bubbles:true}))')
    b.idle()
    b.check('!document.querySelector("#builder-error").hidden && document.querySelector("#builder-card-title").value.length === 20001', "validation error preserves all card input")
    b.fill("#builder-card-title", "Исправленная карточка")
    b.click("#builder-retry")
    b.check('document.querySelector("#builder-error").hidden', "validation retry uses corrected input")

    # Simulate a browser network outage, leaving the real server and database intact.
    b.fill("#builder-card-context", "Этот текст не должен исчезнуть")
    b.js('window.realFetch=window.fetch; window.fetch=()=>Promise.reject(new TypeError("offline"))')
    b.click('#builder-card-form button[type="submit"]')
    b.check('!document.querySelector("#builder-error").hidden && document.querySelector("#builder-card-context").value === "Этот текст не должен исчезнуть"', "network failure preserves manual edits")
    b.js('window.fetch=window.realFetch')
    b.click("#builder-retry")
    assert repository.get_task(task_id, "business-1").proposed_card.context == "Этот текст не должен исчезнуть"

    b.fill("#builder-card-context", "Правка перед неверным JSON")
    b.js('window.fetch=()=>Promise.resolve(new Response("not-json",{status:502}))')
    b.click('#builder-card-form button[type="submit"]')
    b.check('!document.querySelector("#builder-error").hidden && document.querySelector("#builder-card-context").value === "Правка перед неверным JSON"', "invalid JSON preserves manual edits")
    b.js('window.fetch=window.realFetch')
    b.click("#builder-retry")

    b.fill("#builder-business", "business-2", "change")
    b.idle()
    b.check('document.querySelector("#builder-draft").value === "Черновик второго бизнеса"', "unsaved new draft survives profile changes")
    b.request("POST", b.path + "/refresh", {})
    b.idle()
    b.check('document.querySelector("#builder-draft").value === "Черновик второго бизнеса"', "unsaved input survives reload")
    b.js('Storage.prototype.setItem=()=>{throw new Error("blocked")}; Storage.prototype.getItem=()=>{throw new Error("blocked")}; Storage.prototype.removeItem=()=>{throw new Error("blocked")};')
    b.fill("#builder-draft", "Правка без localStorage")
    b.fill("#builder-business", "business-1", "change")
    b.idle()
    b.fill("#builder-business", "business-2", "change")
    b.idle()
    b.check('document.querySelector("#builder-draft").value === "Правка без localStorage" && !document.querySelector("#builder-storage-warning").hidden', "blocked browser storage retains per-profile edits in memory")
    for width in [1440, 1086, 768, 390]:
        b.request("POST", b.path + "/window/rect", {"width": width, "height": 1000})
        b.check('document.documentElement.scrollWidth <= innerWidth', f"no overflow at {width}px")
    b.click('[data-page="catalog"]')
    b.check('!document.querySelector("#page-catalog").hidden && document.querySelectorAll(".catalog-card").length === 5', "team catalog remains functional")
    logs = b.request("POST", b.path + "/log", {"type": "browser"})
    assert not [entry for entry in logs if entry["source"] == "javascript" and entry["level"] == "SEVERE"], logs
    print("PASS: no JavaScript exceptions; expected 503/422 requests were exercised", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--webdriver", default="http://127.0.0.1:9515")
    parser.add_argument("--screenshots", type=Path, default=Path(tempfile.gettempdir()) / "sana-builder-screenshots")
    args = parser.parse_args()
    args.screenshots.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sana-browser-") as temporary:
        database = Database(Path(temporary) / "test.sqlite3")
        seed_database(database)
        app = create_app(database.path, AIService(AISettings(mode="local", api_key="")))
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        browser = None
        try:
            deadline = time.monotonic() + 10
            while not server.started and time.monotonic() < deadline:
                time.sleep(.05)
            assert server.started, "temporary app did not start"
            browser = Browser(args.webdriver)
            verify(browser, f"http://127.0.0.1:{port}", Repository(database), args.screenshots)
            from browser_readiness import verify_readiness
            verify_readiness(browser, f"http://127.0.0.1:{port}", Repository(database), args.screenshots)
        finally:
            if browser:
                browser.request("DELETE", browser.path)
            server.should_exit = True
            thread.join(timeout=5)
            sock.close()


if __name__ == "__main__":
    main()
