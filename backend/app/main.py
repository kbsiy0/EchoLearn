from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.jobs.runner import JobRunner
from app.routers import subtitles


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

app.include_router(subtitles.router)


@app.get("/")
def root():
    return {"status": "ok"}
