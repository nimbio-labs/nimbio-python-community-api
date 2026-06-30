"""Asynchronous quickstart.

    export NIMBIO_API_KEY=nimbio_test_xxxxxxxxxxxxxxxxxxxxxx
    export NIMBIO_ENV=dev
    python examples/async_quickstart.py
"""

import asyncio

from nimbio_community_api import APIError, AsyncNimbioClient


async def main() -> None:
    async with AsyncNimbioClient() as client:  # reads NIMBIO_API_KEY / NIMBIO_ENV
        print(f"Mode: {client.mode}  Base URL: {client.base_url}")

        me = await client.me()
        print(f"Account: {me.account_id} (key '{me.key.name}')")

        gate = await client.community.gate_status()
        for latch in gate.latches:
            print(f"  - {latch.latch_name}: {latch.status}")

        # Walk every page of the access log without managing pagination yourself.
        count = 0
        async for _row in client.community.iter_access_log():
            count += 1
        print(f"Access-log rows (all pages): {count}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except APIError as e:
        raise SystemExit(f"API error [{e.status_code}] {e.code}: {e.message}") from e
