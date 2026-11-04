"""Prints the latest ERP batch log entries (preview DB)."""
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.core import db, tables


async def main():
    rows = await db.all(select(tables.erp_batches).order_by(tables.erp_batches.c.started_at.desc()).limit(5))
    print(" ".join(f"{b['entity']}:{b['status']}:{b.get('count')}:{(b.get('error') or '')[:150]}" for b in rows))
    await db.close()

asyncio.run(main())
