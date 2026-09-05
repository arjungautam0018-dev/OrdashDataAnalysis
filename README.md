# Ordash Analytics — Python Microservice

FastAPI service for data analytics and ML predictions.
Runs alongside the Node.js backend as a separate service.

## Run locally

```bash
cd python-service
pip install -r requirements.txt
cp .env.example .env   # fill in your values
uvicorn main:app --reload --port 8000
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /health | Health check |
| GET | /analytics/revenue/{seller_id} | Daily revenue breakdown |
| GET | /analytics/top-items/{seller_id} | Most ordered items |
| GET | /analytics/peak-hours/{seller_id} | Busiest hours of day |
| GET | /predict/demand/{seller_id} | 7-day demand forecast (ML) |

## Deploy on Render

1. Create a new Web Service on Render
2. Set root directory to `python-service`
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Add env vars: `MONGO_URL`, `REDIS_URL`
6. In Node backend `.env`, set: `PYTHON_SERVICE_URL=https://your-service.onrender.com`
