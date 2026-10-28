"""Read-only Oracle probe: python3 oracle_probe.py <service> <resource> '<json params>'"""
import asyncio
import json
import sys

import httpx
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")
from erp import get_adapter  # noqa: E402


async def main():
    a = get_adapter()
    service, resource = sys.argv[1], sys.argv[2]
    params = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
    async with httpx.AsyncClient(auth=a.auth, timeout=100) as c:
        r = await c.get(a._url(service, resource), params={"onlyData": "true", **params})
    print(r.status_code)
    try:
        body = r.json()
        print(json.dumps(body.get("items", body), indent=0)[:3000])
    except ValueError:
        print(r.text[:1000])

asyncio.run(main())
