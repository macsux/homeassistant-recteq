"""End-to-end test of the discovery + auth pipeline.

Exercises the same paths the integration uses at config-flow time, with
no Home Assistant required:

  1. Login (email + password) → sid + ecode
  2. tuya.m.location.list → group ids
  3. tuya.m.my.group.device.list (gid in URL) → devices with localKey
  4. UDP-scan LAN for the current local IP of each device

Useful for sanity-checking your account works (and seeing what your
grill's productId is, if you need to file an issue for an unsupported
model).

Run:
  python -m venv .venv && .venv/bin/pip install aiohttp pycryptodome tinytuya
  .venv/bin/python test_login.py <email> <password>
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "custom_components"))

import aiohttp  # noqa: E402

from recteq import oem_api  # noqa: E402
from recteq.const import PRODUCT_DP_MAPS  # noqa: E402


async def main(email: str, password: str) -> int:
    async with aiohttp.ClientSession() as session:
        client = oem_api.OemApiClient(session)
        try:
            sess = await client.login(email, password)
        except oem_api.OemAuthError as exc:
            print(f"AUTH FAIL: {exc}")
            return 1
        except oem_api.OemApiError as exc:
            print(f"API FAIL: {exc}")
            return 2
        print(f"login ok  uid={sess.uid}")

        try:
            devices = await client.list_devices()
        except oem_api.OemApiError as exc:
            print(f"list_devices FAIL: {exc}")
            return 3

        print(f"\nfound {len(devices)} device(s) on the account:")
        for d in devices:
            mark = "✓" if d.product_id in PRODUCT_DP_MAPS else "✗"
            print(
                f"  [{mark}] {d.name!r:<30}  id={d.dev_id}  product={d.product_id}  "
                f"localKey={'<got>' if d.local_key else '<EMPTY>'}"
            )

        supported = [d for d in devices if d.product_id in PRODUCT_DP_MAPS]
        if not supported:
            print("\nno supported RecTeq grills on this account")
            return 4

        # Resolve LAN IP for each. Will succeed on Linux/HAOS where UDP
        # broadcasts traverse; falls back to <not-found> on Docker Desktop
        # for Mac/Windows where it doesn't.
        print("\nLAN-scanning for current device IPs (4s)...")
        for d in supported:
            ip = await oem_api.discover_lan_ip(d.dev_id, timeout=4.0)
            print(f"  {d.name!r}  ip={ip or '<not found, would prompt for manual entry>'}")
        return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: test_login.py <email> <password>")
        sys.exit(1)
    sys.exit(asyncio.run(main(sys.argv[1], sys.argv[2])))
