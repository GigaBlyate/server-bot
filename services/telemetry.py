#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time
from datetime import datetime
from pathlib import Path

import aiohttp
from telegram.ext import ContextTypes

import config
from core.db import get_setting, set_setting

logger = logging.getLogger(__name__)
TELEMETRY_TIMEOUT = int(getattr(config, 'TELEMETRY_TIMEOUT', 10) or 10)
SERVER_UID_FILE = Path.home() / '.gpanel-server-id'
MACHINE_ID_CANDIDATES = (
    Path('/etc/machine-id'),
    Path('/var/lib/dbus/machine-id'),
)


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


def _machine_hash() -> str:
    for candidate in MACHINE_ID_CANDIDATES:
        try:
            raw = candidate.read_text(encoding='utf-8').strip()
            if raw:
                return hashlib.sha256(f'gpanel:{raw}'.encode('utf-8')).hexdigest()
        except Exception:
            continue
    return hashlib.sha256(f'gpanel-fallback:{secrets.token_hex(32)}'.encode('utf-8')).hexdigest()


def get_or_create_server_uid() -> str:
    if SERVER_UID_FILE.exists():
        try:
            uid = SERVER_UID_FILE.read_text(encoding='utf-8').strip()
            if len(uid) >= 32:
                return uid
        except Exception:
            pass
    uid = _machine_hash()
    try:
        SERVER_UID_FILE.write_text(uid, encoding='utf-8')
        SERVER_UID_FILE.chmod(0o600)
    except Exception:
        logger.warning('Не удалось сохранить %s', SERVER_UID_FILE)
    return uid


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


async def post_telemetry_event(event_name: str) -> bool:
    if not telemetry_enabled():
        return False

    auth_secret = get_or_create_auth_secret()
    path = f'/api/telemetry/{event_name}'
    payload = {
        'server_uid': get_or_create_server_uid(),
        'install_id': get_or_create_install_id(),
        'bot_version': get_current_version(),
    }
    if event_name == 'install':
        payload['auth_secret'] = auth_secret

    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(12)
    signature = _build_signature(auth_secret, path, payload, timestamp, nonce)
    url = f'{telemetry_url()}{path}'
    timeout = aiohttp.ClientTimeout(total=TELEMETRY_TIMEOUT)
    headers = {
        'User-Agent': 'server-bot-telemetry/3.0',
        'X-Telemetry-Timestamp': timestamp,
        'X-Telemetry-Nonce': nonce,
        'X-Telemetry-Signature': signature,
    }
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
