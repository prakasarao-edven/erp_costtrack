"""Try candidate Transaction Source / Document / Document Entry combos for one labor cost.
Stops at the first accepted one (that one creates a single unprocessed cost row in Oracle)."""
import asyncio
import json
import sys

import httpx
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")
from erp import get_adapter  # noqa: E402

CANDIDATES = [("3rd party Labor", "Timecard", "Straight Time"),
              ("Third Party Labor", "Timecard", "Straight Time"),
              (" Misc_Third party source uncosted", " Misc_Third party document uncosted", " Misc_Third party doc entry uncosted")]
BASE = json.loads(sys.argv[1])


async def main():
    a = get_adapter()
    async with httpx.AsyncClient(auth=a.auth, timeout=100) as c:
        for src, doc, entry in CANDIDATES:
            body = {**BASE, "TransactionSource": src, "Document": doc, "DocumentEntry": entry}
            r = await c.post(a._url("fscmRestApi", "unprocessedProjectCosts"), json=body, headers={"Content-Type": "application/json"})
            print(src, "->", r.status_code, r.text[:400] if not r.is_success else "")
            if r.is_success:
                d = r.json()
                print(json.dumps({k: d.get(k) for k in ["UnprocessedTransactionReferenceId", "StatusCode", "Status", "TransactionSource", "Document",
                                                         "DocumentEntry", "ProjectNumber", "TaskNumber", "ExpenditureType", "PersonName",
                                                         "PersonNumber", "Quantity", "ExpenditureOrganization", "OriginalTransactionReference"]}))
                return

asyncio.run(main())
