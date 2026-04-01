#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Any, Dict, Tuple

import psutil
from telegram.ext import ContextTypes

from core.db import get_setting, set_setting
from core.formatting import format_gb, format_size

logger = logging.getLogger(__name__)
GB = 1024 ** 3
TB_GB = 1024


def _as_bool(value: str) -> bool:
    return str(value).lower() == 'true'


def _today() -> date:
    return datetime.now().date()


def _now() -> datetime:
    return datetime.now()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value).strip()))
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).strip().replace(',', '.'))
    except Exception:
        return default


def _date_or_none(raw: Any) -> date | None:
    try:
        text = str(raw or '').strip()
        return date.fromisoformat(text) if text else None
    except Exception:
        return None


def _setdefault(key: str, value: Any) -> Any:
    current = get_setting(key, None)
    if current in (None, ''):
        set_setting(key, value)
        return value
    return current


def _raw_total_bytes() -> int:
    c = psutil.net_io_counters()
    return int(c.bytes_sent) + int(c.bytes_recv)


def _update_monotonic_total() -> int:
    """Maintain a total counter that never decreases across reboot/service restart."""
    raw_total = _raw_total_bytes()
    last_raw = _safe_int(get_setting('traffic_last_raw_total_bytes', ''), -1)
    monotonic_total = _safe_int(get_setting('traffic_monotonic_total_bytes', ''), -1)

    if monotonic_total < 0:
        monotonic_total = raw_total
        set_setting('traffic_monotonic_total_bytes', str(monotonic_total))
        set_setting('traffic_last_raw_total_bytes', str(raw_total))
        set_setting('traffic_last_total_updated_at', _now().isoformat(timespec='seconds'))
        return monotonic_total

    if last_raw < 0:
        last_raw = raw_total

    delta = raw_total - last_raw
    if delta >= 0:
        monotonic_total += delta
    else:
        # System counters were reset (reboot / interface reset). Count from zero again.
        monotonic_total += raw_total

    set_setting('traffic_monotonic_total_bytes', str(monotonic_total))
    set_setting('traffic_last_raw_total_bytes', str(raw_total))
    set_setting('traffic_last_total_updated_at', _now().isoformat(timespec='seconds'))
    return monotonic_total


def _advance_month(anchor: date) -> date:
    year = anchor.year + (anchor.month // 12)
    month = 1 if anchor.month == 12 else anchor.month + 1
    if anchor.month != 12:
        year = anchor.year
    target_day = min(anchor.day, monthrange(year, month)[1])
    return date(year, month, target_day)


def _resolve_period(start_hint: date | None = None) -> Tuple[date, date]:
    today = _today()
    activation = _date_or_none(get_setting('traffic_activation_date', ''))
    current_start = _date_or_none(get_setting('traffic_cycle_start_date', ''))

    if start_hint:
        start = start_hint
        end = _advance_month(start)
        return start, end

    if current_start:
        start = current_start
        end = _advance_month(start)
        # keep rolling until today is in period
        while today >= end:
            start = end
            end = _advance_month(start)
        while today < start:
            prev_month_last = start - timedelta(days=1)
            start = date(prev_month_last.year, prev_month_last.month, min(start.day, monthrange(prev_month_last.year, prev_month_last.month)[1]))
            end = _advance_month(start)
        return start, end

    if activation:
        start = activation
        end = _advance_month(start)
        while today >= end:
            start = end
            end = _advance_month(start)
        return start, end

    # Fallback for old installs: keep previous day-based semantics only until first proper cycle is initialized.
    cycle_days = _safe_int(get_setting('traffic_cycle_days', '30'), 30)
    start = today
    hint = _date_or_none(get_setting('traffic_cycle_start_date', ''))
    if hint:
        start = hint
    elif cycle_days > 0:
        start = today
    end = start + timedelta(days=max(cycle_days, 1))
    return start, end


def _ensure_cycle_initialized(total_bytes: int) -> Tuple[date, date]:
    mode = get_setting('traffic_mode', 'unlimited')
    if mode != 'quota':
        return _today(), _today()

    start = _date_or_none(get_setting('traffic_cycle_start_date', ''))
    activation = _date_or_none(get_setting('traffic_activation_date', ''))
    if not start:
        start = activation or _today()
        set_setting('traffic_cycle_start_date', start.isoformat())
        if not activation:
            set_setting('traffic_activation_date', start.isoformat())
        _setdefault('traffic_period_anchor_total_bytes', str(total_bytes))
        _setdefault('traffic_alert_sent_1tb', 'false')
        _setdefault('traffic_alert_sent_300gb', 'false')

    # Today / yesterday anchors
    anchor_date = _date_or_none(get_setting('traffic_today_anchor_date', ''))
    if anchor_date is None:
        set_setting('traffic_today_anchor_date', _today().isoformat())
        set_setting('traffic_today_anchor_total_bytes', str(total_bytes))
        set_setting('traffic_yesterday_total_bytes', '0')
    elif anchor_date != _today():
        today = _today()
        delta_days = (today - anchor_date).days
        today_used = max(0, total_bytes - _safe_int(get_setting('traffic_today_anchor_total_bytes', '0')))
        if delta_days == 1:
            set_setting('traffic_yesterday_total_bytes', str(today_used))
        else:
            set_setting('traffic_yesterday_total_bytes', '0')
        set_setting('traffic_today_anchor_date', today.isoformat())
        set_setting('traffic_today_anchor_total_bytes', str(total_bytes))

    start, end = _resolve_period(start)
    current_start = _date_or_none(get_setting('traffic_cycle_start_date', '')) or start
    if start != current_start:
        # period has rolled over automatically
        set_setting('traffic_cycle_start_date', start.isoformat())
        set_setting('traffic_period_anchor_total_bytes', str(total_bytes))
        set_setting('traffic_period_sync_used_bytes', '')
        set_setting('traffic_period_sync_total_bytes', '')
        set_setting('traffic_alert_sent_1tb', 'false')
        set_setting('traffic_alert_sent_300gb', 'false')
    return start, end


def sync_current_period_usage_from_hoster(used_bytes: int) -> None:
    total_bytes = _update_monotonic_total()
    start, _ = _ensure_cycle_initialized(total_bytes)
    set_setting('traffic_cycle_start_date', start.isoformat())
    set_setting('traffic_period_sync_used_bytes', str(max(0, int(used_bytes))))
    set_setting('traffic_period_sync_total_bytes', str(total_bytes))
    set_setting('traffic_period_sync_set_at', _now().isoformat(timespec='seconds'))


def reset_current_period_anchor() -> None:
    total_bytes = _update_monotonic_total()
    start, _ = _ensure_cycle_initialized(total_bytes)
    set_setting('traffic_cycle_start_date', start.isoformat())
    set_setting('traffic_period_anchor_total_bytes', str(total_bytes))
    set_setting('traffic_period_sync_used_bytes', '')
    set_setting('traffic_period_sync_total_bytes', '')
    set_setting('traffic_alert_sent_1tb', 'false')
    set_setting('traffic_alert_sent_300gb', 'false')


def get_quota_status() -> Dict[str, Any]:
    mode = get_setting('traffic_mode', 'unlimited')
    total_bytes = _update_monotonic_total()
    _ensure_cycle_initialized(total_bytes)

    today_anchor = _safe_int(get_setting('traffic_today_anchor_total_bytes', '0'))
    today_bytes = max(0, total_bytes - today_anchor)
    yesterday_bytes = _safe_int(get_setting('traffic_yesterday_total_bytes', '0'))

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
            'current_bytes': today_bytes,
            'period_used_bytes': None,
            'days_left': None,
            'cycle_end': None,
        }

    quota_gb = _safe_float(get_setting('traffic_quota_gb', '3072'), 3072.0)
    start, end = _resolve_period(_date_or_none(get_setting('traffic_cycle_start_date', '')))
    anchor_total = _safe_int(get_setting('traffic_period_anchor_total_bytes', '0'))
    period_used_bytes = max(0, total_bytes - anchor_total)

    sync_used = get_setting('traffic_period_sync_used_bytes', '')
    sync_total = get_setting('traffic_period_sync_total_bytes', '')
    if str(sync_used).strip() != '' and str(sync_total).strip() != '':
        sync_used_bytes = _safe_int(sync_used, 0)
        sync_total_bytes = _safe_int(sync_total, total_bytes)
        period_used_bytes = max(period_used_bytes, sync_used_bytes + max(0, total_bytes - sync_total_bytes))

    # Safety: period usage must never exceed total usage tracked by bot.
    if period_used_bytes > total_bytes:
        period_used_bytes = total_bytes

    used_gb = period_used_bytes / GB
    remaining_gb = max(0.0, quota_gb - used_gb)
    days_left = max(0, (end - _today()).days)

    return {
        'mode': 'quota',
        'used_gb': used_gb,
        'remaining_gb': remaining_gb,
        'quota_gb': quota_gb,
        'label': f'{format_gb(used_gb)} из {format_gb(quota_gb)}',
        'cycle_start': start.isoformat(),
        'cycle_end': end.isoformat(),
        'days_left': days_left,
        'total_bytes': total_bytes,
        'yesterday_bytes': yesterday_bytes,
        'today_bytes': today_bytes,
        'current_bytes': today_bytes,
        'period_used_bytes': period_used_bytes,
    }


def get_quota_summary_text() -> str:
    status = get_quota_status()
    if status['mode'] == 'unlimited':
        return f'Трафик: безлимитный, всего {format_size(status["total_bytes"])}'
    return (
        f"Трафик: {format_size(status['period_used_bytes'])} из {format_gb(status['quota_gb'])}, "
        f"остаток {format_gb(status['remaining_gb'])} до {status['cycle_end']}"
    )


def get_dashboard_traffic_lines() -> list[str]:
    status = get_quota_status()
    if status['mode'] == 'unlimited':
        return [
            f'• Трафик: всего {format_size(status["total_bytes"])}',
            f'• Вчера: {format_size(status["yesterday_bytes"])} • Сегодня: {format_size(status["today_bytes"])}',
            '• Статус: безлимитный',
        ]
    return [
        f'• Трафик: всего {format_size(status["total_bytes"])}',
        f'• Вчера: {format_size(status["yesterday_bytes"])} • Сегодня: {format_size(status["today_bytes"])}',
        f'• Период: {format_size(status["period_used_bytes"])} из {format_gb(status["quota_gb"])}',
        f'• Остаток пакета: {format_gb(status["remaining_gb"])} • До сброса: {status["days_left"]} дн.',
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
