from fastapi import APIRouter, Query
from bson import ObjectId
from db import db, cache
from datetime import datetime, timedelta, timezone
import json

router = APIRouter()

NPT_OFFSET = timedelta(hours=5, minutes=45)
NPT_TZ     = timezone(NPT_OFFSET)

def get_range_bounds(range: str):
    npt_now   = datetime.now(tz=NPT_TZ)
    npt_today = npt_now.replace(hour=0, minute=0, second=0, microsecond=0)
    utc_today = npt_today.astimezone(timezone.utc).replace(tzinfo=None)
    utc_now   = npt_now.astimezone(timezone.utc).replace(tzinfo=None)

    if range == "today":
        return utc_today, utc_now
    elif range == "week":
        week_start = npt_today - timedelta(days=npt_today.weekday())
        s = week_start - timedelta(days=7)
        return s.astimezone(timezone.utc).replace(tzinfo=None), week_start.astimezone(timezone.utc).replace(tzinfo=None)
    elif range == "month":
        this_month = npt_today.replace(day=1)
        prev = this_month.replace(month=this_month.month - 1) if this_month.month > 1 \
               else this_month.replace(year=this_month.year - 1, month=12)
        return prev.astimezone(timezone.utc).replace(tzinfo=None), this_month.astimezone(timezone.utc).replace(tzinfo=None)
    elif range == "year":
        s = npt_today.replace(year=npt_today.year - 1, month=1, day=1)
        e = npt_today.replace(month=1, day=1)
        return s.astimezone(timezone.utc).replace(tzinfo=None), e.astimezone(timezone.utc).replace(tzinfo=None)
    return utc_today, utc_now

@router.get("/top-items/{seller_id}")
async def top_items(seller_id: str, range: str = Query("today")):
    cache_key = f"analytics:top-items:{seller_id}:{range}"

    # today always fresh, others cached until midnight
    if range != "today":
        cached = await cache.get(cache_key)
        if cached:
            return {"data": json.loads(cached), "cached": True}

    start, end = get_range_bounds(range)

    pipeline = [
        {"$match": {
            "seller":    ObjectId(seller_id),
            "status":    "done",
            "createdAt": {"$gte": start, "$lt": end}
        }},
        {"$unwind": "$items"},
        {"$group": {
            "_id":     "$items.name",
            "count":   {"$sum": "$items.quantity"},
            "revenue": {"$sum": {"$multiply": ["$items.price", "$items.quantity"]}}
        }},
        {"$sort": {"count": -1}},
        {"$limit": 5},
        {"$project": {"_id": 0, "name": "$_id", "count": 1, "revenue": 1}}
    ]

    result = await db.orders.aggregate(pipeline).to_list(None)

    if range != "today":
        now      = datetime.now()
        midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        ttl      = int((midnight - now).total_seconds())
        await cache.setex(cache_key, ttl, json.dumps(result, default=str))

    return {"data": result, "cached": False}
