from fastapi import APIRouter, Query
from bson import ObjectId
from db import db, cache
from datetime import datetime, timedelta, timezone
import json

router = APIRouter()

NPT_OFFSET = timedelta(hours=5, minutes=45)
NPT_TZ     = timezone(NPT_OFFSET)

def now_npt():
    return datetime.now(tz=NPT_TZ)

def get_range_bounds(range: str):
    npt_now   = now_npt()
    npt_today = npt_now.replace(hour=0, minute=0, second=0, microsecond=0)
    utc_today = npt_today.astimezone(timezone.utc).replace(tzinfo=None)
    utc_now   = npt_now.astimezone(timezone.utc).replace(tzinfo=None)

    if range == "today":
        return utc_today, utc_now
    elif range == "week":
        this_week_start = npt_today - timedelta(days=npt_today.weekday())
        s = this_week_start - timedelta(days=7)
        return s.astimezone(timezone.utc).replace(tzinfo=None), this_week_start.astimezone(timezone.utc).replace(tzinfo=None)
    elif range == "month":
        this_month_start = npt_today.replace(day=1)
        if this_month_start.month == 1:
            prev = this_month_start.replace(year=this_month_start.year - 1, month=12)
        else:
            prev = this_month_start.replace(month=this_month_start.month - 1)
        return prev.astimezone(timezone.utc).replace(tzinfo=None), this_month_start.astimezone(timezone.utc).replace(tzinfo=None)
    elif range == "year":
        s = npt_today.replace(year=npt_today.year - 1, month=1, day=1)
        e = npt_today.replace(month=1, day=1)
        return s.astimezone(timezone.utc).replace(tzinfo=None), e.astimezone(timezone.utc).replace(tzinfo=None)
    return utc_today, utc_now

@router.get("/categories/{seller_id}")
async def categories(seller_id: str, range: str = Query("today")):
    cache_key = f"analytics:categories:{seller_id}:{range}"

    if range != "today":
        cached = await cache.get(cache_key)
        if cached:
            return {"data": json.loads(cached), "cached": True}

    start, end = get_range_bounds(range)

    pipeline = [
        # 1. filter orders for this seller in the time range
        {"$match": {
            "seller":    ObjectId(seller_id),
            "status":    "done",
            "createdAt": {"$gte": start, "$lt": end}
        }},

        # 2. flatten order items
        {"$unwind": "$items"},

        # 3. join hotelproducts to get the product's category
        #    hotelproducts has one doc per seller with a products[] array
        {"$lookup": {
            "from": "hotelproducts",
            "let":  {"pid": "$items.productId", "sid": "$seller"},
            "pipeline": [
                {"$match": {"$expr": {"$eq": ["$seller", "$$sid"]}}},
                {"$unwind": "$products"},
                {"$match": {"$expr": {"$eq": ["$products._id", "$$pid"]}}},
                {"$project": {"_id": 0, "category": "$products.category"}}
            ],
            "as": "productInfo"
        }},

        # 4. flatten lookup result (one product = one category)
        {"$unwind": {
            "path": "$productInfo",
            "preserveNullAndEmptyArrays": True   # keep items if product was deleted
        }},

        # 5. group by category, sum revenue
        {"$group": {
            "_id":     {"$ifNull": ["$productInfo.category", "Uncategorized"]},
            "revenue": {"$sum": {"$multiply": ["$items.price", "$items.quantity"]}},
            "orders":  {"$sum": 1}
        }},

        {"$sort": {"revenue": -1}},

        {"$project": {
            "_id":      0,
            "category": "$_id",
            "revenue":  1,
            "orders":   1
        }}
    ]

    result = await db.orders.aggregate(pipeline).to_list(None)

    if range != "today":
        now      = datetime.now()
        midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        ttl      = int((midnight - now).total_seconds())
        await cache.setex(cache_key, ttl, json.dumps(result, default=str))

    return {"data": result, "cached": False}
