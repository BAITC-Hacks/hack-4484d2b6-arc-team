from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from app.ai import AIError, AIService
from app.config import ai_settings, cors_origins, database_path
from app.db import Database
from app.models import AIRequest, AIResult, DemoProfiles, DraftCreate, DraftUpdate, GenerateCardRequest, Task
from app.repository import Repository, StaleTaskError


def create_app(db_path: Path | None = None, ai_service: AIService | None = None) -> FastAPI:
    db = Database(db_path if db_path is not None else database_path())
    repository = Repository(db)
    ai = ai_service or AIService(ai_settings())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db.initialize()
        yield

    app = FastAPI(title="AI Sana Challenge Hub", version="0.2.0", lifespan=lifespan,
                  description="Step 2: persistent drafts and AI constructor. Demo profile headers are not authentication.")
    app.state.db = db
    assets = Path(__file__).resolve().parent
    app.mount("/static", StaticFiles(directory=assets / "static"), name="static")

    @app.get("/ui", include_in_schema=False)
    def ui():
        return FileResponse(assets / "templates" / "base.html")

    origins = cors_origins()
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST", "PATCH"],
                           allow_headers=["Content-Type", "X-Demo-Business-Id"])

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        codes = {400: "bad_request", 404: "not_found", 405: "method_not_allowed", 409: "conflict", 422: "validation_error"}
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": codes.get(exc.status_code, "http_error"), "message": str(exc.detail), "details": []}}, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        details = [{"field": ".".join(map(str, e["loc"])), "message": e["msg"]} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": "Проверьте поля запроса", "details": details}})

    @app.exception_handler(AIError)
    async def ai_error(request: Request, exc: AIError):
        return JSONResponse(status_code=exc.status_code, content={"error": {
            "code": exc.code, "message": exc.message, "details": [], "local_mode_available": True,
        }})

    @app.exception_handler(StaleTaskError)
    async def stale_task(request: Request, exc: StaleTaskError):
        return JSONResponse(status_code=409, content={"error": {
            "code": "task_changed", "message": "Задача изменилась во время запроса. Загрузите актуальные данные и повторите операцию.", "details": [],
        }})

    def business_profile(x_demo_business_id: Annotated[str | None, Header()] = None) -> str:
        if not x_demo_business_id:
            raise HTTPException(400, "Укажите X-Demo-Business-Id из /api/demo/profiles")
        if not repository.business_exists(x_demo_business_id):
            raise HTTPException(404, "Демонстрационный бизнес-профиль не найден")
        return x_demo_business_id

    @app.get("/", include_in_schema=False)
    def index():
        return {"service": "AI Sana Challenge Hub", "stage": "ai_constructor", "docs": "/docs"}

    @app.get("/api/ai/status", tags=["ai"])
    def ai_status():
        return {"default_mode": ai.settings.mode, "local_available": True,
                "openai_configured": bool(ai.settings.api_key), "model": ai.settings.model}

    @app.get("/health", tags=["system"])
    def health():
        with db.connect() as connection:
            connection.execute("SELECT 1").fetchone()
        return {"status": "ok", "database": "ok"}

    @app.get("/api/demo/profiles", response_model=DemoProfiles, tags=["demo"])
    def profiles():
        return repository.profiles()

    @app.post("/api/tasks", response_model=Task, status_code=201, tags=["drafts"])
    def create_draft(payload: DraftCreate, business_id: str = Depends(business_profile)):
        return repository.create_draft(business_id, payload)

    @app.get("/api/tasks", response_model=list[Task], tags=["drafts"])
    def own_tasks(business_id: str = Depends(business_profile)):
        return repository.list_tasks(business_id)

    @app.get("/api/tasks/{task_id}", response_model=Task, tags=["drafts"])
    def get_task(task_id: str, business_id: str = Depends(business_profile)):
        task = repository.get_task(task_id, business_id)
        if task is None:
            raise HTTPException(404, "Задача не найдена")
        return task

    @app.patch("/api/tasks/{task_id}", response_model=Task, tags=["drafts"])
    def save_draft(task_id: str, payload: DraftUpdate, business_id: str = Depends(business_profile)):
        task = repository.update_draft(task_id, business_id, payload)
        if task is None:
            raise HTTPException(404, "Задача не найдена")
        return task

    @app.post("/api/tasks/{task_id}/questions", response_model=AIResult, tags=["ai"])
    def generate_questions(task_id: str, payload: AIRequest | None = None,
                           business_id: str = Depends(business_profile)):
        task = repository.get_task(task_id, business_id)
        if task is None:
            raise HTTPException(404, "Задача не найдена")
        questions, meta = ai.questions(task, payload.mode if payload else None)
        return AIResult(task=repository.save_questions(task, questions, meta), ai=meta)

    @app.post("/api/tasks/{task_id}/generate-card", response_model=AIResult, tags=["ai"])
    def generate_card(task_id: str, payload: GenerateCardRequest | None = None,
                      business_id: str = Depends(business_profile)):
        task = repository.get_task(task_id, business_id)
        if task is None:
            raise HTTPException(404, "Задача не найдена")
        if not task.questions:
            raise HTTPException(409, "Сначала получите уточняющие вопросы")
        if payload and payload.answers is not None:
            if set(payload.answers) - {q.id for q in task.questions}:
                raise HTTPException(422, "Ответ содержит неизвестный идентификатор вопроса")
            # Commit input first, so a failed provider request never loses the answers.
            task = repository.save_answers(task, payload.answers)
        card, meta = ai.card(task, payload.mode if payload else None)
        return AIResult(task=repository.save_generated_card(task, card, meta), ai=meta)

    return app


app = create_app()
