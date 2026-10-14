from fastapi import FastAPI
from contextlib import asynccontextmanager
from routers import revenue, items, peak_hours, today, demand, categories, tables, products

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[analytics] service started")
    yield
    print("[analytics] service stopped")

app = FastAPI(title="Ordash Analytics", lifespan=lifespan)

# ── Root ──────────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {
        "service": "Ordash Analytics 🍽️",
        "status": "up and running",
        "message": "Nothing to see here — go order some food 🚀",
        "docs": "/docs",
    }

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(revenue.router,    prefix="/analytics")
app.include_router(items.router,      prefix="/analytics")
app.include_router(peak_hours.router, prefix="/analytics")
app.include_router(today.router,      prefix="/analytics")
app.include_router(demand.router,     prefix="/predict")
app.include_router(categories.router, prefix="/analytics")
app.include_router(tables.router,     prefix="/analytics")
app.include_router(products.router,   prefix="/analytics")

# ── Health ────────────────────────────────────────────────────────────────────
@app.api_route("/health", methods=["GET", "HEAD"])
def health():
    return {"status": "ok"}

# ── Keep-alive ping ───────────────────────────────────────────────────────────
@app.api_route("/ping", methods=["GET", "HEAD"])
def ping():
    return {"status": "pong"}
