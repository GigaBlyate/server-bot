#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import socket
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import aiohttp
from telegram.ext import ContextTypes

import config
from core.db import get_setting, set_setting

logger = logging.getLogger(__name__)
TELEMETRY_TIMEOUT = int(getattr(config, 'TELEMETRY_TIMEOUT', 10) or 10)
LEGACY_SERVER_UID_FILE = Path.home() / '.gpanel-server-id'
MACHINE_ID_CANDIDATES = (
    Path('/etc/machine-id'),
    Path('/var/lib/dbus/machine-id'),
)
DMI_ID_CANDIDATES = (
    Path('/sys/class/dmi/id/product_uuid'),
    Path('/sys/class/dmi/id/product_serial'),
    Path('/sys/class/dmi/id/board_serial'),
    Path('/sys/class/dmi/id/chassis_serial'),
)
NETWORK_BASE = Path('/sys/class/net')
VIRTUAL_IFACE_PREFIXES = ('lo', 'docker', 'veth', 'br-', 'virbr', 'tun', 'tap', 'wg', 'tailscale', 'zt', 'vmnet')
UID_MIN_LEN = 32


def telemetry_enabled() -> bool:
    url = str(getattr(config, 'TELEMETRY_URL', '') or '').strip().rstrip('/')
    enabled = bool(getattr(config, 'TELEMETRY_ENABLED', True))
    return enabled and bool(url)


def telemetry_url() -> str:
    return str(getattr(config, 'TELEMETRY_URL', '') or '').strip().rstrip('/')


def get_or_create_install_id() -> str:
    install_id = str(get_setting('telemetry_install_id', '') or '').strip()
    if len(install_id) >= 16:
        return install_id
    install_id = secrets.token_hex(16)
    set_setting('telemetry_install_id', install_id)
    return install_id


def get_or_create_auth_secret() -> str:
    secret = str(get_setting('telemetry_auth_secret', '') or '').strip()
    if len(secret) >= 32:
        return secret
    secret = secrets.token_hex(32)
    set_setting('telemetry_auth_secret', secret)
    return secret


def _safe_read_text(path: Path, max_len: int = 256) -> str:
    try:
        return path.read_text(encoding='utf-8', errors='ignore').strip()[:max_len]
    except Exception:
        return ''


def _normalize_hostname(value: str) -> str:
    value = (value or '').strip().lower()
    if not value:
        return ''
    if value in {'localhost', '(none)'}:
        return ''
    return value[:128]


def _read_machine_id() -> str:
    for candidate in MACHINE_ID_CANDIDATES:
        raw = _safe_read_text(candidate, 128)
        if raw:
            return raw
    return ''


def _legacy_machine_hash() -> str:
    machine_id = _read_machine_id()
    if machine_id:
        return hashlib.sha256(f'gpanel:{machine_id}'.encode('utf-8')).hexdigest()
    return ''


def _legacy_file_uid() -> str:
    raw = _safe_read_text(LEGACY_SERVER_UID_FILE, 256).lower()
    if len(raw) >= UID_MIN_LEN and all(ch in '0123456789abcdef' for ch in raw):
        return raw
    return ''


def _collect_dmi_ids() -> List[str]:
    values: List[str] = []
    for candidate in DMI_ID_CANDIDATES:
        raw = _safe_read_text(candidate, 128)
        if raw:
            values.append(raw)
    return values


def _collect_mac_addresses() -> List[str]:
    macs: List[str] = []
    seen = set()
    if not NETWORK_BASE.exists():
        return macs

    for iface in sorted(NETWORK_BASE.iterdir(), key=lambda p: p.name):
        name = iface.name.lower()
        if name.startswith(VIRTUAL_IFACE_PREFIXES):
            continue
        addr = _safe_read_text(iface / 'address', 32).lower()
        if not addr or addr == '00:00:00:00:00:00':
            continue
        if len(addr) != 17 or not all(ch in '0123456789abcdef:' for ch in addr):
            continue
        if addr in seen:
            continue
        seen.add(addr)
        macs.append(addr)
    return macs[:4]


def _collect_fingerprint_material() -> Dict[str, object]:
    machine_id = _read_machine_id()
    dmi_ids = _collect_dmi_ids()
    macs = _collect_mac_addresses()
    hostname = _normalize_hostname(socket.gethostname())
    material: Dict[str, object] = {}
    if machine_id:
        material['machine_id'] = machine_id
    if dmi_ids:
        material['dmi'] = dmi_ids
    if macs:
        material['macs'] = macs
    if hostname:
        material['hostname'] = hostname
    return material


def _fingerprint_hash(material: Dict[str, object]) -> str:
    if not material:
        return ''
    canonical = json.dumps(material, ensure_ascii=False, separators=(',', ':'), sort_keys=True)
    return hashlib.sha256(f'gpanel-v2:{canonical}'.encode('utf-8')).hexdigest()


def get_server_uid() -> str:
    legacy_file_uid = _legacy_file_uid()
    if legacy_file_uid:
        return legacy_file_uid

    material = _collect_fingerprint_material()
    composite = _fingerprint_hash(material)
    if composite:
        return composite

    legacy_hash = _legacy_machine_hash()
    if legacy_hash:
        return legacy_hash

    fallback_hostname = _normalize_hostname(socket.gethostname()) or 'unknown-host'
    return hashlib.sha256(f'gpanel-hostname:{fallback_hostname}'.encode('utf-8')).hexdigest()


def get_server_uid_aliases() -> List[str]:
    aliases: List[str] = []
    seen = set()
    primary = get_server_uid()

    for candidate in (_legacy_file_uid(), _legacy_machine_hash()):
        if not candidate or candidate == primary or candidate in seen:
            continue
        seen.add(candidate)
        aliases.append(candidate)
    return aliases


def get_current_version() -> str:
    version_path = Path(config.PROJECT_DIR) / 'version.txt'
    try:
        value = version_path.read_text(encoding='utf-8').strip()
        return value or 'unknown'
    except Exception:
        return 'unknown'


def _canonical_payload(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':'), sort_keys=True)


def _build_signature(secret: str, path: str, payload: dict, timestamp: str, nonce: str) -> str:
    signed = '\n'.join([path, timestamp, nonce, _canonical_payload(payload)])
    return hmac.new(secret.encode('utf-8'), signed.encode('utf-8'), hashlib.sha256).hexdigest()


def build_event_payload(event_name: str) -> dict:
    payload = {
        'server_uid': get_server_uid(),
        'install_id': get_or_create_install_id(),
        'bot_version': get_current_version(),
    }
    aliases = get_server_uid_aliases()
    if aliases:
        payload['server_uid_aliases'] = aliases
    if event_name == 'install':
        payload['auth_secret'] = get_or_create_auth_secret()
    return payload


def build_event_request(event_name: str, url_override: str | None = None) -> Tuple[str, str, dict, dict]:
    auth_secret = get_or_create_auth_secret()
    path = f'/api/telemetry/{event_name}'
    payload = build_event_payload(event_name)
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(12)
    signature = _build_signature(auth_secret, path, payload, timestamp, nonce)
    url_root = (url_override or telemetry_url()).strip().rstrip('/')
    url = f'{url_root}{path}'
    headers = {
        'User-Agent': 'server-bot-telemetry/4.0',
        'Content-Type': 'application/json',
        'X-Telemetry-Timestamp': timestamp,
        'X-Telemetry-Nonce': nonce,
        'X-Telemetry-Signature': signature,
    }
    return path, url, payload, headers


async def post_telemetry_event(event_name: str) -> bool:
    if not telemetry_enabled():
        return False

    _path, url, payload, headers = build_event_request(event_name)
    timeout = aiohttp.ClientTimeout(total=TELEMETRY_TIMEOUT)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as response:
                if response.status == 200:
                    set_setting(
                        'telemetry_last_sent',
                        datetime.utcnow().replace(microsecond=0).isoformat() + 'Z',
                    )
                    return True
                logger.warning('Telemetry %s returned HTTP %s', event_name, response.status)
                return False
    except Exception as exc:
        logger.warning('Could not send telemetry %s: %s', event_name, exc)
        return False


def send_signed_event_sync(event_name: str, url_override: str | None = None, timeout: int | None = None) -> bool:
    if event_name not in {'install', 'heartbeat', 'uninstall'}:
        raise ValueError(f'Unsupported telemetry event: {event_name}')
    if not (url_override or telemetry_enabled()):
        return False

    _path, url, payload, headers = build_event_request(event_name, url_override=url_override)
    request = urllib.request.Request(
        url,
        data=_canonical_payload(payload).encode('utf-8'),
        headers=headers,
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=(timeout or TELEMETRY_TIMEOUT)) as response:
            if int(getattr(response, 'status', 0) or 0) == 200:
                set_setting(
                    'telemetry_last_sent',
                    datetime.utcnow().replace(microsecond=0).isoformat() + 'Z',
                )
                return True
            return False
    except Exception as exc:
        logger.warning('Could not send telemetry %s: %s', event_name, exc)
        return False


async def ensure_install_registered() -> None:
    if not telemetry_enabled():
        return
    if str(get_setting('telemetry_registered', 'false')).lower() == 'true':
        return
    if await post_telemetry_event('install'):
        set_setting('telemetry_registered', 'true')


async def telemetry_startup_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_install_registered()
    await post_telemetry_event('heartbeat')


async def telemetry_heartbeat_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_install_registered()
    await post_telemetry_event('heartbeat')


async def send_uninstall_event() -> bool:
    return await post_telemetry_event('uninstall')
