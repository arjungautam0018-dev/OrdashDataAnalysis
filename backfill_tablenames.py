from motor.motor_asyncio import AsyncIOMotorClient
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

mongo = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db    = mongo[os.getenv("MONGO_DB", "test")]

async def backfill():
    orders_missing = await db.orders.distinct(
        "seller",
        {"tableName": {"$exists": False}}
    )
    print(f"Sellers with missing tableName: {len(orders_missing)}")

    for seller_id in orders_missing:
        hotel = await db.hoteltables.find_one({"seller": seller_id})
        if not hotel:
            print(f"  No hoteltables doc for seller {seller_id}, skipping")
            continue

        table_map = {str(t["_id"]): t["name"] for t in hotel.get("tables", [])}
        print(f"  Seller {seller_id} — {len(table_map)} tables: {table_map}")

        updated = 0
        async for order in db.orders.find(
            {"seller": seller_id, "tableName": {"$exists": False}},
            {"_id": 1, "tableId": 1}
        ):
            table_name = table_map.get(str(order["tableId"]))
            if table_name:
                await db.orders.update_one(
                    {"_id": order["_id"]},
                    {"$set": {"tableName": table_name}}
                )
                updated += 1
            else:
                print(f"    tableId {order['tableId']} not found in table_map")

        print(f"  Backfilled {updated} orders for seller {seller_id}")

    print("Done.")

asyncio.run(backfill())
