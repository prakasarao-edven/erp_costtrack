"""Prints the latest ERP batch log entries (preview DB)."""
import asyncio
import os

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")
db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


async def main():
    rows = await db.erp_batches.find({}, {"_id": 0}).sort("started_at", -1).to_list(5)
    print(" ".join(f"{b['entity']}:{b['status']}:{b.get('count')}:{(b.get('error') or '')[:150]}" for b in rows))

asyncio.run(main())
