from fastapi import APIRouter
from bson import ObjectId
from db import db, cache
import json
from datetime import datetime
router = APIRouter()

@router.get("/peak-hours/{seller_id}")
async def peak_hours(seller_id: str):
    key    = f"analytics:peak-hours:{seller_id}"
    #Redis cache
    cached = await cache.get(key)
    if cached:
        return {"data": json.loads(cached), "cached": True}

    pipeline = [
        {"$match": {"seller": ObjectId(seller_id)}},
        {"$group": {
            "_id":    {"$hour": "$createdAt"},
            "orders": {"$sum": 1}
        }},
        {"$sort": {"_id": 1}}
    ]
    result = await db.orders.aggregate(pipeline).to_list(None)
    
    now        = datetime.now()
    end_of_day = now.replace(hour=23, minute=59, second=59)
    ttl        = int((end_of_day - now).total_seconds())
    await cache.setex(key, ttl, json.dumps(result, default=str))

    return {"data": result, "cached": False}
