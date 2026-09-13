from fastapi import APIRouter, Query
from bson import ObjectId
from db import db, cache
from datetime import datetime, timedelta, timezone
import json
import asyncio
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
        week_start = npt_today - timedelta(days=npt_today.weekday())
        s = week_start - timedelta(days=7)
        return (
            s.astimezone(timezone.utc).replace(tzinfo=None),
            week_start.astimezone(timezone.utc).replace(tzinfo=None),
        )
    elif range == "month":
        this_month = npt_today.replace(day=1)
        prev = this_month.replace(month=this_month.month - 1) if this_month.month > 1 \
               else this_month.replace(year=this_month.year - 1, month=12)
        return (
            prev.astimezone(timezone.utc).replace(tzinfo=None),
            this_month.astimezone(timezone.utc).replace(tzinfo=None),
        )
    elif range == "year":
        s = npt_today.replace(year=npt_today.year - 1, month=1, day=1)
        e = npt_today.replace(month=1, day=1)
        return (
            s.astimezone(timezone.utc).replace(tzinfo=None),
            e.astimezone(timezone.utc).replace(tzinfo=None),
        )
    return utc_today, utc_now


def cache_ttl():
    now      = datetime.now()
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int((midnight - now).total_seconds())


def base_pipeline(seller_id: str, start: datetime, end: datetime) -> list:
    return [
        {"$match": {
            "seller":    ObjectId(seller_id),
            "status":    "done",              # fixed: removed stray space
            "createdAt": {"$gte": start, "$lt": end}
        }},
        {"$unwind": "$items"},
        {"$lookup": {
            "from": "hotelproducts",
            "let":  {"pid": "$items.productId", "sid": "$seller"},
            "pipeline": [
                {"$match": {"$expr": {"$eq": ["$seller", "$$sid"]}}},
                {"$unwind": "$products"},
                {"$match": {"$expr": {
                    "$eq": [{"$toString": "$products._id"}, {"$toString": "$$pid"}]
                }}},
                {"$project": {"_id": 0, "category": "$products.category"}}
            ],
            "as": "productInfo"
        }},
        {"$unwind": {
            "path": "$productInfo",
            "preserveNullAndEmptyArrays": True
        }},
    ]


def get_prev_bounds(range: str):
    npt_now   = now_npt()
    npt_today = npt_now.replace(hour=0, minute=0, second=0, microsecond=0)

    if range == "week":
        # previous week's previous week
        this_week = npt_today - timedelta(days=npt_today.weekday())
        prev_end   = this_week - timedelta(days=7)   # = current period start
        prev_start = prev_end - timedelta(days=7)
    elif range == "month":
        this_month = npt_today.replace(day=1)
        # current period = prev month; so prev period = 2 months ago
        if this_month.month == 1:
            curr_start = this_month.replace(year=this_month.year - 1, month=12)
        else:
            curr_start = this_month.replace(month=this_month.month - 1)
        # go back one more month
        if curr_start.month == 1:
            prev_start = curr_start.replace(year=curr_start.year - 1, month=12)
        else:
            prev_start = curr_start.replace(month=curr_start.month - 1)
        prev_end = curr_start
    elif range == "year":
        curr_start = npt_today.replace(year=npt_today.year - 1, month=1, day=1)
        prev_start = curr_start.replace(year=curr_start.year - 1)
        prev_end   = curr_start
    else:
        # today: prev period = yesterday
        prev_end   = npt_today
        prev_start = npt_today - timedelta(days=1)

    return (
        prev_start.astimezone(timezone.utc).replace(tzinfo=None),
        prev_end.astimezone(timezone.utc).replace(tzinfo=None),
    )


# ── 1. Most ordered products ──────────────────────────────────────────────────
@router.get("/most-ordered/{seller_id}")
async def most_ordered(seller_id: str, range: str = Query("today")):
    cache_key = f"analytics:most-ordered:{seller_id}:{range}"

    if range != "today":
        cached = await cache.get(cache_key)
        if cached:
            return {"data": json.loads(cached), "cached": True}

    start, end = get_range_bounds(range)

    pipeline = base_pipeline(seller_id, start, end) + [
        {"$group": {
            "_id":      "$items.name",
            "count":    {"$sum": "$items.quantity"},
            "revenue":  {"$sum": {"$multiply": ["$items.price", "$items.quantity"]}},
            "category": {"$last": {"$ifNull": ["$productInfo.category", "Uncategorized"]}}
        }},
        {"$sort": {"count": -1}},
        {"$limit": 10},
        {"$project": {
            "_id":      0,
            "name":     "$_id",
            "count":    1,
            "revenue":  1,
            "category": 1,
        }}
    ]

    result = await db.orders.aggregate(pipeline).to_list(None)

    if range != "today":
        await cache.setex(cache_key, cache_ttl(), json.dumps(result, default=str))  # fixed: sextex → setex

    return {"data": result, "cached": False}


# ── 2. Highest revenue products ───────────────────────────────────────────────
@router.get("/highest-revenue/{seller_id}")
async def highest_revenue(seller_id: str, range: str = Query("today")):
    cache_key = f"analytics:highest-revenue:{seller_id}:{range}"

    if range != "today":
        cached = await cache.get(cache_key)
        if cached:
            return {"data": json.loads(cached), "cached": True}

    start, end = get_range_bounds(range)

    pipeline = base_pipeline(seller_id, start, end) + [
        {"$group": {
            "_id":      "$items.name",
            "revenue":  {"$sum": {"$multiply": ["$items.price", "$items.quantity"]}},  # fixed: qunatity typo
            "count":    {"$sum": "$items.quantity"},
            "category": {"$last": {"$ifNull": ["$productInfo.category", "Uncategorized"]}}  # fixed: missing $
        }},
        {"$sort": {"revenue": -1}},
        {"$limit": 10},
        {"$project": {
            "_id":      0,
            "name":     "$_id",
            "revenue":  1,
            "count":    1,
            "category": 1
        }}
    ]

    result = await db.orders.aggregate(pipeline).to_list(None)

    if range != "today":
        await cache.setex(cache_key, cache_ttl(), json.dumps(result, default=str))

    return {"data": result, "cached": False}




import asyncio

#Fastest growing product
@router.get("/fastest-growing/{seller_id}")
async def fastest_growing(seller_id: str, range: str = Query("week")):
    cache_key = f"analytics:fastest-growing:{seller_id}:{range}"

    if range != "today":
        cached = await cache.get(cache_key)
        if cached:
            return {"data": json.loads(cached), "cached": True}

    curr_start, curr_end = get_range_bounds(range)
    prev_start, prev_end = get_prev_bounds(range)

    curr_pipeline = base_pipeline(seller_id, curr_start, curr_end) + [
        {"$group": {
            "_id":      "$items.name",
            "count":    {"$sum": "$items.quantity"},
            "category": {"$last": {"$ifNull": ["$productInfo.category", "Uncategorized"]}}
        }}
    ]

    prev_pipeline = base_pipeline(seller_id, prev_start, prev_end) + [
        {"$group": {
            "_id":   "$items.name",
            "count": {"$sum": "$items.quantity"}   # fixed: comma → colon
        }}
    ]

    curr_list, prev_list = await asyncio.gather(
        db.orders.aggregate(curr_pipeline).to_list(None),
        db.orders.aggregate(prev_pipeline).to_list(None),
    )

    curr_map = {r["_id"]: r for r in curr_list}
    prev_map = {r["_id"]: r["count"] for r in prev_list}

    result = []
    for name, curr in curr_map.items():
        prev_count = prev_map.get(name, 0)
        if prev_count == 0:
            continue
        growth = round(((curr["count"] - prev_count) / prev_count) * 100, 1)
        if growth <= 0:
            continue
        result.append({
            "name":         name,
            "growth":       growth,
            "currentCount": curr["count"],
            "prevCount":    prev_count,
            "category":     curr.get("category", "Uncategorized"),
        })

    # fixed: sort and slice OUTSIDE the for loop
    result.sort(key=lambda x: x["growth"], reverse=True)
    result = result[:10]

    if range != "today":
        await cache.setex(cache_key, cache_ttl(), json.dumps(result, default=str))  # fixed: sextex → setex

    return {"data": result, "cached": False}


# Declining Products
@router.get("/declining/{seller_id}")
async def declining(seller_id: str, range: str = Query("week")):
    cache_key = f"analytics:declining:{seller_id}:{range}"

    if range != "today":
        cached = await cache.get(cache_key)
        if cached:
            return {"data": json.loads(cached), "cached": True}

    curr_start, curr_end = get_range_bounds(range)
    prev_start, prev_end = get_prev_bounds(range)

    curr_pipeline = base_pipeline(seller_id, curr_start, curr_end) + [
        {"$group": {
            "_id":      "$items.name",
            "count":    {"$sum": "$items.quantity"},
            "category": {"$last": {"$ifNull": ["$productInfo.category", "Uncategorized"]}}
        }}
    ]

    prev_pipeline = base_pipeline(seller_id, prev_start, prev_end) + [
        {"$group": {
            "_id":   "$items.name",
            "count": {"$sum": "$items.quantity"}
        }}
    ]

    curr_list, prev_list = await asyncio.gather(
        db.orders.aggregate(curr_pipeline).to_list(None),
        db.orders.aggregate(prev_pipeline).to_list(None),
    )

    curr_map = {r["_id"]: r for r in curr_list}
    prev_map = {r["_id"]: r["count"] for r in prev_list}

    result = []
    for name, prev_count in prev_map.items():
        curr       = curr_map.get(name)
        curr_count = curr["count"] if curr else 0
        if prev_count == 0:
            continue
        growth = round(((curr_count - prev_count) / prev_count) * 100, 1)
        if growth >= 0:
            continue
        result.append({
            "name":         name,
            "decline":      growth,
            "currentCount": curr_count,   # fixed: cuurentCount typo
            "prevCount":    prev_count,
            "category":     curr.get("category", "Uncategorized") if curr else "Uncategorized",
        })

    result.sort(key=lambda x: x["decline"])
    result = result[:10]

    if range != "today":
        await cache.setex(cache_key, cache_ttl(), json.dumps(result, default=str))

    return {"data": result, "cached": False}
