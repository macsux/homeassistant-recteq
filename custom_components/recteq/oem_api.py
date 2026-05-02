"""Async client for RecTeq's OEM Tuya API.

Two-step flow: login with email/password to obtain a session, then
`thing.m.device.get` for each device to retrieve its `localKey`. The localKey
is what lets us decrypt the device's local-network traffic — without it the
LAN-discovered device is opaque.

Algorithm details (signing, AES-GCM payload encryption, key derivation) were
recovered by decompiling `libthing_security.so` from the Android app. Comments
on the trickier bits document why a particular byte slice or HMAC ordering
matters; nothing here is original cryptography, just a reimplementation of
Tuya's stable algorithms in pure Python.
"""
from __future__ import annotations

import asyncio
import base64
import gzip
import hashlib
import hmac as hmac_mod
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass

import aiohttp
from Crypto.Cipher import AES

from .const import (
    API_BASE,
    API_PATH,
    APP_VERSION,
    CH_KEY,
    DEVICE_CORE_VERSION,
    HMAC_KEY,
    LANG,
    OEM_ACCESS_ID,
    OS_SYSTEM,
    PARTNER_IDENTITY,
    PLATFORM,
    SDK_VERSION,
    SIGN_WHITELIST,
    TTID,
)

_LOGGER = logging.getLogger(__name__)


class OemApiError(Exception):
    """OEM API returned an error response or refused the request."""


class OemAuthError(OemApiError):
    """Login was rejected — wrong email/password or account locked."""


@dataclass
class CloudDevice:
    """Subset of `thing.m.device.get` fields we actually use."""
    dev_id: str
    name: str
    product_id: str
    local_key: str
    online: bool
    mac: str | None
    ip: str | None  # public WAN IP per the cloud — usually NOT the LAN IP


@dataclass
class Session:
    """Result of a successful login."""
    sid: str
    uid: str
    ecode: str
    partner_identity: str


# ── Crypto + signing primitives ──────────────────────────────────────────


def _md5hex(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()


def _swap_sign_string(h: str) -> str:
    """Tuya's quirky 32-char hex shuffle: h[8:16] + h[0:8] + h[24:32] + h[16:24]."""
    return h[8:16] + h[0:8] + h[24:32] + h[16:24]


def _build_sign_string(params: dict) -> str:
    """Canonical key=value||key=value||... over SIGN_WHITELIST keys, sorted."""
    parts = []
    for key in sorted(params):
        if key not in SIGN_WHITELIST:
            continue
        value = params.get(key, "")
        if not value:
            continue
        if key == "postData":
            value = _swap_sign_string(_md5hex(value))
        parts.append(f"{key}={value}")
    return "||".join(parts)


def _hmac_sha256_hex(key: str, msg: str) -> str:
    return hmac_mod.new(key.encode(), msg.encode(), hashlib.sha256).hexdigest()


def _get_encrypto_key(request_id: str, ecode: str | None) -> bytes:
    """Derive AES-128 key for et=3 request/response payload encryption.

    Algorithm (confirmed via libthing_security.so disasm):
        msg = HMAC_KEY [ + "_" + ecode ]
        digest = HMAC-SHA256(key=requestId, msg)
        return digest_hex[:16] as ASCII bytes
    """
    msg = HMAC_KEY + ("_" + ecode if ecode else "")
    return _hmac_sha256_hex(request_id, msg)[:16].encode("ascii")


def _aes_gcm_encrypt(key: bytes, plaintext: bytes) -> bytes:
    nonce = os.urandom(12)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    ct, tag = cipher.encrypt_and_digest(plaintext)
    return nonce + ct + tag


def _aes_gcm_decrypt(key: bytes, blob: bytes) -> bytes:
    nonce, ct_tag = blob[:12], blob[12:]
    ct, tag = ct_tag[:-16], ct_tag[-16:]
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    return cipher.decrypt_and_verify(ct, tag)


# ── Client ───────────────────────────────────────────────────────────────


class OemApiClient:
    """Stateless until `login()` succeeds; thereafter calls require a valid sid."""

    def __init__(self, session: aiohttp.ClientSession, device_id: str | None = None) -> None:
        self._http = session
        # `deviceId` is the *Android* installation UUID, not the BBQ device id.
        # We persist a stable random one across the entry's lifetime so the
        # OEM API isn't re-introduced to a brand-new "device" on every refresh.
        self._android_device_id = device_id or uuid.uuid4().hex
        self._sid: str | None = None
        self._ecode: str | None = None
        self._uid: str | None = None
        self._partner_identity: str | None = None

    # Properties exposed after login
    @property
    def session_obj(self) -> Session:
        if not self._sid:
            raise OemApiError("not logged in")
        return Session(self._sid, self._uid or "", self._ecode or "",
                       self._partner_identity or PARTNER_IDENTITY)

    # ── Public API ──────────────────────────────────────────────────────

    async def login(self, email: str, password: str, country_code: str = "1") -> Session:
        """Email/password login. Returns Session, caches sid+ecode internally."""
        post = {
            "countryCode": country_code,
            "email": email,
            "passwd": _md5hex(password),
            "token": "",
            "ifencrypt": 0,
            "options": '{"group": 1}',
        }
        try:
            resp = await self._call("thing.m.user.email.password.login", post)
        except OemApiError as exc:
            # Tuya returns specific error codes for bad creds — surface as auth error
            if "USER_PASSWD_WRONG" in str(exc) or "USER_NOT_EXIST" in str(exc):
                raise OemAuthError(str(exc)) from exc
            raise
        result = resp.get("result", {}) or {}
        self._sid = result.get("sid")
        self._uid = result.get("uid")
        self._ecode = result.get("ecode")
        self._partner_identity = result.get("partnerIdentity") or PARTNER_IDENTITY
        if not self._sid:
            raise OemAuthError("Login response missing sid")
        return self.session_obj

    async def list_devices(self) -> list[CloudDevice]:
        """Enumerate devices on the user's account.

        Two-step: list locations (homes) → list devices for each location's
        groupId. The grid id rides as a URL param (`gid=`), NOT in postData —
        otherwise the endpoint returns USER_GROUP_ID_IS_BLANK.
        """
        loc_resp = await self._call(
            "tuya.m.location.list", {}, api_version="2.0", with_session=True
        )
        locations = loc_resp.get("result", []) or []
        gids = [
            str(loc.get("groupId") or loc.get("gid"))
            for loc in locations
            if loc.get("groupId") or loc.get("gid")
        ]

        devices: list[CloudDevice] = []
        seen: set[str] = set()
        for gid in gids:
            resp = await self._call_with_gid(
                "tuya.m.my.group.device.list", {}, gid,
                api_version="1.0", with_session=True,
            )
            for it in resp.get("result", []) or []:
                dev_id = it.get("devId") or it.get("uuid") or ""
                if not dev_id or dev_id in seen:
                    continue
                seen.add(dev_id)
                devices.append(CloudDevice(
                    dev_id=dev_id,
                    name=(it.get("name") or "").strip(),
                    product_id=it.get("productId") or "",
                    local_key=it.get("localKey") or "",
                    online=bool(it.get("isOnline")),
                    mac=it.get("mac"),
                    ip=it.get("ip"),
                ))
        return devices

    async def _call_with_gid(
        self, api: str, post: dict, gid: str,
        api_version: str = "1.0", with_session: bool = True,
    ) -> dict:
        """`_call` variant that injects `gid` into URL params (not postData)."""
        orig = self._base_params

        def patched(api_name: str, api_version_: str) -> dict:
            params = orig(api_name, api_version_)
            params["gid"] = gid
            return params

        self._base_params = patched
        try:
            return await self._call(
                api, post, api_version=api_version, with_session=with_session,
            )
        finally:
            self._base_params = orig

    async def get_device(self, dev_id: str) -> CloudDevice:
        """Detailed device fetch — guaranteed to include localKey."""
        resp = await self._call(
            "thing.m.device.get", {"devId": dev_id},
            api_version="4.1", with_session=True,
        )
        r = resp.get("result", {}) or {}
        return CloudDevice(
            dev_id=r.get("devId", dev_id),
            name=r.get("name") or "",
            product_id=r.get("productId") or "",
            local_key=r.get("localKey") or "",
            online=bool(r.get("isOnline")),
            mac=r.get("mac"),
            ip=r.get("ip"),
        )

    # ── Internals ───────────────────────────────────────────────────────

    def _base_params(self, api_name: str, api_version: str) -> dict:
        return {
            "a": api_name,
            "v": api_version,
            "clientId": OEM_ACCESS_ID,
            "os": "Android",
            "lang": LANG,
            "appVersion": APP_VERSION,
            "sdkVersion": SDK_VERSION,
            "deviceCoreVersion": DEVICE_CORE_VERSION,
            "ttid": TTID,
            "osSystem": OS_SYSTEM,
            "platform": PLATFORM,
            "deviceId": self._android_device_id,
            "requestId": uuid.uuid4().hex,
            "time": str(int(time.time())),
            "chKey": CH_KEY,
            "channel": "sdk",
            "timeZoneId": time.strftime("%Z") or "America/New_York",
            "bizData": json.dumps({"customDomainSupport": "1"}, separators=(",", ":")),
            "et": "3",  # AES-GCM payload encryption — required for newer endpoints
            "sp": "1",
            "cp": "gzip",
        }

    async def _call(
        self,
        api_name: str,
        post_data: dict,
        api_version: str = "3.0",
        with_session: bool = False,
    ) -> dict:
        params = self._base_params(api_name, api_version)
        if with_session:
            if not self._sid:
                raise OemApiError("session required but not logged in")
            params["sid"] = self._sid

        post_json = json.dumps(post_data, separators=(",", ":"))
        request_id = params["requestId"]
        ecode_for_key = self._ecode if with_session else None
        enc_key = _get_encrypto_key(request_id, ecode_for_key)
        post_value = base64.b64encode(
            _aes_gcm_encrypt(enc_key, post_json.encode())
        ).decode()

        sign_map = {**params, "postData": post_value}
        sig = _hmac_sha256_hex(HMAC_KEY, _build_sign_string(sign_map))

        body = {**params, "postData": post_value, "sign": sig}

        url = f"{API_BASE}{API_PATH}"
        async with self._http.post(
            url, data=body,
            headers={
                "User-Agent": f"ThingClips/{APP_VERSION}",
                "Connection": "keep-alive",
            },
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            resp.raise_for_status()
            # API returns the body labelled `text/plain; charset=utf-8` even
            # though the body is JSON. Pass content_type=None to skip aiohttp's
            # mime-type check.
            raw = await resp.json(content_type=None)

        # Decrypt + maybe-gunzip the result before checking success — Tuya
        # nests the success/errorCode envelope inside the encrypted payload.
        if raw.get("result"):
            try:
                blob = base64.b64decode(raw["result"])
                plain = _aes_gcm_decrypt(enc_key, blob)
                try:
                    plain = gzip.decompress(plain)
                except (gzip.BadGzipFile, OSError):
                    pass
                decoded = json.loads(plain)
                if isinstance(decoded, dict) and "success" in decoded:
                    raw = decoded
                else:
                    raw["result"] = decoded
                    raw.setdefault("success", True)
            except Exception:  # noqa: BLE001 — surface as API error below
                _LOGGER.debug("could not decrypt %s response — passing through", api_name)

        if not raw.get("success", False):
            code = raw.get("errorCode", "?")
            msg = raw.get("errorMsg", "?")
            raise OemApiError(f"{api_name}: [{code}] {msg}")

        return raw


@dataclass
class LanCandidate:
    """A device seen broadcasting on the LAN (UDP 6666/6667)."""
    dev_id: str
    ip: str
    version: str


async def scan_lan(timeout: float = 8.0) -> list[LanCandidate]:
    """UDP-scan the LAN for Tuya devices broadcasting their identity.

    Returns whatever's broadcasting; the caller filters by account ownership
    via the OEM `get_device` call. Off-loads to an executor so the HA event
    loop isn't blocked by tinytuya's sync scan.
    """
    import tinytuya  # local import — heavy module, avoid at integration import time

    def _scan() -> list[LanCandidate]:
        try:
            results = tinytuya.deviceScan(verbose=False, maxretry=int(timeout))
        except Exception:
            return []
        out: list[LanCandidate] = []
        for ip, info in (results or {}).items():
            gw_id = info.get("gwId")
            if not gw_id:
                continue
            out.append(LanCandidate(dev_id=gw_id, ip=ip, version=str(info.get("version", "3.4"))))
        return out

    return await asyncio.get_running_loop().run_in_executor(None, _scan)


async def discover_lan_ip(dev_id: str, timeout: float = 8.0) -> str | None:
    """Convenience: find a single device's IP by gwId via LAN scan."""
    candidates = await scan_lan(timeout=timeout)
    for c in candidates:
        if c.dev_id == dev_id:
            return c.ip
    return None
