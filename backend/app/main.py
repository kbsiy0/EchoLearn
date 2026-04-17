from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.jobs.runner import JobRunner
from app.routers import jobs as jobs_router
from app.routers import subtitles as subtitles_router
from app.routers import videos as videos_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    runner = JobRunner()
    runner.startup_sweep()
    app.state.runner = runner
    yield
    runner.shutdown(wait=True)


app = FastAPI(title="EchoLearn API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs_router.router)
app.include_router(subtitles_router.router)
app.include_router(videos_router.router)


from fastapi.exceptions import HTTPException as FastAPIHTTPException  # noqa: E402


@app.exception_handler(FastAPIHTTPException)
async def http_exception_handler(request: Request, exc: FastAPIHTTPException):
    """Flatten structured detail dicts to top-level response body."""
    if isinstance(exc.detail, dict):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/")
def root():
    return {"status": "ok"}
