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





# ── 1. Revenue by table ───────────────────────────────────────────────────────
@router.get("/table-revenue/{seller_id}")
async def table_revenue(seller_id: str, range: str = Query("today")):
    cache_key = f"analytics:table-revenue:{seller_id}:{range}"

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
        {"$group": {
            "_id":       "$tableId",
            # pick the last non-null tableName (new orders have it, old ones don't)
            "tableName": {"$last": {"$ifNull": ["$tableName", None]}},
            "revenue":   {"$sum": "$total"},
            "orders":    {"$sum": 1}
        }},
        {"$project": {
            "_id":       0,
            "tableId":   {"$toString": "$_id"},
            "tableName": {"$ifNull": ["$tableName", "Unknown Table"]},
            "revenue":   1,
            "orders":    1
        }},
        {"$sort": {"revenue": -1}}
    ]

    result = await db.orders.aggregate(pipeline).to_list(None)

    print(f"[table-revenue] seller={seller_id} range={range} count={len(result)}")
    for r in result:
        print(f"  tableId={r.get('tableId')} tableName={r.get('tableName')} revenue={r.get('revenue')}")

    if range != "today":
        await cache.setex(cache_key, cache_ttl(), json.dumps(result, default=str))

    return {"data": result, "cached": False}


# ── 2. Orders by table ────────────────────────────────────────────────────────
@router.get("/table-orders/{seller_id}")
async def table_orders(seller_id: str, range: str = Query("today")):
    cache_key = f"analytics:table-orders:{seller_id}:{range}"

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
        {"$group": {
            "_id":      "$tableId",
            "tableName": {"$last": {"$ifNull": ["$tableName", None]}},
            "orders":   {"$sum": 1},
            "sessions": {"$addToSet": "$sessionId"}
        }},
        {"$project": {
            "_id":       0,
            "tableId":   {"$toString": "$_id"},
            "tableName": {"$ifNull": ["$tableName", "Unknown Table"]},
            "orders":    1,
            "sessions":  {"$size": "$sessions"}
        }},
        {"$sort": {"orders": -1}}
    ]

    result = await db.orders.aggregate(pipeline).to_list(None)

    print(f"[table-orders] seller={seller_id} range={range} count={len(result)}")
    for r in result:
        print(f"  tableId={r.get('tableId')} tableName={r.get('tableName')} orders={r.get('orders')} sessions={r.get('sessions')}")

    if range != "today":
        await cache.setex(cache_key, cache_ttl(), json.dumps(result, default=str))

    return {"data": result, "cached": False}

# 3. Most active tables by sessions
@router.get("/active-tables/{seller_id}")
async def active_tables(seller_id: str, range: str = Query("today")):
    cache_key = f"analytics:active-tables:{seller_id}:{range}"

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

        # stage 1 — group by table+session to get per-session time boundaries
        {"$group": {
            "_id": {
                "tableId":   "$tableId",
                "tableName": "$tableName",
                "sessionId": "$sessionId"
            },
            "sessionStart": {"$min": "$createdAt"},
            "sessionEnd":   {"$max": "$createdAt"}
        }},

        # stage 2 — group by table to count sessions and avg duration
        {"$group": {
            "_id":       "$_id.tableId",
            "tableName": {"$last": {"$ifNull": ["$_id.tableName", None]}},
            "sessions":  {"$sum": 1},
            "avgDurationMs": {
                "$avg": {"$subtract": ["$sessionEnd", "$sessionStart"]}
            }
        }},

        {"$project": {
            "_id":       0,
            "tableId":   {"$toString": "$_id"},
            "tableName": {"$ifNull": ["$tableName", "Unknown Table"]},
            "sessions":  1,
            # ms → minutes
            "avgDuration": {
                "$toInt": {"$divide": [{"$ifNull": ["$avgDurationMs", 0]}, 60000]}
            }
        }},
        {"$sort": {"sessions": -1}}
    ]

    result = await db.orders.aggregate(pipeline).to_list(None)

    if range != "today":
        await cache.setex(cache_key, cache_ttl(), json.dumps(result, default=str))

    return {"data": result, "cached": False}

#4 Average order value by table
@router.get("/avg-order-by-table/{seller_id}")
async def avg_order_by_table(seller_id: str, range: str = Query("today")):
    cache_key = f"analytics:avg-order-by-table:{seller_id}:{range}"

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
        {"$group": {
            "_id":          "$tableId",
            "tableName":    {"$last": {"$ifNull": ["$tableName", None]}},
            "totalRevenue": {"$sum": "$total"},
            "orders":       {"$sum": 1}
        }},
        {"$project": {
            "_id":       0,
            "tableId":   {"$toString": "$_id"},
            "tableName": {"$ifNull": ["$tableName", "Unknown Table"]},
            "orders":    1,
            "avgOrderValue": {
                "$cond": [
                    {"$gt": ["$orders", 0]},
                    {"$divide": ["$totalRevenue", "$orders"]},
                    0
                ]
            }
        }},
        {"$sort": {"avgOrderValue": -1}}
    ]

    result = await db.orders.aggregate(pipeline).to_list(None)

    if range != "today":
        await cache.setex(cache_key, cache_ttl(), json.dumps(result, default=str))

    return {"data": result, "cached": False}
