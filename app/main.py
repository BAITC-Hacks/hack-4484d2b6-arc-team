from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.config import cors_origins, database_path
from app.db import Database
from app.models import DemoProfiles, DraftCreate, DraftUpdate, Task
from app.repository import Repository


def create_app(db_path: Path | None = None) -> FastAPI:
    db = Database(db_path if db_path is not None else database_path())
    repository = Repository(db)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db.initialize()
        yield

    app = FastAPI(title="AI Sana Challenge Hub", version="0.1.0", lifespan=lifespan,
                  description="Step 1: demo profiles and persistent drafts. Demo profile headers are not authentication.")
    app.state.db = db
    origins = cors_origins()
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST", "PATCH"],
                           allow_headers=["Content-Type", "X-Demo-Business-Id"])

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        codes = {400: "bad_request", 404: "not_found", 405: "method_not_allowed"}
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": codes.get(exc.status_code, "http_error"), "message": str(exc.detail), "details": []}}, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        details = [{"field": ".".join(map(str, e["loc"])), "message": e["msg"]} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": "Проверьте поля запроса", "details": details}})

    def business_profile(x_demo_business_id: Annotated[str | None, Header()] = None) -> str:
        if not x_demo_business_id:
            raise HTTPException(400, "Укажите X-Demo-Business-Id из /api/demo/profiles")
        if not repository.business_exists(x_demo_business_id):
            raise HTTPException(404, "Демонстрационный бизнес-профиль не найден")
        return x_demo_business_id

    @app.get("/", include_in_schema=False)
    def index():
        return {"service": "AI Sana Challenge Hub", "stage": "storage", "docs": "/docs"}

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

    return app


app = create_app()
