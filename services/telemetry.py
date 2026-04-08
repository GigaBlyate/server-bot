#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import socket
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import aiohttp
from telegram.ext import ContextTypes

import config
from core.db import get_setting, set_setting

logger = logging.getLogger(__name__)
TELEMETRY_TIMEOUT = int(getattr(config, 'TELEMETRY_TIMEOUT', 10) or 10)
IDENTITY_NAMESPACE = 'gpanel-private-telemetry/3.1.15'
MACHINE_ID_CANDIDATES = (
    Path('/etc/machine-id'),
    Path('/var/lib/dbus/machine-id'),
)
PRODUCT_UUID_CANDIDATES = (
    Path('/sys/class/dmi/id/product_uuid'),
    Path('/sys/devices/virtual/dmi/id/product_uuid'),
)
BOARD_SERIAL_CANDIDATES = (
    Path('/sys/class/dmi/id/board_serial'),
    Path('/sys/devices/virtual/dmi/id/board_serial'),
)
NET_CLASS_DIR = Path('/sys/class/net')


def telemetry_enabled() -> bool:
    url = str(getattr(config, 'TELEMETRY_URL', '') or '').strip().rstrip('/')
    enabled = bool(getattr(config, 'TELEMETRY_ENABLED', True))
    return enabled and bool(url)


def telemetry_url() -> str:
    return str(getattr(config, 'TELEMETRY_URL', '') or '').strip().rstrip('/')


def telemetry_owner_token() -> str:
    return str(getattr(config, 'TELEMETRY_OWNER_TOKEN', '') or '').strip()


def telemetry_owner_enabled() -> bool:
    return telemetry_enabled() and bool(telemetry_owner_token())


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


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8', errors='ignore').strip()
    except Exception:
        return ''


def _first_nonempty(paths) -> str:
    for candidate in paths:
        value = _read_text(candidate).strip()
        if value:
            return value
    return ''


def _read_root_mount_source() -> str:
    try:
        for raw in Path('/proc/self/mountinfo').read_text(encoding='utf-8', errors='ignore').splitlines():
            left, _, right = raw.partition(' - ')
            left_parts = left.split()
            right_parts = right.split()
            if len(left_parts) >= 5 and left_parts[4] == '/' and len(right_parts) >= 2:
                source = right_parts[1].strip()
                if source and source != 'rootfs':
                    return source
    except Exception:
        pass
    try:
        st = os.stat('/')
        return f'dev:{os.major(st.st_dev)}:{os.minor(st.st_dev)}'
    except Exception:
        return ''


def _read_mac_addresses() -> list[str]:
    values: list[str] = []
    if not NET_CLASS_DIR.exists():
        return values
    skip_prefixes = ('lo', 'docker', 'br-', 'veth', 'virbr', 'tun', 'tap', 'wg')
    for iface_dir in sorted(NET_CLASS_DIR.iterdir(), key=lambda item: item.name):
        name = iface_dir.name
        if name.startswith(skip_prefixes):
            continue
        mac = _read_text(iface_dir / 'address').lower()
        if not mac or mac == '00:00:00:00:00:00':
            continue
        values.append(f'{name}:{mac}')
    return values


def _collect_identity_sources() -> Dict[str, object]:
    payload: Dict[str, object] = {}
    machine_id = _first_nonempty(MACHINE_ID_CANDIDATES).lower()
    if machine_id:
        payload['machine_id'] = machine_id
    product_uuid = _first_nonempty(PRODUCT_UUID_CANDIDATES).lower()
    if product_uuid:
        payload['product_uuid'] = product_uuid
    board_serial = _first_nonempty(BOARD_SERIAL_CANDIDATES).lower()
    if board_serial:
        payload['board_serial'] = board_serial
    root_source = _read_root_mount_source().lower()
    if root_source:
        payload['root_source'] = root_source
    macs = _read_mac_addresses()
    if macs:
        payload['macs'] = macs
    try:
        hostname = socket.gethostname().strip().lower()
        if hostname:
            payload['hostname_hint'] = hostname
    except Exception:
        pass
    if not payload:
        payload['fallback'] = hashlib.sha256(
            f'{IDENTITY_NAMESPACE}|{os.getuid()}|{Path(config.PROJECT_DIR).resolve()}'.encode('utf-8')
        ).hexdigest()
    return payload


def _canonical_identity_payload() -> str:
    return json.dumps(_collect_identity_sources(), ensure_ascii=False, separators=(',', ':'), sort_keys=True)


def get_server_uid() -> str:
    canonical = _canonical_identity_payload()
    return hashlib.sha256(f'{IDENTITY_NAMESPACE}\n{canonical}'.encode('utf-8')).hexdigest()


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


def _build_payload(event_name: str) -> dict:
    payload = {
        'event_type': event_name,
        'server_uid': get_server_uid(),
        'install_id': get_or_create_install_id(),
        'bot_version': get_current_version(),
        'telemetry_version': '2',
    }
    if event_name == 'install':
        payload['auth_secret'] = get_or_create_auth_secret()
    return payload


async def post_telemetry_event(event_name: str) -> bool:
    if not telemetry_enabled():
        return False
    path = f'/api/telemetry/{event_name}'
    payload = _build_payload(event_name)
    auth_secret = str(payload.get('auth_secret') or get_or_create_auth_secret())
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(12)
    signature = _build_signature(auth_secret, path, payload, timestamp, nonce)
    url = f'{telemetry_url()}{path}'
    timeout = aiohttp.ClientTimeout(total=TELEMETRY_TIMEOUT)
    headers = {
        'User-Agent': 'server-bot-private-telemetry/3.1.15',
        'X-Telemetry-Timestamp': timestamp,
        'X-Telemetry-Nonce': nonce,
        'X-Telemetry-Signature': signature,
    }
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as response:
                if response.status == 200:
                    set_setting('telemetry_last_sent', datetime.utcnow().replace(microsecond=0).isoformat() + 'Z')
                    return True
                logger.warning('Telemetry %s returned HTTP %s', event_name, response.status)
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


def send_uninstall_event_sync() -> bool:
    try:
        return asyncio.run(send_uninstall_event())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(send_uninstall_event())
        finally:
            loop.close()


async def _owner_get_json(path: str) -> Optional[dict]:
    if not telemetry_owner_enabled():
        return None
    url = f'{telemetry_url()}{path}'
    headers = {
        'Authorization': f'Bearer {telemetry_owner_token()}',
        'User-Agent': 'server-bot-private-telemetry-admin/3.1.15',
    }
    timeout = aiohttp.ClientTimeout(total=TELEMETRY_TIMEOUT)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    logger.warning('Telemetry admin endpoint %s returned HTTP %s', path, response.status)
                    return None
                return await response.json()
    except Exception as exc:
        logger.warning('Could not fetch telemetry admin endpoint %s: %s', path, exc)
        return None


async def fetch_owner_telemetry_summary() -> Optional[dict]:
    return await _owner_get_json('/api/telemetry/private/summary')


async def fetch_owner_telemetry_recent() -> Optional[dict]:
    return await _owner_get_json('/api/telemetry/private/recent')
