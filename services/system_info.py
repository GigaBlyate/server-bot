#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import json
import logging
import os
import platform
import re
import shutil
import socket
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import psutil

from core.db import get_json_setting, get_setting
from core.formatting import format_size, format_uptime
from security import safe_run_command
from services.geolocation import get_public_ip_info

logger = logging.getLogger(__name__)
SERVICE_CACHE_TTL = 90
UPDATE_CACHE_TTL = 1800
DOCKER_PERMISSION_ERRORS = ('permission denied', 'got permission denied', 'connect: permission denied')
SCAN_DIRECTORIES = [
    '/etc', '/opt', '/srv', '/usr/local/bin', '/usr/local/sbin', '/usr/bin', '/usr/sbin', '/var/lib',
]

SERVICE_CATALOG: List[Dict[str, Any]] = [
    {'key': 'server-bot', 'label': 'G-PANEL', 'aliases': ['server-bot', 'g-panel'], 'systemd': ['server-bot'], 'process': ['bot.py'], 'binary': ['server-bot-rootctl']},
    {'key': 'ssh', 'label': 'SSH', 'aliases': ['ssh', 'sshd'], 'systemd': ['ssh', 'sshd'], 'process': ['sshd']},
    {'key': 'nginx', 'label': 'Nginx', 'aliases': ['nginx'], 'systemd': ['nginx'], 'process': ['nginx'], 'binary': ['nginx'], 'config': ['/etc/nginx/nginx.conf']},
    {'key': 'apache', 'label': 'Apache', 'aliases': ['apache', 'apache2', 'httpd'], 'systemd': ['apache2', 'httpd'], 'process': ['apache2', 'httpd'], 'binary': ['apache2', 'httpd']},
    {'key': 'caddy', 'label': 'Caddy', 'aliases': ['caddy'], 'systemd': ['caddy'], 'process': ['caddy'], 'binary': ['caddy']},
    {'key': 'docker', 'label': 'Docker', 'aliases': ['docker', 'dockerd'], 'systemd': ['docker'], 'process': ['dockerd'], 'docker_builtin': True, 'binary': ['docker']},
    {'key': 'containerd', 'label': 'containerd', 'aliases': ['containerd'], 'systemd': ['containerd'], 'process': ['containerd'], 'binary': ['containerd']},
    {'key': 'podman', 'label': 'Podman', 'aliases': ['podman'], 'systemd': ['podman'], 'process': ['podman'], 'binary': ['podman']},
    {'key': 'redis', 'label': 'Redis', 'aliases': ['redis', 'redis-server'], 'systemd': ['redis', 'redis-server'], 'process': ['redis-server'], 'binary': ['redis-server']},
    {'key': 'mysql', 'label': 'MySQL/MariaDB', 'aliases': ['mysql', 'mariadb', 'mysqld', 'mariadbd'], 'systemd': ['mysql', 'mariadb'], 'process': ['mysqld', 'mariadbd'], 'binary': ['mysqld', 'mariadbd']},
    {'key': 'postgresql', 'label': 'PostgreSQL', 'aliases': ['postgresql', 'postgres'], 'systemd': ['postgresql'], 'process': ['postgres', 'postgresql'], 'binary': ['postgres']},
    {'key': 'fail2ban', 'label': 'Fail2Ban', 'aliases': ['fail2ban', 'fail2ban-server'], 'systemd': ['fail2ban'], 'process': ['fail2ban-server'], 'binary': ['fail2ban-server']},
    {'key': 'certbot', 'label': 'Certbot', 'aliases': ['certbot'], 'systemd': ['certbot'], 'process': ['certbot'], 'binary': ['certbot']},
    {'key': 'x-ui-family', 'label': '3X-UI', 'aliases': ['3x-ui', 'x-ui', 'xui'], 'systemd': ['3x-ui', 'x-ui'], 'process': ['3x-ui', 'x-ui', 'x-ui-linux', 'x-ui-amd64'], 'docker': ['3x-ui', 'x-ui'], 'binary': ['x-ui', '3x-ui'], 'config': ['/etc/x-ui', '/etc/3x-ui', '/usr/local/x-ui', '/opt/x-ui', '/opt/3x-ui']},
    {'key': 'marzban', 'label': 'Marzban', 'aliases': ['marzban', 'marzban-node'], 'systemd': ['marzban', 'marzban-node'], 'process': ['marzban', 'marzban-node'], 'docker': ['marzban', 'marzban-node'], 'binary': ['marzban', 'marzban-node'], 'config': ['/opt/marzban', '/etc/marzban']},
    {'key': 'remnawave', 'label': 'Remnawave', 'aliases': ['remnawave'], 'systemd': ['remnawave'], 'process': ['remnawave'], 'docker': ['remnawave'], 'binary': ['remnawave'], 'config': ['/opt/remnawave', '/etc/remnawave']},
    {'key': 'wireguard', 'label': 'WireGuard', 'aliases': ['wireguard', 'wg', 'wg-quick'], 'systemd_prefix': ['wg-quick@', 'wireguard'], 'process': ['wg-quick', 'wireguard-go'], 'binary': ['wg', 'wg-quick', 'wireguard-go'], 'config': ['/etc/wireguard']},
    {'key': 'openvpn', 'label': 'OpenVPN', 'aliases': ['openvpn', 'openvpn-server', 'openvpn-client'], 'systemd_prefix': ['openvpn', 'openvpn-server@', 'openvpn-client@'], 'process': ['openvpn'], 'binary': ['openvpn'], 'config': ['/etc/openvpn']},
    {'key': 'ocserv', 'label': 'ocserv', 'aliases': ['ocserv'], 'systemd': ['ocserv'], 'process': ['ocserv-main', 'ocserv'], 'binary': ['ocserv']},
    {'key': 'strongswan', 'label': 'strongSwan', 'aliases': ['strongswan', 'ipsec', 'charon'], 'systemd': ['strongswan', 'strongswan-starter', 'ipsec'], 'process': ['charon', 'starter'], 'binary': ['ipsec', 'charon']},
    {'key': 'xray-family', 'label': 'Xray/V2Ray', 'aliases': ['xray', 'v2ray'], 'systemd': ['xray', 'v2ray'], 'process': ['xray', 'v2ray'], 'docker': ['xray', 'v2ray'], 'binary': ['xray', 'v2ray'], 'config': ['/etc/xray', '/usr/local/etc/xray', '/etc/v2ray']},
    {'key': 'sing-box', 'label': 'sing-box', 'aliases': ['sing-box', 'singbox'], 'systemd': ['sing-box', 'singbox'], 'process': ['sing-box', 'singbox'], 'docker': ['sing-box', 'singbox'], 'binary': ['sing-box', 'singbox'], 'config': ['/etc/sing-box', '/usr/local/etc/sing-box']},
    {'key': 'hysteria', 'label': 'Hysteria', 'aliases': ['hysteria', 'hysteria2'], 'systemd': ['hysteria-server', 'hysteria', 'hysteria2'], 'process': ['hysteria', 'hysteria2'], 'docker': ['hysteria', 'hysteria2'], 'binary': ['hysteria', 'hysteria2'], 'config': ['/etc/hysteria', '/etc/hysteria2']},
    {'key': 'trojan', 'label': 'Trojan', 'aliases': ['trojan', 'trojan-go'], 'systemd': ['trojan', 'trojan-go'], 'process': ['trojan', 'trojan-go'], 'docker': ['trojan', 'trojan-go'], 'binary': ['trojan', 'trojan-go']},
    {'key': 'shadowsocks', 'label': 'Shadowsocks', 'aliases': ['shadowsocks', 'ssserver', 'shadowsocks-libev', 'shadowsocks-rust'], 'systemd': ['shadowsocks-libev', 'shadowsocks-rust', 'ssserver'], 'process': ['ssserver', 'ss-local'], 'docker': ['shadowsocks', 'ssserver'], 'binary': ['ssserver', 'ss-local'], 'config': ['/etc/shadowsocks-libev', '/etc/shadowsocks-rust']},
    {'key': 'gost', 'label': 'Gost', 'aliases': ['gost'], 'systemd': ['gost'], 'process': ['gost'], 'docker': ['gost'], 'binary': ['gost']},
    {'key': 'mtproto', 'label': 'MTProto/TeleMT', 'aliases': ['telemt', 'mtg', 'mtproto-proxy', 'mtproxy', 'mtproto'], 'systemd': ['telemt', 'mtg', 'mtproto-proxy', 'mtproxy'], 'process': ['telemt', 'mtg', 'mtproto-proxy', 'mtproxy'], 'docker': ['telemt', 'mtg', 'mtproxy'], 'binary': ['telemt', 'mtg', 'mtproto-proxy', 'mtproxy'], 'config': ['/etc/telemt', '/etc/mtg', '/etc/mtproxy', '/opt/telemt']},
]


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


def _manual_service_definitions() -> List[Dict[str, str]]:
    payload = get_json_setting('manual_services_json', [])
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


def _normalize(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', value.lower())


def _norm_contains(needle: str, haystack: str) -> bool:
    n = _normalize(needle)
    h = _normalize(haystack)
    return bool(n and h and n in h)


def _looks_running(status: str) -> bool:
    lower = str(status).lower()
    return lower in {'active', 'running'} or 'running' in lower or 'up ' in lower or lower.startswith('up')


def _status_text(running: bool, installed: bool) -> str:
    if running:
        return 'running'
    if installed:
        return 'stopped'
    return 'not found'


async def _disk_models() -> List[str]:
    _, out, _ = await safe_run_command(['lsblk', '-d', '-J', '-o', 'NAME,MODEL,SIZE,TYPE'], timeout=10)
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
    code, out, err = await safe_run_command(['systemctl', 'list-units', '--type=service', '--all', '--no-legend', '--no-pager'], timeout=12)
    raw = out or err
    if code != 0 and not raw.strip():
        return {}
    result: Dict[str, str] = {}
    for line in raw.splitlines():
        chunks = line.split()
        if len(chunks) < 4:
            continue
        unit, _, active, sub = chunks[:4]
        norm = unit.replace('.service', '').strip().lower()
        if not norm:
            continue
        result[norm] = sub if active == 'active' else active
    return result


async def _list_systemd_unit_files() -> Dict[str, str]:
    code, out, err = await safe_run_command(['systemctl', 'list-unit-files', '--type=service', '--no-legend', '--no-pager'], timeout=12)
    raw = out or err
    if code != 0 and not raw.strip():
        return {}
    result: Dict[str, str] = {}
    for line in raw.splitlines():
        chunks = line.split()
        if len(chunks) < 2:
            continue
        unit, state = chunks[:2]
        norm = unit.replace('.service', '').strip().lower()
        if norm:
            result[norm] = state
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
    code, out, err = await safe_run_command(['docker', 'ps', '-a', '--format', '{{.Names}}	{{.Status}}'], timeout=8)
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
            name, status = line.strip(), 'running'
        result[name.strip().lower()] = status.strip() or 'running'
    return result, permission_needed


def _find_process_match(aliases: Sequence[str], processes: List[Tuple[str, str]]) -> Tuple[bool, str]:
    for alias in aliases:
        for proc_name, cmdline in processes:
            if _norm_contains(alias, proc_name) or _norm_contains(alias, cmdline):
                return True, proc_name or alias
    return False, ''


def _find_docker_match(aliases: Sequence[str], containers: Dict[str, str]) -> Tuple[bool, bool, str]:
    for alias in aliases:
        for name, status in containers.items():
            if _norm_contains(alias, name):
                return _looks_running(status), True, name
    return False, False, ''


def _find_systemd_match(exacts: Sequence[str], prefixes: Sequence[str], units: Dict[str, str], unit_files: Dict[str, str]) -> Tuple[bool, bool, str]:
    for name in exacts:
        key = name.lower().replace('.service', '')
        if key in units:
            return _looks_running(units[key]), True, key
        if key in unit_files:
            return False, True, key
    for prefix in prefixes:
        low = prefix.lower()
        for key, status in units.items():
            if key.startswith(low):
                return _looks_running(status), True, key
        for key in unit_files:
            if key.startswith(low):
                return False, True, key
    return False, False, ''


def _files_indicate_installation(entry: Dict[str, Any]) -> bool:
    for binary in entry.get('binary', []):
        if shutil.which(binary):
            return True
    for path in entry.get('config', []):
        if Path(path).exists():
            return True
    return False


def _status_from_catalog(entry: Dict[str, Any], systemd_units: Dict[str, str], unit_files: Dict[str, str], processes: List[Tuple[str, str]], docker_containers: Dict[str, str]) -> Tuple[str, str]:
    aliases = list(entry.get('aliases', []))
    exacts = list(entry.get('systemd', []))
    prefixes = list(entry.get('systemd_prefix', []))
    running, installed, _ = _find_systemd_match(exacts, prefixes, systemd_units, unit_files)
    if running:
        return entry['label'], 'running'
    docker_running, docker_installed, _ = _find_docker_match(list(entry.get('docker', aliases)), docker_containers)
    if docker_running:
        return entry['label'], 'running'
    proc_running, _ = _find_process_match(list(entry.get('process', aliases)), processes)
    if proc_running:
        return entry['label'], 'running'
    installed = installed or docker_installed or _files_indicate_installation(entry)
    if entry.get('docker_builtin') and docker_containers:
        return entry['label'], 'running'
    status = _status_text(False, installed)
    return entry['label'], status if installed else ''


def _status_for_manual_service(item: Dict[str, str], systemd_units: Dict[str, str], unit_files: Dict[str, str], processes: List[Tuple[str, str]], docker_containers: Dict[str, str]) -> str:
    service_type = item['type']
    name = item['name'].strip().lower()
    if service_type == 'systemd':
        running, installed, _ = _find_systemd_match([name], [name], systemd_units, unit_files)
        return _status_text(running, installed)
    if service_type == 'process':
        running, _ = _find_process_match([name], processes)
        return 'running' if running else 'not found'
    if service_type == 'docker':
        running, installed, _ = _find_docker_match([name], docker_containers)
        return _status_text(running, installed)
    return 'not found'


def find_manual_service_candidate(service_type: str, user_input: str, bot_data: Dict[str, Any] | None = None) -> Tuple[bool, Dict[str, str], str]:
    name = (user_input or '').strip()
    if not name:
        return False, {}, 'Пустое имя сервиса.'
    service_type = service_type.lower().strip()
    systemd_units = (bot_data or {}).get('_last_systemd_units') or {}
    unit_files = (bot_data or {}).get('_last_systemd_unit_files') or {}
    processes = (bot_data or {}).get('_last_processes') or _list_processes()
    docker_containers = (bot_data or {}).get('_last_docker_containers') or {}

    if service_type == 'systemd':
        running, installed, matched = _find_systemd_match([name], [name], systemd_units, unit_files)
        if not installed and not running:
            return False, {}, f'Сервис <b>{name}</b> не найден среди systemd unit.'
        matched_name = matched or name
        return True, {'type': 'systemd', 'name': matched_name, 'label': _humanize_service_name(matched_name)}, 'ok'

    if service_type == 'process':
        running, matched = _find_process_match([name], processes)
        if not running:
            return False, {}, f'Процесс <b>{name}</b> не найден среди запущенных процессов.'
        actual = matched or name
        return True, {'type': 'process', 'name': actual, 'label': _humanize_service_name(actual)}, 'ok'

    if service_type == 'docker':
        running, installed, matched = _find_docker_match([name], docker_containers)
        if not installed and not running:
            return False, {}, f'Docker-контейнер <b>{name}</b> не найден.'
        actual = matched or name
        return True, {'type': 'docker', 'name': actual, 'label': _humanize_service_name(actual)}, 'ok'

    return False, {}, 'Неподдерживаемый тип сервиса.'


async def get_service_statuses(bot_data: Dict[str, Any], force: bool = False) -> Dict[str, str]:
    cached = bot_data.get('service_statuses')
    if not force and cached and time.time() - cached.get('cached_at', 0) < SERVICE_CACHE_TTL:
        return cached['data']

    systemd_units = await _list_systemd_units()
    unit_files = await _list_systemd_unit_files()
    processes = _list_processes()
    docker_containers, docker_permission_needed = await _list_docker_containers()

    bot_data['_last_systemd_units'] = systemd_units
    bot_data['_last_systemd_unit_files'] = unit_files
    bot_data['_last_processes'] = processes
    bot_data['_last_docker_containers'] = docker_containers

    result: Dict[str, str] = {}
    auto_labels: List[str] = []
    for entry in SERVICE_CATALOG:
        label, status = _status_from_catalog(entry, systemd_units, unit_files, processes, docker_containers)
        if not label or not status:
            continue
        if label in result:
            continue
        result[label] = status
        auto_labels.append(label)

    manual_labels: List[str] = []
    for item in _manual_service_definitions():
        label = item['label']
        status = _status_for_manual_service(item, systemd_units, unit_files, processes, docker_containers)
        result[label] = status
        manual_labels.append(label)

    bot_data['service_statuses'] = {
        'cached_at': time.time(),
        'data': result,
        'auto': auto_labels,
        'manual': manual_labels,
        'docker_permission_needed': docker_permission_needed,
        'scan_sources': ['systemd', 'processes', 'docker', ', '.join(SCAN_DIRECTORIES)],
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
        'scan_sources': list(cached.get('scan_sources') or []),
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


def _truncate_cmdline(value: str, limit: int = 72) -> str:
    cleaned = re.sub(r'\s+', ' ', (value or '').strip())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + '…'


def _collect_top_processes(limit: int = 7, sample_interval: float = 0.35) -> Dict[str, Any]:
    memory_total = psutil.virtual_memory().total or 1
    candidates = []
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            proc.cpu_percent(None)
            candidates.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    time.sleep(sample_interval)

    rows: List[Dict[str, Any]] = []
    for proc in candidates:
        try:
            with proc.oneshot():
                cpu = float(proc.cpu_percent(None) or 0.0)
                mem = proc.memory_info().rss or 0
                name = str(proc.name() or 'unknown').strip() or 'unknown'
                cmdline = _truncate_cmdline(' '.join(proc.cmdline() or []))
                rows.append({
                    'pid': int(proc.pid),
                    'name': name,
                    'cpu_percent': round(cpu, 1),
                    'ram_bytes': int(mem),
                    'ram_percent': round((mem / memory_total) * 100, 1),
                    'cmdline': cmdline,
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        except Exception:
            continue

    cpu_top = sorted(rows, key=lambda item: (item['cpu_percent'], item['ram_bytes']), reverse=True)[:limit]
    ram_top = sorted(rows, key=lambda item: (item['ram_bytes'], item['cpu_percent']), reverse=True)[:limit]
    return {
        'cpu_top': cpu_top,
        'ram_top': ram_top,
        'sample_interval': sample_interval,
    }


async def get_top_processes(limit: int = 7) -> Dict[str, Any]:
    return await asyncio.to_thread(_collect_top_processes, limit)
