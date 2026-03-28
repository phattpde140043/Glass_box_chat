from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

# Load env before importing runtime controller because controller wiring instantiates
# the orchestrator at import time and requires GEMINI_API_KEY immediately.
APP_DIR = Path(__file__).resolve().parent
SRC_DIR = APP_DIR.parent
REPO_ROOT = SRC_DIR.parent

load_dotenv(REPO_ROOT / ".env")
load_dotenv(SRC_DIR / ".env", override=False)

from .controllers.runtime_controller import (
    router as runtime_router,
    start_runtime_workers,
    stop_runtime_workers,
)
from .sqlite_db import initialize_sqlite


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_sqlite()
    await start_runtime_workers()
    yield
    await stop_runtime_workers()


app = FastAPI(
    title="The Glass Box API",
    version="0.1.0",
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(runtime_router)
