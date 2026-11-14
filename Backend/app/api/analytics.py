"""
Analytics API — reads the call history stored in SQLite.

  GET /api/analytics/summary       KPIs, intents, calls per day, knowledge gaps
  GET /api/analytics/calls         recent calls with their post-call analysis
  GET /api/analytics/calls/{id}    one call with every turn
"""
import asyncio
from fastapi import APIRouter, HTTPException
from app.db import store

router = APIRouter(prefix="/api/analytics")


@router.get("/summary")
async def summary():
    return await asyncio.to_thread(store.analytics_summary)


@router.get("/calls")
async def calls(limit: int = 50):
    return {"calls": await asyncio.to_thread(store.list_calls, max(1, min(limit, 200)))}


@router.get("/calls/{call_id}")
async def call_detail(call_id: str):
    call = await asyncio.to_thread(store.get_call, call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    return call
