#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict

import psutil
from telegram.ext import ContextTypes

from core.db import get_setting, set_setting
from core.formatting import format_gb

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
        set_setting('traffic_alert_sent_1tb', 'false')
        set_setting('traffic_alert_sent_300gb', 'false')



def get_quota_status() -> Dict[str, Any]:
    mode = get_setting('traffic_mode', 'unlimited')
    if mode != 'quota':
        return {
            'mode': 'unlimited',
            'label': 'Безлимитный трафик',
            'remaining_gb': None,
            'used_gb': None,
            'quota_gb': None,
        }

    _ensure_cycle_started()
    counters = psutil.net_io_counters()
    baseline_sent = int(get_setting('traffic_baseline_sent', '0') or 0)
    baseline_recv = int(get_setting('traffic_baseline_recv', '0') or 0)
    quota_gb = float(get_setting('traffic_quota_gb', '3072') or 3072)
    used_bytes = max(0, int(counters.bytes_sent) - baseline_sent) + max(0, int(counters.bytes_recv) - baseline_recv)
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
    }



def get_quota_summary_text() -> str:
    status = get_quota_status()
    if status['mode'] == 'unlimited':
        return 'Трафик: безлимитный'
    return (
        f"Трафик: {status['label']}, осталось {format_gb(status['remaining_gb'])} "
        f"до {status['cycle_end']}"
    )


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
                '🚨 <b>Критически мало трафика</b>\n\n'
                f'Осталось около {format_gb(remaining)}. Проверьте лимит или тариф.'
            ),
            parse_mode='HTML',
        )
        set_setting('traffic_alert_sent_300gb', 'true')
