from fastapi import APIRouter, Query
from bson import ObjectId
from db import db, cache
from datetime import datetime, timedelta, timezone
import json

router = APIRouter()

# Nepal is UTC+5:45
NPT_OFFSET   = timedelta(hours=5, minutes=45)
NPT_TZ       = timezone(NPT_OFFSET)
NPT_OFFSET_MS = int(NPT_OFFSET.total_seconds() * 1000)   # for $dateToString timezone offset


def now_npt() -> datetime:
    """Current time in Nepal (timezone-aware)."""
    return datetime.now(tz=NPT_TZ)


def get_range_bounds(range: str):
    """Returns (start_utc, end_utc, date_format, is_today)."""
    npt_now   = now_npt()
    npt_today = npt_now.replace(hour=0, minute=0, second=0, microsecond=0)

    # convert NPT midnight → UTC for DB queries
    utc_today = npt_today.astimezone(timezone.utc).replace(tzinfo=None)
    utc_now   = npt_now.astimezone(timezone.utc).replace(tzinfo=None)

    if range == "today":
        return utc_today, utc_now, None, True          # format handled separately

    elif range == "week":
        this_week_start = npt_today - timedelta(days=npt_today.weekday())
        start_npt = this_week_start - timedelta(days=7)
        end_npt   = this_week_start
        return (
            start_npt.astimezone(timezone.utc).replace(tzinfo=None),
            end_npt.astimezone(timezone.utc).replace(tzinfo=None),
            "%Y-%m-%d",
            False,
        )

    elif range == "month":
        this_month_start = npt_today.replace(day=1)
        if this_month_start.month == 1:
            prev_month = this_month_start.replace(year=this_month_start.year - 1, month=12)
        else:
            prev_month = this_month_start.replace(month=this_month_start.month - 1)
        return (
            prev_month.astimezone(timezone.utc).replace(tzinfo=None),
            this_month_start.astimezone(timezone.utc).replace(tzinfo=None),
            "%Y-%m-%d",
            False,
        )

    elif range == "year":
        start = npt_today.replace(year=npt_today.year - 1, month=1, day=1)
        end   = npt_today.replace(month=1, day=1)
        return (
            start.astimezone(timezone.utc).replace(tzinfo=None),
            end.astimezone(timezone.utc).replace(tzinfo=None),
            "%Y-%m",
            False,
        )

    return utc_today, utc_now, None, True


def build_cumulative_today(raw: list) -> list:
    """
    raw: [{"label": "HH:00", "revenue": X}, ...]  — only hours that had orders
    Returns 24 slots (00:00–23:00) with cumulative revenue.
    Fills missing hours with the previous cumulative value so the line never dips.
    """
    # bucket per-hour revenue
    by_hour = {r["label"]: r["revenue"] for r in raw}

    result    = []
    running   = 0
    npt_now   = now_npt()
    current_h = npt_now.hour   # don't plot future hours

    for h in range(0, 24):
        label = f"{h:02d}:00"
        running += by_hour.get(label, 0)
        result.append({"label": label, "revenue": running, "orders": 0})
        if h >= current_h:
            break   # stop at current hour, no future data

    return result


@router.get("/revenue/{seller_id}")
async def revenue(seller_id: str, range: str = Query("today")):
    cache_key = f"analytics:revenue:{seller_id}:{range}"

    if range != "today":
        cached = await cache.get(cache_key)
        if cached:
            return {"data": json.loads(cached), "cached": True}

    start, end, date_format, is_today = get_range_bounds(range)

    if is_today:
        # group by Nepal local hour using timezone offset in $dateToString
        pipeline = [
            {"$match": {
                "seller":    ObjectId(seller_id),
                "status":    "done",
                "createdAt": {"$gte": start, "$lt": end}
            }},
            {"$group": {
                "_id": {
                    "$dateToString": {
                        "format":   "%H:00",
                        "date":     "$createdAt",
                        "timezone": "+05:45"      # Nepal UTC+5:45 as numeric offset (avoids olson db requirement)
                    }
                },
                "revenue": {"$sum": "$total"},
                "orders":  {"$sum": 1}
            }},
            {"$sort": {"_id": 1}},
            {"$project": {"_id": 0, "label": "$_id", "revenue": 1, "orders": 1}}
        ]
        raw    = await db.orders.aggregate(pipeline).to_list(None)
        result = build_cumulative_today(raw)

    else:
        pipeline = [
            {"$match": {
                "seller":    ObjectId(seller_id),
                "status":    "done",
                "createdAt": {"$gte": start, "$lt": end}
            }},
            {"$group": {
                "_id": {
                    "$dateToString": {
                        "format":   date_format,
                        "date":     "$createdAt",
                        "timezone": "+05:45"      # Nepal UTC+5:45
                    }
                },
                "revenue": {"$sum": "$total"},
                "orders":  {"$sum": 1}
            }},
            {"$sort": {"_id": 1}},
            {"$project": {"_id": 0, "label": "$_id", "revenue": 1, "orders": 1}}
        ]
        result = await db.orders.aggregate(pipeline).to_list(None)

        now      = datetime.now()
        midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        ttl      = int((midnight - now).total_seconds())
        await cache.setex(cache_key, ttl, json.dumps(result, default=str))

    return {"data": result, "cached": False}
