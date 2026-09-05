from fastapi import APIRouter
from bson import ObjectId
from db import db, cache
from datetime import datetime, timedelta, timezone
import json

router = APIRouter()


async def fetch_day_stats(seller_id: str, start: datetime, end: datetime) -> dict:
    print(f"[today] querying MongoDB for {start} to {end}")
    pipeline = [
        {"$match": {
            "seller":    ObjectId(seller_id),
            "createdAt": {"$gte": start, "$lt": end}
        }},
        {"$group": {
            "_id":     None,
            "revenue": {"$sum": "$total"},
            "orders":  {"$sum": 1}
        }}
    ]
    result = await db.orders.aggregate(pipeline).to_list(None)
    data   = result[0] if result else {}
    out    = {"revenue": round(data.get("revenue", 0), 2), "orders": data.get("orders", 0)}
    print(f"[today] MongoDB result: {out}")
    return out


def calc_growth(today_val: float, yest_val: float) -> float:
    if yest_val == 0:
        return 100.0 if today_val > 0 else 0.0
    return round(((today_val - yest_val) / yest_val) * 100, 1)


@router.get("/today/{seller_id}")
async def today(seller_id: str):
    print(f"[today] request for seller: {seller_id}")
    now         = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end   = today_start + timedelta(days=1)
    yest_start  = today_start - timedelta(days=1)

    # today — always fresh, no cache
    print("[today] fetching today from MongoDB (no cache)")
    today_data = await fetch_day_stats(seller_id, today_start, today_end)

    # yesterday — cache 48h
    yest_key    = f"analytics:yesterday:utc:{seller_id}:{yest_start.date()}"
    cached_yest = await cache.get(yest_key)

    if cached_yest:
        print(f"[today] yesterday cache HIT for key: {yest_key}")
        yest_data = json.loads(cached_yest)
    else:
        print(f"[today] yesterday cache MISS — querying MongoDB, key: {yest_key}")
        yest_data = await fetch_day_stats(seller_id, yest_start, today_start)
        await cache.setex(yest_key, 48 * 3600, json.dumps(yest_data))
        print(f"[today] yesterday cached for 48h: {yest_data}")

    revenue_growth = calc_growth(today_data["revenue"], yest_data["revenue"])
    orders_growth  = calc_growth(today_data["orders"],  yest_data["orders"])

    print(f"[today] revenueGrowth={revenue_growth}% ordersGrowth={orders_growth}%")

    return {
        "data": {
            "today":         today_data,
            "yesterday":     yest_data,
            "revenueGrowth": revenue_growth,
            "ordersGrowth":  orders_growth,
        }
    }
