#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Tuple

import psutil
from telegram.ext import ContextTypes

from core.db import add_alert_event, add_metrics_sample, add_process_samples, cleanup_old_samples, get_setting
from core.formatting import compact_bar, format_size

logger = logging.getLogger(__name__)
ALERT_COOLDOWN = 1800


async def _collect_top_processes(limit: int = 5) -> Tuple[List[Tuple[str, int, float, float, float, str]], List[Tuple[str, int, float, float, float, str]]]:
    for proc in psutil.process_iter():
        try:
            proc.cpu_percent(None)
        except Exception:
            continue
    await asyncio.sleep(0.15)

    cpu_rows = []
    ram_rows = []
    for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'memory_info']):
        try:
            name = proc.info['name'] or 'unknown'
            pid = int(proc.info['pid'])
            cpu = float(proc.info['cpu_percent'] or 0)
            mem_percent = float(proc.info['memory_percent'] or 0)
            memory_mb = float((proc.info['memory_info'].rss if proc.info['memory_info'] else 0) / 1024 / 1024)
            cpu_rows.append((name, pid, cpu, mem_percent, memory_mb, 'cpu'))
            ram_rows.append((name, pid, cpu, mem_percent, memory_mb, 'ram'))
        except Exception:
            continue

    cpu_rows.sort(key=lambda item: item[2], reverse=True)
    ram_rows.sort(key=lambda item: item[3], reverse=True)
    return cpu_rows[:limit], ram_rows[:limit]


async def sample_metrics_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    now = datetime.now().isoformat(timespec='seconds')
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    net = psutil.net_io_counters()
    try:
        load1, load5, load15 = psutil.getloadavg()
    except Exception:
        load1, load5, load15 = 0.0, 0.0, 0.0

    cpu_percent = psutil.cpu_percent(interval=0.2)
    add_metrics_sample(
        now,
        cpu_percent,
        mem.percent,
        disk.percent,
        int(net.bytes_sent),
        int(net.bytes_recv),
        float(load1),
        float(load5),
        float(load15),
    )

    cpu_top, ram_top = await _collect_top_processes()
    process_rows = []
    for name, pid, cpu, mem_percent, memory_mb, metric_type in cpu_top + ram_top:
        process_rows.append(
            (
                now,
                name,
                pid,
                round(cpu, 1),
                round(mem_percent, 1),
                round(memory_mb, 1),
                metric_type,
            )
        )
    add_process_samples(now, process_rows)
    cleanup_old_samples(days_to_keep=14)

    update_network_state(context.application.bot_data, net.bytes_sent, net.bytes_recv)



def update_network_state(bot_data: Dict[str, Any], bytes_sent: int, bytes_recv: int) -> Dict[str, float]:
    now = time.time()
    state = bot_data.get('network_state')
    if not state:
        bot_data['network_state'] = {
            'timestamp': now,
            'bytes_sent': bytes_sent,
            'bytes_recv': bytes_recv,
            'tx_rate_bps': 0.0,
            'rx_rate_bps': 0.0,
        }
        return bot_data['network_state']

    delta = max(1e-6, now - float(state['timestamp']))
    tx_rate = max(0.0, (bytes_sent - int(state['bytes_sent'])) / delta)
    rx_rate = max(0.0, (bytes_recv - int(state['bytes_recv'])) / delta)
    state.update(
        {
            'timestamp': now,
            'bytes_sent': bytes_sent,
            'bytes_recv': bytes_recv,
            'tx_rate_bps': tx_rate,
            'rx_rate_bps': rx_rate,
        }
    )
    return state


async def resource_monitor_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    cpu_threshold = float(get_setting('cpu_threshold', '85'))
    ram_threshold = float(get_setting('ram_threshold', '90'))
    disk_threshold = float(get_setting('disk_threshold', '90'))
    bot_data = context.application.bot_data

    cpu = psutil.cpu_percent(interval=0.2)
    ram = psutil.virtual_memory().percent
    disk = psutil.disk_usage('/').percent

    checks = [
        ('cpu', cpu, cpu_threshold, 'CPU'),
        ('ram', ram, ram_threshold, 'RAM'),
        ('disk', disk, disk_threshold, 'SSD'),
    ]

    cooldowns = bot_data.setdefault('resource_alerts_cooldown', {})
    now = time.time()
    for key, current, threshold, label in checks:
        if current < threshold:
            continue
        last_sent = cooldowns.get(key, 0)
        if now - last_sent < ALERT_COOLDOWN:
            continue
        cooldowns[key] = now
        message = (
            f'⚠️ <b>Высокая нагрузка: {label}</b>\n\n'
            f'{label} {current:.1f}% {compact_bar(current)}\n'
            f'Порог: {threshold:.0f}%\n\n'
        )
        if key == 'ram':
            mem = psutil.virtual_memory()
            message += f'Использовано: {format_size(mem.used)} из {format_size(mem.total)}'
        elif key == 'disk':
            usage = psutil.disk_usage('/')
            message += f'Использовано: {format_size(usage.used)} из {format_size(usage.total)}'
        else:
            message += 'Проверьте процессы с высокой нагрузкой.'

        await context.bot.send_message(
            chat_id=context.application.bot_data['admin_id'],
            text=message,
            parse_mode='HTML',
        )
        add_alert_event(key, message)
