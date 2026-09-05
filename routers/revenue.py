from fastapi import APIRouter
from bson import ObjectId
from db import db, cache
import json

router = APIRouter()

@router.get("/revenue/{seller_id}")
async def revenue(seller_id: str):
    key    = f"analytics:revenue:{seller_id}"
    cached = await cache.get(key)
    if cached:
        return {"data": json.loads(cached), "cached": True}

    # daily revenue for all completed orders — excludes today
    from datetime import datetime
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    pipeline = [
        {"$match": {
            "seller":    ObjectId(seller_id),
            "status":    "done",
            "createdAt": {"$lt": today_start}
        }},
        {"$group": {
            "_id":     {"$dateToString": {"format": "%Y-%m-%d", "date": "$createdAt"}},
            "revenue": {"$sum": "$total"},
            "orders":  {"$sum": 1}
        }},
        {"$sort": {"_id": 1}}
    ]
    result = await db.orders.aggregate(pipeline).to_list(None)

    # cache until end of day
    from datetime import timedelta
    now        = datetime.now()
    end_of_day = now.replace(hour=23, minute=59, second=59)
    ttl        = int((end_of_day - now).total_seconds())
    await cache.setex(key, ttl, json.dumps(result, default=str))

    return {"data": result, "cached": False}
