#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import threading
import time
import urllib.request
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get('TELEMETRY_DB_PATH') or BASE_DIR / 'telemetry.db')
HOST = os.environ.get('TELEMETRY_HOST', '127.0.0.1')
PORT = int(os.environ.get('TELEMETRY_PORT', '8787'))
GITHUB_VERSION_URL = os.environ.get(
    'TELEMETRY_GITHUB_VERSION_URL',
    'https://raw.githubusercontent.com/GigaBlyate/server-bot/main/version.txt',
)
ACTIVE_WINDOW_MINUTES = int(os.environ.get('TELEMETRY_ACTIVE_MINUTES', '90'))
MAX_BODY_BYTES = int(os.environ.get('TELEMETRY_MAX_BODY_BYTES', '4096'))
RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get('TELEMETRY_RATE_LIMIT_WINDOW', '60'))
RATE_LIMIT_MAX_REQUESTS = int(os.environ.get('TELEMETRY_RATE_LIMIT_MAX_REQUESTS', '120'))
TIMESTAMP_SKEW_SECONDS = int(os.environ.get('TELEMETRY_TIMESTAMP_SKEW', '300'))
SERVER_UID_RE = re.compile(r'^[a-f0-9]{32,128}$')
INSTALL_ID_RE = re.compile(r'^[a-f0-9]{16,128}$')
AUTH_SECRET_RE = re.compile(r'^[a-f0-9]{32,128}$')
NONCE_RE = re.compile(r'^[A-Fa-f0-9]{12,64}$')
_version_lock = threading.Lock()
_version_cache = {'value': '—', 'checked_at': datetime.min.replace(tzinfo=timezone.utc)}
_rate_lock = threading.Lock()
_rate_state: Dict[str, Deque[float]] = defaultdict(deque)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS installs (
                server_uid TEXT PRIMARY KEY,
                install_id TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                bot_version TEXT DEFAULT '',
                auth_secret TEXT DEFAULT '',
                is_installed INTEGER NOT NULL DEFAULT 1,
                uninstall_seen TEXT DEFAULT NULL,
                install_count INTEGER NOT NULL DEFAULT 1
            )
            '''
        )
        columns = {row[1] for row in conn.execute('PRAGMA table_info(installs)').fetchall()}
        if 'auth_secret' not in columns:
            conn.execute("ALTER TABLE installs ADD COLUMN auth_secret TEXT DEFAULT ''")
        if 'is_installed' not in columns:
            conn.execute("ALTER TABLE installs ADD COLUMN is_installed INTEGER NOT NULL DEFAULT 1")
        if 'uninstall_seen' not in columns:
            conn.execute("ALTER TABLE installs ADD COLUMN uninstall_seen TEXT DEFAULT NULL")
        if 'install_count' not in columns:
            conn.execute("ALTER TABLE installs ADD COLUMN install_count INTEGER NOT NULL DEFAULT 1")

        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS server_aliases (
                alias_uid TEXT PRIMARY KEY,
                server_uid TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            '''
        )
        conn.commit()


def parse_json(body: bytes) -> Dict[str, Any]:
    if not body:
        return {}
    return json.loads(body.decode('utf-8'))


def _valid(value: str, regex: re.Pattern[str]) -> bool:
    return bool(regex.fullmatch(value or ''))


def _canonical_payload(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':'), sort_keys=True)


def _build_signature(secret: str, path: str, payload: Dict[str, Any], timestamp: str, nonce: str) -> str:
    signed = '\n'.join([path, timestamp, nonce, _canonical_payload(payload)])
    return hmac.new(secret.encode('utf-8'), signed.encode('utf-8'), hashlib.sha256).hexdigest()


def _extract_client_ip(handler: BaseHTTPRequestHandler) -> str:
    forwarded = handler.headers.get('X-Forwarded-For', '')
    if forwarded:
        return forwarded.split(',', 1)[0].strip()
    return str(handler.client_address[0])


def _rate_limit_ok(ip: str) -> bool:
    now = time.time()
    with _rate_lock:
        bucket = _rate_state[ip]
        while bucket and (now - bucket[0]) > RATE_LIMIT_WINDOW_SECONDS:
            bucket.popleft()
        if len(bucket) >= RATE_LIMIT_MAX_REQUESTS:
            return False
        bucket.append(now)
    return True


def _normalise_aliases(payload: Dict[str, Any], server_uid: str) -> List[str]:
    raw_aliases = payload.get('aliases', [])
    if not isinstance(raw_aliases, list):
        return []
    result: List[str] = []
    seen = {server_uid}
    for item in raw_aliases[:8]:
        value = str(item or '').strip().lower()
        if _valid(value, SERVER_UID_RE) and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _resolve_canonical_uid(server_uid: str, aliases: Iterable[str]) -> Optional[str]:
    candidates = [server_uid, *list(aliases)]
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row

        row = conn.execute('SELECT server_uid FROM installs WHERE server_uid = ?', (server_uid,)).fetchone()
        if row:
            return str(row['server_uid'])

        for candidate in candidates:
            row = conn.execute('SELECT server_uid FROM installs WHERE server_uid = ?', (candidate,)).fetchone()
            if row:
                return str(row['server_uid'])

        for candidate in candidates:
            row = conn.execute('SELECT server_uid FROM server_aliases WHERE alias_uid = ?', (candidate,)).fetchone()
            if row:
                return str(row['server_uid'])

    return None


def _load_install(canonical_uid: str) -> Optional[sqlite3.Row]:
    if not canonical_uid:
        return None
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute('SELECT * FROM installs WHERE server_uid = ?', (canonical_uid,)).fetchone()


def _verify_signature(path: str, payload: Dict[str, Any], headers, stored_secret: str = '') -> Tuple[bool, str]:
    timestamp = str(headers.get('X-Telemetry-Timestamp', '')).strip()
    nonce = str(headers.get('X-Telemetry-Nonce', '')).strip()
    signature = str(headers.get('X-Telemetry-Signature', '')).strip().lower()

    if not timestamp.isdigit():
        return False, 'Missing timestamp'
    if abs(int(time.time()) - int(timestamp)) > TIMESTAMP_SKEW_SECONDS:
        return False, 'Stale timestamp'
    if not _valid(nonce, NONCE_RE):
        return False, 'Invalid nonce'
    if not signature or len(signature) < 32:
        return False, 'Missing signature'

    secret = stored_secret.strip().lower()
    if not secret:
        secret = str(payload.get('auth_secret', '')).strip().lower()
        if not _valid(secret, AUTH_SECRET_RE):
            return False, 'Invalid auth_secret'

    expected = _build_signature(secret, path, payload, timestamp, nonce)
    if not hmac.compare_digest(signature, expected):
        return False, 'Bad signature'
    return True, secret


def _bind_aliases(conn: sqlite3.Connection, canonical_uid: str, aliases: Iterable[str]) -> None:
    now = utcnow().replace(microsecond=0).isoformat()
    for alias in aliases:
        if alias == canonical_uid:
            continue
        conn.execute(
            '''
            INSERT INTO server_aliases (alias_uid, server_uid, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(alias_uid) DO UPDATE SET server_uid = excluded.server_uid
            ''',
            (alias, canonical_uid, now),
        )


def upsert_install(server_uid: str, aliases: List[str], install_id: str, bot_version: str, auth_secret: str) -> None:
    now = utcnow().replace(microsecond=0).isoformat()
    canonical_uid = _resolve_canonical_uid(server_uid, aliases) or server_uid
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT * FROM installs WHERE server_uid = ?', (canonical_uid,)).fetchone()
        if row:
            next_install_count = int(row['install_count'] or 1)
            if str(row['install_id']) != install_id:
                next_install_count += 1
            conn.execute(
                '''
                UPDATE installs
                SET install_id = ?, last_seen = ?, bot_version = ?, auth_secret = ?, is_installed = 1,
                    uninstall_seen = NULL, install_count = ?
                WHERE server_uid = ?
                ''',
                (install_id, now, bot_version, auth_secret, next_install_count, canonical_uid),
            )
        else:
            conn.execute(
                '''
                INSERT INTO installs (
                    server_uid, install_id, first_seen, last_seen, bot_version,
                    auth_secret, is_installed, uninstall_seen, install_count
                ) VALUES (?, ?, ?, ?, ?, ?, 1, NULL, 1)
                ''',
                (canonical_uid, install_id, now, now, bot_version, auth_secret),
            )

        _bind_aliases(conn, canonical_uid, [server_uid, *aliases])
        conn.commit()


def update_heartbeat(server_uid: str, aliases: List[str], install_id: str, bot_version: str) -> bool:
    now = utcnow().replace(microsecond=0).isoformat()
    canonical_uid = _resolve_canonical_uid(server_uid, aliases)
    if not canonical_uid:
        return False
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            '''
            UPDATE installs
            SET install_id = ?, last_seen = ?, bot_version = ?, is_installed = 1
            WHERE server_uid = ?
            ''',
            (install_id, now, bot_version, canonical_uid),
        )
        _bind_aliases(conn, canonical_uid, [server_uid, *aliases])
        conn.commit()
    return True


def mark_uninstalled(server_uid: str, aliases: List[str], install_id: str, bot_version: str) -> bool:
    now = utcnow().replace(microsecond=0).isoformat()
    canonical_uid = _resolve_canonical_uid(server_uid, aliases)
    if not canonical_uid:
        return False
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            '''
            UPDATE installs
            SET install_id = ?, last_seen = ?, bot_version = ?, is_installed = 0, uninstall_seen = ?
            WHERE server_uid = ?
            ''',
            (install_id, now, bot_version, now, canonical_uid),
        )
        _bind_aliases(conn, canonical_uid, [server_uid, *aliases])
        conn.commit()
    return True


def get_latest_version() -> str:
    with _version_lock:
        now = utcnow()
        if (now - _version_cache['checked_at']) < timedelta(minutes=10):
            return _version_cache['value']
        try:
            with urllib.request.urlopen(GITHUB_VERSION_URL, timeout=8) as response:
                value = response.read().decode('utf-8', errors='ignore').strip() or '—'
                _version_cache['value'] = value
                _version_cache['checked_at'] = now
        except Exception:
            pass
        return _version_cache['value']


def build_public_stats() -> Dict[str, Any]:
    now = utcnow()
    active_now_cutoff = (now - timedelta(minutes=ACTIVE_WINDOW_MINUTES)).replace(microsecond=0).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        total_installs = conn.execute('SELECT COUNT(*) AS count FROM installs').fetchone()['count']
        active_now = conn.execute(
            'SELECT COUNT(*) AS count FROM installs WHERE is_installed = 1 AND last_seen >= ?',
            (active_now_cutoff,),
        ).fetchone()['count']
    latest_version = get_latest_version()
    return {
        'total_installs': int(total_installs),
        'active_bots_now': int(active_now),
        'current_bot_version': latest_version,
        'latest_version': latest_version,
        'heartbeat_window_minutes': ACTIVE_WINDOW_MINUTES,
        'updated_at': now.replace(microsecond=0).isoformat(),
    }


class TelemetryHandler(BaseHTTPRequestHandler):
    server_version = 'GPanelTelemetry/3.1.13'

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _send_json(self, payload: Dict[str, Any], status: int = 200, allow_cors: bool = False) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        if allow_cors:
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:
        self._send_json({'ok': True}, allow_cors=True)

    def do_GET(self) -> None:
        if self.path == '/healthz':
            self._send_json({'ok': True, 'service': 'telemetry'}, allow_cors=True)
            return
        if self.path == '/api/public/stats':
            self._send_json(build_public_stats(), allow_cors=True)
            return
        self._send_json({'ok': False, 'error': 'Not found'}, status=404, allow_cors=True)

    def do_POST(self) -> None:
        if self.path not in ('/api/telemetry/install', '/api/telemetry/heartbeat', '/api/telemetry/uninstall'):
            self._send_json({'ok': False, 'error': 'Not found'}, status=404)
            return

        client_ip = _extract_client_ip(self)
        if not _rate_limit_ok(client_ip):
            self._send_json({'ok': False, 'error': 'Rate limit exceeded'}, status=429)
            return

        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            self._send_json({'ok': False, 'error': 'Invalid Content-Length'}, status=400)
            return
        if length <= 0 or length > MAX_BODY_BYTES:
            self._send_json({'ok': False, 'error': 'Payload too large'}, status=413)
            return

        try:
            payload = parse_json(self.rfile.read(length))
        except Exception:
            self._send_json({'ok': False, 'error': 'Invalid JSON'}, status=400)
            return

        server_uid = str(payload.get('server_uid', '')).strip().lower()
        install_id = str(payload.get('install_id', '')).strip().lower()
        bot_version = str(payload.get('bot_version', '')).strip() or 'unknown'
        aliases = _normalise_aliases(payload, server_uid)

        if not _valid(server_uid, SERVER_UID_RE):
            self._send_json({'ok': False, 'error': 'Invalid server_uid'}, status=400)
            return
        if not _valid(install_id, INSTALL_ID_RE):
            self._send_json({'ok': False, 'error': 'Invalid install_id'}, status=400)
            return

        canonical_uid = _resolve_canonical_uid(server_uid, aliases)
        row = _load_install(canonical_uid) if canonical_uid else None
        stored_secret = ''
        if not self.path.endswith('/install') and row and row['auth_secret']:
            stored_secret = str(row['auth_secret'])

        ok, secret_or_error = _verify_signature(self.path, payload, self.headers, stored_secret)
        if not ok:
            self._send_json({'ok': False, 'error': secret_or_error}, status=401)
            return

        if self.path.endswith('/install'):
            upsert_install(server_uid, aliases, install_id, bot_version, secret_or_error)
            self._send_json({'ok': True})
            return

        if self.path.endswith('/heartbeat'):
            if not update_heartbeat(server_uid, aliases, install_id, bot_version):
                self._send_json({'ok': False, 'error': 'Unknown installation'}, status=404)
                return
            self._send_json({'ok': True})
            return

        if not mark_uninstalled(server_uid, aliases, install_id, bot_version):
            self._send_json({'ok': False, 'error': 'Unknown installation'}, status=404)
            return
        self._send_json({'ok': True})


def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), TelemetryHandler)
    print(f'Telemetry service listening on http://{HOST}:{PORT}')
    server.serve_forever()


if __name__ == '__main__':
    main()
