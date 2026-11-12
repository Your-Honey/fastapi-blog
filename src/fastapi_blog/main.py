from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from fastapi_swagger_ui_theme import setup_swagger_ui_theme
from starlette.exceptions import HTTPException as StarletteHTTPException

from fastapi_blog.routers import posts, users

from .database import engine


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(lifespan=lifespan, docs_url=None)
setup_swagger_ui_theme(app, docs_path="/docs")

app.mount(
    "/media",
    StaticFiles(directory=Path(__file__).parent / "media"),
    name="media",
)

app.include_router(users.router, prefix="/api/users", tags=["Users"])
app.include_router(posts.router, prefix="/api/posts", tags=["Posts"])


@app.exception_handler(RequestValidationError)
async def validation_execption_handler(
    request: Request, exception: RequestValidationError
):
    return await request_validation_exception_handler(request, exception)


@app.exception_handler(StarletteHTTPException)
async def general_HTTP_exception_handler(
    request: Request, exception: StarletteHTTPException
):
    return await http_exception_handler(request, exception)


def main() -> None:
    uvicorn.run("fastapi_blog.main:app")
