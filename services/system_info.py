#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import logging
import os
import platform
import socket
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import psutil

from core.db import get_setting
from core.formatting import format_size, format_uptime
from security import safe_run_command
from services.geolocation import get_public_ip_info

logger = logging.getLogger(__name__)
SERVICE_CACHE_TTL = 90
UPDATE_CACHE_TTL = 1800

SERVICE_CATALOG: List[Dict[str, Any]] = [
    {'key': 'server-bot', 'label': 'G-PANEL', 'systemd': ['server-bot']},
    {'key': 'ssh', 'label': 'SSH', 'systemd': ['ssh', 'sshd'], 'process': ['sshd']},
    {'key': 'nginx', 'label': 'Nginx', 'systemd': ['nginx'], 'process': ['nginx']},
    {'key': 'apache', 'label': 'Apache', 'systemd': ['apache2', 'httpd'], 'process': ['apache2', 'httpd']},
    {'key': 'caddy', 'label': 'Caddy', 'systemd': ['caddy'], 'process': ['caddy']},
    {'key': 'docker', 'label': 'Docker', 'systemd': ['docker'], 'process': ['dockerd'], 'docker_builtin': True},
    {'key': 'docker-compose', 'label': 'Docker Compose', 'process': ['docker-compose', 'compose']},
    {'key': 'containerd', 'label': 'containerd', 'systemd': ['containerd'], 'process': ['containerd']},
    {'key': 'podman', 'label': 'Podman', 'systemd': ['podman'], 'process': ['podman']},
    {'key': 'redis', 'label': 'Redis', 'systemd': ['redis', 'redis-server'], 'process': ['redis-server']},
    {'key': 'mysql', 'label': 'MySQL/MariaDB', 'systemd': ['mysql', 'mariadb'], 'process': ['mysqld', 'mariadbd']},
    {'key': 'postgresql', 'label': 'PostgreSQL', 'systemd': ['postgresql'], 'process': ['postgres', 'postgresql']},
    {'key': 'fail2ban', 'label': 'Fail2Ban', 'systemd': ['fail2ban'], 'process': ['fail2ban-server']},
    {'key': 'certbot', 'label': 'Certbot', 'systemd': ['certbot'], 'process': ['certbot']},
    {'key': 'x-ui', 'label': 'X-UI', 'systemd': ['x-ui'], 'process': ['x-ui']},
    {'key': '3x-ui', 'label': '3X-UI', 'systemd': ['3x-ui'], 'process': ['3x-ui']},
    {'key': 'marzban', 'label': 'Marzban', 'systemd': ['marzban', 'marzban-node'], 'process': ['marzban', 'marzban-node'], 'docker': ['marzban', 'marzban-node']},
    {'key': 'remnawave', 'label': 'Remnawave', 'systemd': ['remnawave'], 'process': ['remnawave'], 'docker': ['remnawave']},
    {'key': 'wireguard', 'label': 'WireGuard', 'systemd_prefix': ['wg-quick@', 'wireguard'], 'process': ['wg-quick', 'wireguard-go']},
    {'key': 'openvpn', 'label': 'OpenVPN', 'systemd_prefix': ['openvpn', 'openvpn-server@', 'openvpn-client@'], 'process': ['openvpn']},
    {'key': 'ocserv', 'label': 'ocserv', 'systemd': ['ocserv'], 'process': ['ocserv-main', 'ocserv']},
    {'key': 'strongswan', 'label': 'strongSwan', 'systemd': ['strongswan', 'strongswan-starter', 'ipsec'], 'process': ['charon', 'starter']},
    {'key': 'amneziawg', 'label': 'AmneziaWG', 'systemd': ['amneziawg', 'amnezia-wg'], 'process': ['awg', 'amneziawg']},
    {'key': 'tailscale', 'label': 'Tailscale', 'systemd': ['tailscaled'], 'process': ['tailscaled']},
    {'key': 'headscale', 'label': 'Headscale', 'systemd': ['headscale'], 'process': ['headscale']},
    {'key': 'softether', 'label': 'SoftEther', 'systemd': ['vpnserver', 'vpnclient', 'vpnbridge'], 'process': ['vpnserver', 'vpnclient', 'vpnbridge']},
    {'key': 'xl2tpd', 'label': 'xl2tpd', 'systemd': ['xl2tpd'], 'process': ['xl2tpd']},
    {'key': 'pptpd', 'label': 'PPTP', 'systemd': ['pptpd'], 'process': ['pptpd']},
    {'key': 'sstp', 'label': 'SSTP', 'systemd': ['accel-ppp'], 'process': ['accel-pppd']},
    {'key': 'outline', 'label': 'Outline', 'systemd': ['outline-ss-server'], 'process': ['outline-ss-server']},
    {'key': 'danted', 'label': 'Dante', 'systemd': ['danted', 'sockd'], 'process': ['danted', 'sockd']},
    {'key': 'xray', 'label': 'Xray', 'systemd': ['xray'], 'process': ['xray']},
    {'key': 'v2ray', 'label': 'V2Ray', 'systemd': ['v2ray'], 'process': ['v2ray']},
    {'key': 'sing-box', 'label': 'sing-box', 'systemd': ['sing-box', 'singbox'], 'process': ['sing-box', 'singbox']},
    {'key': 'hysteria', 'label': 'Hysteria', 'systemd': ['hysteria-server', 'hysteria', 'hysteria2'], 'process': ['hysteria', 'hysteria2']},
    {'key': 'trojan', 'label': 'Trojan', 'systemd': ['trojan', 'trojan-go'], 'process': ['trojan', 'trojan-go']},
    {'key': 'shadowsocks', 'label': 'Shadowsocks', 'systemd': ['shadowsocks-libev', 'shadowsocks-rust', 'ssserver'], 'process': ['ssserver', 'ss-local']},
    {'key': 'gost', 'label': 'Gost', 'systemd': ['gost'], 'process': ['gost']},
    {'key': 'brook', 'label': 'Brook', 'systemd': ['brook'], 'process': ['brook']},
    {'key': 'naiveproxy', 'label': 'NaiveProxy', 'systemd': ['naiveproxy'], 'process': ['naive', 'naiveproxy']},
    {'key': 'cloak', 'label': 'Cloak', 'systemd': ['ck-server', 'cloak-server'], 'process': ['ck-server', 'cloak-server']},
    {'key': 'mtg', 'label': 'MTG', 'systemd': ['mtg'], 'process': ['mtg']},
    {'key': 'mtproto-proxy', 'label': 'MTProto Proxy', 'systemd': ['mtproto-proxy', 'mtproxy'], 'process': ['mtproto-proxy', 'mtproxy']},
    {'key': 'telemt', 'label': 'TeleMT', 'systemd': ['telemt'], 'process': ['telemt']},
]

DOCKER_PERMISSION_ERRORS = ('permission denied', 'got permission denied', 'connect: permission denied')


def get_local_ip_addresses() -> List[str]:
    ips: List[str] = []
    for addrs in psutil.net_if_addrs().values():
        for addr in addrs:
            if addr.family == socket.AF_INET and not addr.address.startswith('127.'):
                ips.append(addr.address)
    return sorted(set(ips))


def _read_first_line(path: str) -> str:
    try:
        return Path(path).read_text(encoding='utf-8').strip()
    except Exception:
        return 'N/A'


def _cpu_model() -> str:
    try:
        for line in Path('/proc/cpuinfo').read_text(encoding='utf-8').splitlines():
            if line.lower().startswith('model name'):
                return line.split(':', 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or 'N/A'


def _get_os_name() -> str:
    try:
        data: Dict[str, str] = {}
        for line in Path('/etc/os-release').read_text(encoding='utf-8').splitlines():
            if '=' not in line:
                continue
            key, value = line.split('=', 1)
            data[key.strip()] = value.strip().strip('"')
        pretty = data.get('PRETTY_NAME', '').strip()
        if pretty:
            return pretty
        parts = [data.get('NAME', '').strip(), data.get('VERSION', '').strip()]
        result = ' '.join(part for part in parts if part).strip()
        if result:
            return result
    except Exception:
        pass
    return platform.platform()


def _humanize_service_name(raw: str) -> str:
    cleaned = raw.replace('.service', '').replace('-', ' ').replace('_', ' ').strip()
    return ' '.join(part.capitalize() if part else '' for part in cleaned.split()) or raw


def _normalize_service_query(raw: str) -> str:
    value = str(raw or '').strip().lower()
    return value[:-8] if value.endswith('.service') else value


def _normalize_status(status: str) -> str:
    raw = str(status or '').strip().lower()
    if raw in {'active', 'running', 'online', 'up'}:
        return 'running'
    if raw in {'inactive', 'dead', 'exited', 'stopped', 'created'}:
        return 'stopped'
    if raw in {'failed', 'crashed', 'error', 'missing', 'not-found', 'unknown'}:
        return 'missing'
    if raw in {'activating', 'reloading', 'deactivating'}:
        return 'stopped'
    return raw or 'unknown'


def _status_label(status: str) -> str:
    normalized = _normalize_status(status)
    if normalized == 'running':
        return 'running'
    if normalized == 'stopped':
        return 'stopped'
    return 'not found'


def _manual_service_definitions() -> List[Dict[str, str]]:
    raw = str(get_setting('manual_services_json', '[]') or '[]')
    try:
        payload = json.loads(raw)
        if not isinstance(payload, list):
            return []
        result: List[Dict[str, str]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            service_type = str(item.get('type') or '').strip().lower()
            name = str(item.get('name') or '').strip()
            if service_type not in {'systemd', 'process', 'docker'} or not name:
                continue
            label = str(item.get('label') or '').strip() or _humanize_service_name(name)
            result.append({'type': service_type, 'name': name, 'label': label})
        return result[:20]
    except Exception:
        logger.warning('Cannot parse manual_services_json')
        return []


async def _disk_models() -> List[str]:
    _, out, _ = await safe_run_command(
        ['lsblk', '-d', '-J', '-o', 'NAME,MODEL,SIZE,TYPE'], timeout=10
    )
    devices: List[str] = []
    if out:
        try:
            payload = json.loads(out)
            for item in payload.get('blockdevices', []):
                if item.get('type') != 'disk':
                    continue
                model = (item.get('model') or '').strip() or 'Unknown model'
                size = (item.get('size') or '').strip()
                name = item.get('name') or ''
                devices.append(f'{name}: {model} ({size})')
        except Exception:
            logger.debug('Cannot parse lsblk output')
    return devices[:6]


async def _nic_models() -> List[str]:
    _, out, _ = await safe_run_command(['lspci'], timeout=10)
    found: List[str] = []
    if out:
        for line in out.splitlines():
            lower = line.lower()
            if 'ethernet controller' in lower or 'network controller' in lower:
                found.append(line.split(': ', 1)[1].strip() if ': ' in line else line.strip())
    if found:
        return found[:6]

    fallback: List[str] = []
    stats = psutil.net_if_stats()
    for name, info in stats.items():
        if name.startswith('lo'):
            continue
        speed = f'{info.speed} Mbps' if info.speed and info.speed > 0 else 'скорость неизвестна'
        fallback.append(f'{name}: {speed}')
    return fallback[:6]


async def _list_systemd_units() -> Dict[str, str]:
    result: Dict[str, str] = {}

    code, out, err = await safe_run_command(
        ['systemctl', 'list-units', '--type=service', '--all', '--no-legend', '--no-pager'],
        timeout=12,
    )
    raw = out or err
    if code == 0 or raw.strip():
        for line in raw.splitlines():
            chunks = line.split()
            if len(chunks) < 4:
                continue
            unit, _, active, sub = chunks[:4]
            norm = _normalize_service_query(unit)
            status = sub if active == 'active' else active
            result[norm] = _normalize_status(status)

    code, out, err = await safe_run_command(
        ['systemctl', 'list-unit-files', '--type=service', '--no-legend', '--no-pager'],
        timeout=12,
    )
    raw = out or err
    if code == 0 or raw.strip():
        for line in raw.splitlines():
            chunks = line.split()
            if len(chunks) < 2:
                continue
            unit, state = chunks[:2]
            norm = _normalize_service_query(unit)
            if norm not in result:
                result[norm] = 'stopped'
            elif result[norm] == 'missing' and state.lower() not in {'masked', 'bad'}:
                result[norm] = 'stopped'
    return result


def _list_processes() -> List[Tuple[str, str]]:
    items: List[Tuple[str, str]] = []
    for proc in psutil.process_iter(['name', 'cmdline']):
        try:
            name = str(proc.info.get('name') or '').strip().lower()
            cmdline = ' '.join(proc.info.get('cmdline') or []).strip().lower()
            if name or cmdline:
                items.append((name, cmdline))
        except Exception:
            continue
    return items


async def _list_docker_containers() -> Tuple[Dict[str, str], bool]:
    code, out, err = await safe_run_command(
        ['docker', 'ps', '-a', '--format', '{{.Names}}	{{.Status}}'],
        timeout=8,
    )
    permission_needed = False
    error_text = (err or out or '').lower()
    if code != 0:
        if any(fragment in error_text for fragment in DOCKER_PERMISSION_ERRORS):
            permission_needed = True
        return {}, permission_needed

    result: Dict[str, str] = {}
    for line in (out or '').splitlines():
        if not line.strip():
            continue
        if '	' in line:
            name, status = line.split('	', 1)
        else:
            name, status = line.strip(), 'unknown'
        normalized = 'running' if any(x in status.lower() for x in ('up', 'running', 'healthy')) else 'stopped'
        result[name.strip().lower()] = normalized
    return result, permission_needed


def _status_from_catalog(
    entry: Dict[str, Any],
    systemd_units: Dict[str, str],
    processes: List[Tuple[str, str]],
    docker_containers: Dict[str, str],
) -> Tuple[str, str]:
    for unit in entry.get('systemd', []):
        status = systemd_units.get(_normalize_service_query(unit))
        if status:
            return entry['label'], status
    for prefix in entry.get('systemd_prefix', []):
        normalized_prefix = _normalize_service_query(prefix)
        for unit_name, status in sorted(systemd_units.items()):
            if unit_name.startswith(normalized_prefix):
                suffix = unit_name[len(normalized_prefix):].strip('@-._')
                label = entry['label'] if not suffix else f"{entry['label']} {suffix}"
                return label, status
    for keyword in entry.get('process', []):
        lower_keyword = str(keyword).lower()
        for proc_name, cmdline in processes:
            if lower_keyword and (lower_keyword == proc_name or lower_keyword in cmdline):
                return entry['label'], 'running'
    for docker_name in entry.get('docker', []):
        lower_name = str(docker_name).lower()
        for container, status in docker_containers.items():
            if lower_name == container or lower_name in container:
                return entry['label'], status
    if entry.get('docker_builtin') and docker_containers:
        return entry['label'], 'running'
    return '', ''


def _status_for_manual_service(
    item: Dict[str, str],
    systemd_units: Dict[str, str],
    processes: List[Tuple[str, str]],
    docker_containers: Dict[str, str],
) -> str:
    service_type = item['type']
    name = _normalize_service_query(item['name'])
    if service_type == 'systemd':
        return systemd_units.get(name, 'missing')
    if service_type == 'process':
        for proc_name, cmdline in processes:
            if name == proc_name or name in cmdline:
                return 'running'
        return 'missing'
    if service_type == 'docker':
        for container, status in docker_containers.items():
            if name == container or name in container:
                return status
        return 'missing'
    return 'unknown'


async def resolve_manual_service_query(
    service_type: str,
    query: str,
    *,
    include_docker: bool = True,
) -> Dict[str, str] | None:
    service_type = str(service_type or '').strip().lower()
    q = _normalize_service_query(query)
    if service_type not in {'systemd', 'process', 'docker'} or not q:
        return None

    systemd_units = await _list_systemd_units() if service_type == 'systemd' else {}
    processes = _list_processes() if service_type == 'process' else []
    docker_containers, _ = await _list_docker_containers() if include_docker and service_type == 'docker' else ({}, False)

    if service_type == 'systemd':
        if q in systemd_units:
            return {'type': 'systemd', 'name': q, 'label': _humanize_service_name(q), 'status': systemd_units[q]}
        matches = [(name, status) for name, status in systemd_units.items() if q in name]
        if len(matches) == 1:
            name, status = matches[0]
            return {'type': 'systemd', 'name': name, 'label': _humanize_service_name(name), 'status': status}
        return None

    if service_type == 'process':
        candidates: Dict[str, str] = {}
        for proc_name, cmdline in processes:
            if q == proc_name or q in cmdline:
                canonical = proc_name or q
                candidates[canonical] = canonical
        if not candidates:
            return None
        name = sorted(candidates)[0]
        return {'type': 'process', 'name': name, 'label': _humanize_service_name(name), 'status': 'running'}

    if service_type == 'docker':
        matches = [(name, status) for name, status in docker_containers.items() if q == name or q in name]
        if not matches:
            return None
        name, status = sorted(matches, key=lambda item: (item[0] != q, len(item[0])))[0]
        return {'type': 'docker', 'name': name, 'label': _humanize_service_name(name), 'status': status}
    return None


async def get_service_statuses(bot_data: Dict[str, Any], force: bool = False) -> Dict[str, str]:
    cached = bot_data.get('service_statuses')
    if not force and cached and time.time() - cached.get('cached_at', 0) < SERVICE_CACHE_TTL:
        return cached['data']

    systemd_units = await _list_systemd_units()
    processes = _list_processes()
    docker_containers, docker_permission_needed = await _list_docker_containers()

    result: Dict[str, str] = {}
    auto_labels: List[str] = []
    for entry in SERVICE_CATALOG:
        label, status = _status_from_catalog(entry, systemd_units, processes, docker_containers)
        if not label or not status:
            continue
        if label in result:
            continue
        result[label] = status
        auto_labels.append(label)

    manual_labels: List[str] = []
    for item in _manual_service_definitions():
        label = item['label']
        status = _status_for_manual_service(item, systemd_units, processes, docker_containers)
        result[label] = status
        manual_labels.append(label)

    bot_data['service_statuses'] = {
        'cached_at': time.time(),
        'data': result,
        'auto': auto_labels,
        'manual': manual_labels,
        'docker_permission_needed': docker_permission_needed,
    }
    return result


async def get_service_scan_snapshot(bot_data: Dict[str, Any], force: bool = False) -> Dict[str, Any]:
    await get_service_statuses(bot_data, force=force)
    cached = bot_data.get('service_statuses') or {}
    return {
        'data': dict(cached.get('data') or {}),
        'auto': list(cached.get('auto') or []),
        'manual': list(cached.get('manual') or []),
        'docker_permission_needed': bool(cached.get('docker_permission_needed')),
    }


async def get_system_update_cache(bot_data: Dict[str, Any]) -> Dict[str, Any]:
    cached = bot_data.get('system_updates_cache')
    if cached and time.time() - cached.get('cached_at', 0) < UPDATE_CACHE_TTL:
        return cached['data']
    return {'count': None, 'packages': []}


async def set_system_update_cache(bot_data: Dict[str, Any], count: int, packages: List[str]) -> None:
    bot_data['system_updates_cache'] = {
        'cached_at': time.time(),
        'data': {'count': count, 'packages': packages},
    }


async def get_server_info(bot_data: Dict[str, Any]) -> Dict[str, Any]:
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    boot = datetime.fromtimestamp(psutil.boot_time())
    net = psutil.net_io_counters()
    from services.metrics import update_network_state

    update_network_state(bot_data, net.bytes_sent, net.bytes_recv)
    geo = await get_public_ip_info(bot_data)
    services = await get_service_statuses(bot_data)
    docker_running = docker_total = None
    _, docker_out, _ = await safe_run_command(['docker', 'ps', '-q'], timeout=5)
    if docker_out is not None:
        running = [line for line in docker_out.splitlines() if line.strip()]
        docker_running = len(running)
        _, docker_all_out, _ = await safe_run_command(['docker', 'ps', '-aq'], timeout=5)
        docker_total = len([line for line in docker_all_out.splitlines() if line.strip()])

    try:
        load1, load5, load15 = os.getloadavg()
    except OSError:
        load1, load5, load15 = 0.0, 0.0, 0.0

    return {
        'hostname': socket.gethostname(),
        'os_name': _get_os_name(),
        'kernel': platform.release(),
        'arch': platform.machine(),
        'boot_time': boot,
        'uptime': format_uptime((datetime.now() - boot).total_seconds()),
        'cpu_percent': psutil.cpu_percent(interval=0.2),
        'cpu_count': psutil.cpu_count(logical=True) or 0,
        'cpu_cores': psutil.cpu_count(logical=False) or 0,
        'cpu_model': _cpu_model(),
        'ram_percent': mem.percent,
        'ram_used': format_size(mem.used),
        'ram_total': format_size(mem.total),
        'disk_percent': disk.percent,
        'disk_used': format_size(disk.used),
        'disk_total': format_size(disk.total),
        'net_total_sent': int(net.bytes_sent),
        'net_total_recv': int(net.bytes_recv),
        'load1': load1,
        'load5': load5,
        'load15': load15,
        'local_ips': get_local_ip_addresses(),
        'public_geo': geo,
        'services': services,
        'docker_running': docker_running,
        'docker_total': docker_total,
        'board_vendor': _read_first_line('/sys/class/dmi/id/board_vendor'),
        'board_name': _read_first_line('/sys/class/dmi/id/board_name'),
        'product_name': _read_first_line('/sys/class/dmi/id/product_name'),
        'product_vendor': _read_first_line('/sys/class/dmi/id/sys_vendor'),
        'disk_models': await _disk_models(),
        'nic_models': await _nic_models(),
    }
