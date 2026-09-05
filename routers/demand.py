from fastapi import APIRouter
from bson import ObjectId
from db import db, cache
import json

router = APIRouter()

@router.get("/demand/{seller_id}")
async def demand(seller_id: str):
    # TODO: train model on historical order data, return 7-day forecast
    # Steps to implement:
    # 1. fetch last 90 days of daily order counts from MongoDB
    # 2. fit a simple linear regression or ARIMA model using pandas + scikit-learn
    # 3. predict next 7 days
    # 4. cache result for 24 hours
    return {
        "data":    [],
        "message": "Demand forecast not yet implemented. Add model in routers/demand.py"
    }
