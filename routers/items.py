from fastapi import APIRouter
from bson import ObjectId
from db import db, cache
import json

router = APIRouter()

@router.get("/top-items/{seller_id}")
async def top_items(seller_id: str):
    key    = f"analytics:top-items:{seller_id}"
    cached = await cache.get(key)
    if cached:
        return {"data": json.loads(cached), "cached": True}

    pipeline = [
        {"$match": {"seller": ObjectId(seller_id), "status": "done"}},
        {"$unwind": "$items"},
        {"$group": {
            "_id":     "$items.name",
            "count":   {"$sum": "$items.quantity"},
            "revenue": {"$sum": {"$multiply": ["$items.price", "$items.quantity"]}}
        }},
        {"$sort": {"count": -1}},
        {"$limit": 10}
    ]
    result = await db.orders.aggregate(pipeline).to_list(None)

    from datetime import datetime
    now        = datetime.now()
    end_of_day = now.replace(hour=23, minute=59, second=59)
    ttl        = int((end_of_day - now).total_seconds())
    await cache.setex(key, ttl, json.dumps(result, default=str))

    return {"data": result, "cached": False}
