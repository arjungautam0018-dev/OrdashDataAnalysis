from fastapi import FastAPI
from contextlib import asynccontextmanager
from routers import revenue, items, peak_hours, today, demand

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[analytics] service started")
    yield
    print("[analytics] service stopped")

app = FastAPI(title="Ordash Analytics", lifespan=lifespan)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(revenue.router,    prefix="/analytics")
app.include_router(items.router,      prefix="/analytics")
app.include_router(peak_hours.router, prefix="/analytics")
app.include_router(today.router,      prefix="/analytics")
app.include_router(demand.router,     prefix="/predict")

# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok"}
