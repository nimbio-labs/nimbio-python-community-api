"""Synchronous quickstart.

Run with a test key so nothing real happens:

    export NIMBIO_API_KEY=nimbio_test_xxxxxxxxxxxxxxxxxxxxxx
    export NIMBIO_ENV=dev          # optional: prod (default) | dev | local
    python examples/sync_quickstart.py
"""

from nimbio_community_api import APIError, NimbioClient


def main() -> None:
    with NimbioClient() as client:  # reads NIMBIO_API_KEY / NIMBIO_ENV
        print(f"Mode: {client.mode}  Base URL: {client.base_url}")

        health = client.health()
        print(f"Backend: ok={health.ok} wamp={health.wamp}")

        me = client.me()
        print(f"Account: {me.account_id} (key '{me.key.name}')")
        print(f"Usage this month: {me.key.month_count}/{me.key.month_limit}")

        print("\nGate status:")
        for latch in client.community.gate_status().latches:
            offline = " [offline]" if latch.offline else ""
            print(f"  - {latch.latch_name}: {latch.status}{offline} ({latch.latch_id})")

        print("\nMembers:")
        for member in client.community.members().accepted:
            print(f"  - {member.full_name} ({member.phone_number})")

        # Side-effecting with a live key; simulated with a test key.
        # Uncomment and supply a real latch id to try it:
        # result = client.community.open("LATCH_ID", note="example")
        # print("Open result:", result.result)


if __name__ == "__main__":
    try:
        main()
    except APIError as e:
        raise SystemExit(f"API error [{e.status_code}] {e.code}: {e.message}") from e
