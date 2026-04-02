#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from cryptography import x509
from cryptography.hazmat.backends import default_backend

logger = logging.getLogger(__name__)
CACHE_TTL = 600
MAX_DEPTH = 8
EXCLUDED_DIRS = {
    'venv', '.git', '__pycache__', 'node_modules', 'backups', 'cache',
    'ca-certificates', 'mozilla', 'python3', 'ssl', 'anchors',
}
EXCLUDED_PATH_PARTS = {
    '/usr/share/ca-certificates',
    '/etc/ssl/certs',
    '/var/lib/ca-certificates',
    '/etc/pki/ca-trust',
}
COMMON_ROOTS = [
    '/etc/letsencrypt',
    '/etc/letsencrypt/live',
    '/etc/letsencrypt/archive',
    '/etc/nginx',
    '/etc/apache2',
    '/etc/haproxy',
    '/etc/prosody',
    '/etc/x-ui',
    '/usr/local/x-ui',
    '/usr/local/share',
    '/usr/local/etc',
    '/etc/ssl/private',
    '/etc/pki',
    '/etc/pki/tls',
    '/var/lib',
    '/var/snap',
    '/opt',
    '/srv',
    '/root',
    '/home',
    '/www/server/panel/vhost/cert',
]
CERT_SUFFIXES = {'.pem', '.crt', '.cer', '.cert', '.fullchain'}
KEYWORDS = (
    'fullchain', 'cert', 'certificate', 'panel', 'tls', 'ssl',
    'letsencrypt', 'prosody', 'x-ui', 'chain', 'acme', 'domain',
)


def _parse_certificate(path: Path) -> Dict[str, Any] | None:
    try:
        raw = path.read_bytes()
    except Exception as exc:
        logger.debug('Cannot read cert %s: %s', path, exc)
        return None

    cert = None
    try:
        if b'-----BEGIN CERTIFICATE-----' in raw:
            blocks = raw.split(b'-----BEGIN CERTIFICATE-----')
            for block in blocks:
                if not block.strip():
                    continue
                pem = b'-----BEGIN CERTIFICATE-----' + block
                end = pem.find(b'-----END CERTIFICATE-----')
                if end != -1:
                    pem = pem[:end + len(b'-----END CERTIFICATE-----')]
                    cert = x509.load_pem_x509_certificate(pem, default_backend())
                    break
        if cert is None:
            cert = x509.load_der_x509_certificate(raw, default_backend())
    except Exception:
        return None

    try:
        common_name = cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)[0].value
    except Exception:
        common_name = path.name

    san = []
    try:
        san_ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        san = san_ext.value.get_values_for_type(x509.DNSName)
    except Exception:
        san = []

    expires_at = cert.not_valid_after.replace(tzinfo=timezone.utc)
    days_left = int((expires_at - datetime.now(timezone.utc)).total_seconds() // 86400)
    return {
        'path': str(path),
        'common_name': common_name,
        'san': san[:5],
        'expires_at': expires_at,
        'days_left': days_left,
        'service': _guess_service(str(path)),
    }


def _guess_service(path: str) -> str:
    lower = path.lower()
    if 'letsencrypt' in lower or 'nginx' in lower:
        return 'Web/TLS'
    if 'prosody' in lower:
        return 'Prosody'
    if 'x-ui' in lower:
        return '3x-ui / panel'
    if 'panel' in lower or 'admin' in lower:
        return 'Web panel'
    if 'server-bot' in lower:
        return 'server-bot'
    return 'Custom service'


def _walk_roots() -> List[Path]:
    found: List[Path] = []
    seen = set()
    for root in COMMON_ROOTS:
        root_path = Path(root)
        if not root_path.exists():
            continue
        for current_root, dirs, files in os.walk(root_path, followlinks=False):
            current_path = Path(current_root)
            try:
                relative_depth = (
                    len(current_path.relative_to(root_path).parts)
                    if current_path != root_path else 0
                )
            except Exception:
                relative_depth = 0
            dirs[:] = [name for name in dirs if name not in EXCLUDED_DIRS]
            if relative_depth >= MAX_DEPTH:
                dirs[:] = []
            current_str = str(current_path)
            if any(part in current_str for part in EXCLUDED_PATH_PARTS):
                dirs[:] = []
                continue
            for file_name in files:
                candidate = current_path / file_name
                lower = file_name.lower()
                if not (
                    candidate.suffix.lower() in CERT_SUFFIXES
                    or any(key in lower for key in KEYWORDS)
                ):
                    continue
                if candidate.is_file() and str(candidate) not in seen:
                    seen.add(str(candidate))
                    found.append(candidate)
    return found


async def get_certificates(bot_data: Dict[str, Any], force: bool = False) -> List[Dict[str, Any]]:
    cached = bot_data.get('certificates_cache')
    if not force and cached and time.time() - cached.get('cached_at', 0) < CACHE_TTL:
        return cached['data']

    certificates: List[Dict[str, Any]] = []
    seen_paths = set()
    for path in _walk_roots():
        cert_info = _parse_certificate(path)
        if cert_info and cert_info['path'] not in seen_paths:
            seen_paths.add(cert_info['path'])
            certificates.append(cert_info)

    certificates.sort(key=lambda item: (item['days_left'], item['common_name']))
    bot_data['certificates_cache'] = {'cached_at': time.time(), 'data': certificates}
    return certificates


async def get_expiring_certificates(
    bot_data: Dict[str, Any],
    days_limit: int = 30,
    force: bool = False,
) -> List[Dict[str, Any]]:
    certs = await get_certificates(bot_data, force=force)
    return [item for item in certs if item['days_left'] <= days_limit]
