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
from typing import Any, Dict, List

import psutil

from core.formatting import format_size, format_uptime
from security import safe_run_command
from services.geolocation import get_public_ip_info

logger = logging.getLogger(__name__)
SERVICE_CACHE_TTL = 60
UPDATE_CACHE_TTL = 1800
KEY_SERVICES = ['server-bot', 'nginx', 'docker', 'prosody', 'x-ui', 'ssh', 'fail2ban']


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


async def get_service_statuses(bot_data: Dict[str, Any], force: bool = False) -> Dict[str, str]:
    cached = bot_data.get('service_statuses')
    if not force and cached and time.time() - cached.get('cached_at', 0) < SERVICE_CACHE_TTL:
        return cached['data']

    result: Dict[str, str] = {}
    for service in KEY_SERVICES:
        _, out, err = await safe_run_command(['systemctl', 'is-active', service], timeout=5)
        status = (out or err).strip().splitlines()[0] if (out or err) else 'unknown'
        if status == 'inactive' and 'not-found' in err:
            continue
        result[service] = status

    bot_data['service_statuses'] = {'cached_at': time.time(), 'data': result}
    return result


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

    pretty_name = platform.platform()
    try:
        for line in Path('/etc/os-release').read_text(encoding='utf-8').splitlines():
            if line.startswith('PRETTY_NAME='):
                pretty_name = line.split('=', 1)[1].strip().strip('"')
                break
    except Exception:
        pass

    return {
        'hostname': socket.gethostname(),
        'os_name': pretty_name,
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
