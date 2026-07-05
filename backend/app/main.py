from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import runs, supervisors
from .db import SessionLocal, init_db
from .seed import seed_supervisors


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    async with SessionLocal() as session:
        await seed_supervisors(session)
    yield


app = FastAPI(title="Order Supervisor API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(supervisors.router)
app.include_router(runs.router)


@app.get("/api/health")
async def health():
    return {"ok": True}
