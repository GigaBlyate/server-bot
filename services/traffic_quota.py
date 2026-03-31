#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict

import psutil
from telegram.ext import ContextTypes

from core.db import get_daily_metrics_summary, get_setting, set_setting
from core.formatting import format_gb, format_size

logger = logging.getLogger(__name__)
GB = 1024 ** 3
TB_GB = 1024


def _as_bool(value: str) -> bool:
    return str(value).lower() == 'true'


def _ensure_cycle_started() -> None:
    mode = get_setting('traffic_mode', 'unlimited')
    if mode != 'quota':
        return

    now = datetime.now()
    cycle_days = int(get_setting('traffic_cycle_days', '30') or 30)
    start_raw = get_setting('traffic_cycle_start_date', '')
    if not start_raw:
        set_setting('traffic_cycle_start_date', now.date().isoformat())
        counters = psutil.net_io_counters()
        set_setting('traffic_baseline_sent', str(int(counters.bytes_sent)))
        set_setting('traffic_baseline_recv', str(int(counters.bytes_recv)))
        set_setting('traffic_baseline_timestamp', now.isoformat(timespec='seconds'))
        set_setting('traffic_cycle_accumulated_bytes', '0')
        set_setting('traffic_last_total_bytes', str(int(counters.bytes_sent) + int(counters.bytes_recv)))
        set_setting('traffic_alert_sent_1tb', 'false')
        set_setting('traffic_alert_sent_300gb', 'false')
        return

    try:
        start_date = date.fromisoformat(start_raw)
    except ValueError:
        start_date = now.date()

    if (now.date() - start_date).days >= cycle_days:
        counters = psutil.net_io_counters()
        set_setting('traffic_cycle_start_date', now.date().isoformat())
        set_setting('traffic_baseline_sent', str(int(counters.bytes_sent)))
        set_setting('traffic_baseline_recv', str(int(counters.bytes_recv)))
        set_setting('traffic_baseline_timestamp', now.isoformat(timespec='seconds'))
        set_setting('traffic_cycle_accumulated_bytes', '0')
        set_setting('traffic_last_total_bytes', str(int(counters.bytes_sent) + int(counters.bytes_recv)))
        set_setting('traffic_alert_sent_1tb', 'false')
        set_setting('traffic_alert_sent_300gb', 'false')


def _get_cycle_used_bytes(total_bytes: int) -> int:
    try:
        accumulated = int(get_setting('traffic_cycle_accumulated_bytes', '0') or 0)
    except ValueError:
        accumulated = 0
    try:
        last_total = int(get_setting('traffic_last_total_bytes', '0') or 0)
    except ValueError:
        last_total = 0

    if last_total <= 0:
        set_setting('traffic_last_total_bytes', str(total_bytes))
        return max(0, accumulated)

    if total_bytes >= last_total:
        accumulated += total_bytes - last_total
    else:
        # Счётчики ядра были сброшены (чаще всего после reboot).
        accumulated += total_bytes

    set_setting('traffic_cycle_accumulated_bytes', str(max(0, accumulated)))
    set_setting('traffic_last_total_bytes', str(total_bytes))
    return max(0, accumulated)


def get_quota_status() -> Dict[str, Any]:
    mode = get_setting('traffic_mode', 'unlimited')
    counters = psutil.net_io_counters()
    total_bytes = int(counters.bytes_sent) + int(counters.bytes_recv)
    yesterday = get_daily_metrics_summary()
    yesterday_bytes = int((yesterday.get('traffic_sent') or 0) + (yesterday.get('traffic_recv') or 0))

    if mode != 'quota':
        return {
            'mode': 'unlimited',
            'label': 'Безлимитный трафик',
            'remaining_gb': None,
            'used_gb': None,
            'quota_gb': None,
            'total_bytes': total_bytes,
            'yesterday_bytes': yesterday_bytes,
            'current_bytes': None,
        }

    _ensure_cycle_started()
    quota_gb = float(get_setting('traffic_quota_gb', '3072') or 3072)
    used_bytes = _get_cycle_used_bytes(total_bytes)
    used_gb = used_bytes / GB
    remaining_gb = max(0.0, quota_gb - used_gb)
    cycle_days = int(get_setting('traffic_cycle_days', '30') or 30)
    cycle_start = get_setting('traffic_cycle_start_date', '')
    cycle_end = ''
    try:
        cycle_end = (date.fromisoformat(cycle_start) + timedelta(days=cycle_days)).isoformat()
    except Exception:
        cycle_end = 'N/A'

    return {
        'mode': 'quota',
        'used_gb': used_gb,
        'remaining_gb': remaining_gb,
        'quota_gb': quota_gb,
        'label': f'{format_gb(used_gb)} из {format_gb(quota_gb)}',
        'cycle_end': cycle_end,
        'total_bytes': total_bytes,
        'yesterday_bytes': yesterday_bytes,
        'current_bytes': used_bytes,
    }


def get_quota_summary_text() -> str:
    status = get_quota_status()
    if status['mode'] == 'unlimited':
        return f'Трафик: безлимитный, всего {format_size(status["total_bytes"])}'
    return (
        f"Трафик: {status['label']}, осталось {format_gb(status['remaining_gb'])} "
        f"до {status['cycle_end']}"
    )


def get_dashboard_traffic_lines() -> list[str]:
    status = get_quota_status()
    if status['mode'] == 'unlimited':
        return [
            f'• Трафик: всего {format_size(status["total_bytes"])}',
            '• Статус: безлимитный',
        ]
    return [
        f'• Трафик: всего {format_size(status["total_bytes"])}',
        f'• Вчера: {format_size(status["yesterday_bytes"])} • Сейчас: {format_size(status["current_bytes"])}',
        f'• Остаток пакета: {format_gb(status["remaining_gb"])} из {format_gb(status["quota_gb"])}',
    ]


async def traffic_quota_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    status = get_quota_status()
    if status['mode'] != 'quota':
        return

    remaining = float(status['remaining_gb'])
    if remaining <= TB_GB and not _as_bool(get_setting('traffic_alert_sent_1tb', 'false')):
        await context.bot.send_message(
            chat_id=context.application.bot_data['admin_id'],
            text=(
                '⚠️ <b>Трафик заканчивается</b>\n\n'
                f'Осталось около {format_gb(remaining)} из пакета {format_gb(status["quota_gb"])}.'
            ),
            parse_mode='HTML',
        )
        set_setting('traffic_alert_sent_1tb', 'true')

    if remaining <= 300 and not _as_bool(get_setting('traffic_alert_sent_300gb', 'false')):
        await context.bot.send_message(
            chat_id=context.application.bot_data['admin_id'],
            text=(
                '🚨 <b>Критично мало трафика</b>\n\n'
                f'Осталось всего {format_gb(remaining)}.'
            ),
            parse_mode='HTML',
        )
        set_setting('traffic_alert_sent_300gb', 'true')
