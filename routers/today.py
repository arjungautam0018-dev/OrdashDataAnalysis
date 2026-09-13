from fastapi import APIRouter
from bson import ObjectId
from db import db, cache
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import json

router  = APIRouter()
NPT     = ZoneInfo("Asia/Kathmandu")  # UTC+5:45


def get_day_boundaries(offset_days: int = 0):
    """Return UTC-aware start and end of a day in Nepal time."""
    now_npt      = datetime.now(NPT)
    target_npt   = (now_npt - timedelta(days=offset_days)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    next_day_npt = target_npt + timedelta(days=1)
    # convert to UTC for MongoDB query
    return target_npt.astimezone(ZoneInfo("UTC")), next_day_npt.astimezone(ZoneInfo("UTC"))


async def fetch_day_stats(seller_id: str, start: datetime, end: datetime) -> dict:
    print(f"[today] querying MongoDB {start} → {end}")
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
    print(f"[today] result: {out}")
    return out


def calc_growth(today_val: float, yest_val: float) -> float:
    if yest_val == 0:
        return 100.0 if today_val > 0 else 0.0
    return round(((today_val - yest_val) / yest_val) * 100, 1)


@router.get("/today/{seller_id}")
async def today(seller_id: str):
    print(f"[today] request for seller: {seller_id}")

    today_start, today_end = get_day_boundaries(offset_days=0)
    yest_start,  yest_end  = get_day_boundaries(offset_days=1)

    print(f"[today] today NPT window (UTC): {today_start} → {today_end}")
    print(f"[today] yesterday NPT window (UTC): {yest_start} → {yest_end}")

    # today — always fresh, no cache
    today_data = await fetch_day_stats(seller_id, today_start, today_end)

    # yesterday — cache until end of today in NPT (so it resets daily)
    yest_date   = (datetime.now(NPT) - timedelta(days=1)).strftime("%Y-%m-%d")
    yest_key    = f"analytics:yesterday:npt:{seller_id}:{yest_date}"
    cached_yest = await cache.get(yest_key)

    if cached_yest:
        print(f"[today] yesterday cache HIT: {yest_key}")
        yest_data = json.loads(cached_yest)
    else:
        print(f"[today] yesterday cache MISS: {yest_key}")
        yest_data = await fetch_day_stats(seller_id, yest_start, yest_end)
        # cache until midnight Nepal time today
        now_npt      = datetime.now(NPT)
        midnight_npt = (now_npt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        ttl          = int((midnight_npt - now_npt).total_seconds())
        await cache.setex(yest_key, ttl, json.dumps(yest_data))
        print(f"[today] yesterday cached for {ttl}s: {yest_data}")

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
