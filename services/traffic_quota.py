#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional

import psutil
from telegram.ext import ContextTypes

from core.db import get_setting, set_setting
from core.formatting import format_gb, format_size

logger = logging.getLogger(__name__)
GB = 1024 ** 3
TB = 1024 ** 4
DATE_FMT = '%Y-%m-%d'


def _as_bool(value: str) -> bool:
    return str(value).lower() == 'true'


def _today() -> date:
    return datetime.now().date()


def _parse_date(value: str) -> Optional[date]:
    try:
        return date.fromisoformat(str(value).strip())
    except Exception:
        return None


def _same_day_next_month(d: date) -> date:
    year = d.year + (1 if d.month == 12 else 0)
    month = 1 if d.month == 12 else d.month + 1
    day = min(d.day, monthrange(year, month)[1])
    return date(year, month, day)


def _add_months(anchor: date, months: int) -> date:
    year = anchor.year + ((anchor.month - 1 + months) // 12)
    month = ((anchor.month - 1 + months) % 12) + 1
    day = min(anchor.day, monthrange(year, month)[1])
    return date(year, month, day)


def _ensure_total_counter() -> int:
    counters = psutil.net_io_counters()
    current = int(counters.bytes_sent) + int(counters.bytes_recv)
    last = int(get_setting('traffic_last_counter_bytes', '0') or 0)
    total = int(get_setting('traffic_total_bytes', '0') or 0)

    if last <= 0 and total <= 0:
        total = current
    elif current >= last:
        total += current - last
    else:
        # System counters were reset, usually after reboot.
        total += current

    set_setting('traffic_total_bytes', str(total))
    set_setting('traffic_last_counter_bytes', str(current))
    set_setting('traffic_last_counter_updated_at', datetime.now().isoformat(timespec='seconds'))
    return total


def _ensure_day_rollover(total_bytes: int) -> None:
    today = _today().isoformat()
    saved_day = str(get_setting('traffic_today_date', '') or '')
    if not saved_day:
        set_setting('traffic_today_date', today)
        set_setting('traffic_today_anchor_total_bytes', str(total_bytes))
        return

    if saved_day == today:
        return

    try:
        old_anchor = int(get_setting('traffic_today_anchor_total_bytes', '0') or 0)
    except Exception:
        old_anchor = total_bytes
    yesterday_bytes = max(0, total_bytes - old_anchor)
    set_setting('traffic_yesterday_bytes', str(yesterday_bytes))
    set_setting('traffic_today_date', today)
    set_setting('traffic_today_anchor_total_bytes', str(total_bytes))


def _resolve_current_period(activation: date, today: date) -> tuple[date, date]:
    start = activation
    end = _same_day_next_month(start)
    while today >= end:
        start = end
        end = _same_day_next_month(start)
    return start, end


def _ensure_billing_period(total_bytes: int) -> tuple[Optional[date], Optional[date]]:
    activation = _parse_date(get_setting('traffic_activation_date', ''))
    if activation is None:
        return None, None

    today = _today()
    start, end = _resolve_current_period(activation, today)
    saved_start = _parse_date(get_setting('traffic_billing_period_start', ''))
    saved_end = _parse_date(get_setting('traffic_billing_period_end', ''))

    if saved_start != start or saved_end != end:
        set_setting('traffic_billing_period_start', start.isoformat())
        set_setting('traffic_billing_period_end', end.isoformat())
        set_setting('traffic_period_anchor_total_bytes', str(total_bytes))
        set_setting('traffic_period_anchor_set_at', datetime.now().isoformat(timespec='seconds'))
        set_setting('traffic_alert_sent_1tb', 'false')
        set_setting('traffic_alert_sent_300gb', 'false')
        set_setting('traffic_period_seed_bytes', '0')
    return start, end


def _days_until(d: Optional[date]) -> Optional[int]:
    if d is None:
        return None
    return max(0, (d - _today()).days)


def _get_today_yesterday(total_bytes: int) -> tuple[int, int]:
    _ensure_day_rollover(total_bytes)
    anchor = int(get_setting('traffic_today_anchor_total_bytes', str(total_bytes)) or total_bytes)
    today_bytes = max(0, total_bytes - anchor)
    yesterday_bytes = int(get_setting('traffic_yesterday_bytes', '0') or 0)
    return today_bytes, yesterday_bytes


def get_quota_status() -> Dict[str, Any]:
    total_bytes = _ensure_total_counter()
    today_bytes, yesterday_bytes = _get_today_yesterday(total_bytes)
    mode = get_setting('traffic_mode', 'unlimited')

    if mode != 'quota':
        return {
            'mode': 'unlimited',
            'label': 'Безлимитный трафик',
            'remaining_gb': None,
            'used_gb': None,
            'quota_gb': None,
            'total_bytes': total_bytes,
            'yesterday_bytes': yesterday_bytes,
            'today_bytes': today_bytes,
            'period_bytes': None,
            'period_days_left': None,
            'period_start': None,
            'period_end': None,
            'overage_bytes': 0,
        }

    quota_gb = float(get_setting('traffic_quota_gb', '3072') or 3072)
    period_start, period_end = _ensure_billing_period(total_bytes)
    period_anchor = int(get_setting('traffic_period_anchor_total_bytes', str(total_bytes)) or total_bytes)
    period_seed = int(get_setting('traffic_period_seed_bytes', '0') or 0)
    period_bytes = max(0, period_seed + max(0, total_bytes - period_anchor))
    quota_bytes = int(quota_gb * GB)
    remaining_bytes = max(0, quota_bytes - period_bytes)
    overage_bytes = max(0, period_bytes - quota_bytes)

    return {
        'mode': 'quota',
        'used_gb': period_bytes / GB,
        'remaining_gb': remaining_bytes / GB,
        'quota_gb': quota_gb,
        'label': f'{format_size(period_bytes)} из {format_gb(quota_gb)}',
        'cycle_end': period_end.isoformat() if period_end else 'N/A',
        'cycle_start': period_start.isoformat() if period_start else 'N/A',
        'total_bytes': total_bytes,
        'yesterday_bytes': yesterday_bytes,
        'today_bytes': today_bytes,
        'period_bytes': period_bytes,
        'period_days_left': _days_until(period_end),
        'period_start': period_start,
        'period_end': period_end,
        'overage_bytes': overage_bytes,
    }


def get_quota_summary_text() -> str:
    status = get_quota_status()
    if status['mode'] == 'unlimited':
        return f'безлимитный, всего {format_size(status["total_bytes"])}'
    tail = ''
    if status['period_days_left'] is not None:
        tail = f', до сброса {status["period_days_left"]} дн.'
    return f"период {format_size(status['period_bytes'])} из {format_gb(status['quota_gb'])}{tail}"


def get_dashboard_traffic_lines() -> list[str]:
    status = get_quota_status()
    if status['mode'] == 'unlimited':
        return [
            f'• Трафик всего: {format_size(status["total_bytes"])}',
            f'• Сегодня: {format_size(status["today_bytes"])} • Вчера: {format_size(status["yesterday_bytes"])}',
            '• Тариф: безлимитный',
        ]

    lines = [
        f'• Трафик всего: {format_size(status["total_bytes"])}',
        f'• Сегодня: {format_size(status["today_bytes"])} • Вчера: {format_size(status["yesterday_bytes"])}',
        f'• Период: {format_size(status["period_bytes"])} из {format_gb(status["quota_gb"])}',
        f'• Остаток: {format_size(max(0, int(status["remaining_gb"] * GB)))}',
    ]
    if status['period_days_left'] is not None:
        lines.append(f'• До сброса: {status["period_days_left"]} дн.')
    if status['overage_bytes'] > 0:
        lines.append(f'• Перерасход: {format_size(status["overage_bytes"])}')
    return lines


async def traffic_quota_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    status = get_quota_status()
    if status['mode'] != 'quota':
        return

    remaining = float(status['remaining_gb'])
    if remaining <= 1024 and not _as_bool(get_setting('traffic_alert_sent_1tb', 'false')):
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
