#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import shutil
import subprocess
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


def get_traffic_interface() -> str:
    return str(get_setting('traffic_interface', 'eth0') or 'eth0').strip() or 'eth0'


def _parse_vnstat_oneline_bytes(output: str) -> Tuple[int, int] | None:
    text = (output or '').strip()
    if not text:
        return None
    parts = [item.strip() for item in text.split(';')]
    if len(parts) < 15:
        return None
    try:
        recv = int(parts[12])
        sent = int(parts[13])
        return sent, recv
    except Exception:
        return None


def _get_vnstat_counters(interface: str) -> Tuple[int, int] | None:
    vnstat_bin = shutil.which('vnstat')
    if not vnstat_bin:
        return None

    try:
        proc = subprocess.run(
            [vnstat_bin, '--oneline', 'b', '-i', interface],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception as exc:
        logger.debug('vnStat execution failed for %s: %s', interface, exc)
        return None

    if proc.returncode != 0:
        stderr = (proc.stderr or '').strip()
        if stderr:
            logger.debug('vnStat returned non-zero for %s: %s', interface, stderr)
        return None

    parsed = _parse_vnstat_oneline_bytes(proc.stdout)
    if parsed is None:
        logger.debug('Unable to parse vnStat oneline output for %s: %r', interface, proc.stdout)
    return parsed


def _get_psutil_counters(interface: str) -> Tuple[int, int]:
    counters = psutil.net_io_counters(pernic=True)
    nic = counters.get(interface)
    if nic is None:
        logger.warning('Traffic interface %s was not found in psutil.net_io_counters(pernic=True)', interface)
        return 0, 0
    return int(nic.bytes_sent), int(nic.bytes_recv)


def get_interface_counters(interface: str | None = None) -> Tuple[int, int]:
    target = (interface or get_traffic_interface()).strip()
    vnstat_counters = _get_vnstat_counters(target)
    if vnstat_counters is not None:
        return vnstat_counters
    return _get_psutil_counters(target)


def _raw_usage() -> Dict[str, int]:
    sent, recv = get_interface_counters()
    return {
        'sent': sent,
        'recv': recv,
        'total': sent + recv,
    }


def _save_total_snapshot(prefix: str, values: Dict[str, int]) -> None:
    set_setting(f'{prefix}_sent_bytes', str(int(values['sent'])))
    set_setting(f'{prefix}_recv_bytes', str(int(values['recv'])))
    set_setting(f'{prefix}_total_bytes', str(int(values['total'])))


def _load_total_snapshot(prefix: str, default: int = 0) -> Dict[str, int]:
    sent = _safe_int(get_setting(f'{prefix}_sent_bytes', ''), default)
    recv = _safe_int(get_setting(f'{prefix}_recv_bytes', ''), default)
    total = _safe_int(get_setting(f'{prefix}_total_bytes', ''), sent + recv if default >= 0 else default)
    if total < 0 and sent >= 0 and recv >= 0:
        total = sent + recv
    return {
        'sent': sent,
        'recv': recv,
        'total': total,
    }


def _compute_monotonic_value(raw_value: int, last_value: int, monotonic_value: int) -> int:
    if monotonic_value < 0:
        return raw_value
    if last_value < 0:
        last_value = raw_value
    delta = raw_value - last_value
    if delta >= 0:
        return monotonic_value + delta
    return monotonic_value + raw_value


def _update_monotonic_totals() -> Dict[str, int]:
    """Maintain interface counters that never decrease across reboot/service restart."""
    raw = _raw_usage()
    last_raw = _load_total_snapshot('traffic_last_raw', default=-1)
    monotonic = _load_total_snapshot('traffic_monotonic', default=-1)

    updated = {
        'sent': _compute_monotonic_value(raw['sent'], last_raw['sent'], monotonic['sent']),
        'recv': _compute_monotonic_value(raw['recv'], last_raw['recv'], monotonic['recv']),
    }
    updated['total'] = updated['sent'] + updated['recv']

    _save_total_snapshot('traffic_monotonic', updated)
    _save_total_snapshot('traffic_last_raw', raw)
    set_setting('traffic_last_total_updated_at', _now().isoformat(timespec='seconds'))
    return updated


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

    cycle_days = _safe_int(get_setting('traffic_cycle_days', '30'), 30)
    start = today
    hint = _date_or_none(get_setting('traffic_cycle_start_date', ''))
    if hint:
        start = hint
    elif cycle_days > 0:
        start = today
    end = start + timedelta(days=max(cycle_days, 1))
    return start, end


def _ensure_cycle_initialized(totals: Dict[str, int]) -> Tuple[date, date]:
    mode = get_setting('traffic_mode', 'unlimited')

    anchor_date = _date_or_none(get_setting('traffic_today_anchor_date', ''))
    if anchor_date is None:
        set_setting('traffic_today_anchor_date', _today().isoformat())
        _save_total_snapshot('traffic_today_anchor', totals)
        _save_total_snapshot('traffic_yesterday', {'sent': 0, 'recv': 0, 'total': 0})
    elif anchor_date != _today():
        today = _today()
        delta_days = (today - anchor_date).days
        previous_anchor = _load_total_snapshot('traffic_today_anchor', default=0)
        today_used = {
            'sent': max(0, totals['sent'] - previous_anchor['sent']),
            'recv': max(0, totals['recv'] - previous_anchor['recv']),
        }
        today_used['total'] = today_used['sent'] + today_used['recv']
        if delta_days == 1:
            _save_total_snapshot('traffic_yesterday', today_used)
        else:
            _save_total_snapshot('traffic_yesterday', {'sent': 0, 'recv': 0, 'total': 0})
        set_setting('traffic_today_anchor_date', today.isoformat())
        _save_total_snapshot('traffic_today_anchor', totals)

    if mode != 'quota':
        return _today(), _today()

    start = _date_or_none(get_setting('traffic_cycle_start_date', ''))
    activation = _date_or_none(get_setting('traffic_activation_date', ''))
    if not start:
        start = activation or _today()
        set_setting('traffic_cycle_start_date', start.isoformat())
        if not activation:
            set_setting('traffic_activation_date', start.isoformat())
        _save_total_snapshot('traffic_period_anchor', totals)
        _setdefault('traffic_alert_sent_1tb', 'false')
        _setdefault('traffic_alert_sent_300gb', 'false')

    start, end = _resolve_period(start)
    current_start = _date_or_none(get_setting('traffic_cycle_start_date', '')) or start
    if start != current_start:
        set_setting('traffic_cycle_start_date', start.isoformat())
        _save_total_snapshot('traffic_period_anchor', totals)
        set_setting('traffic_period_sync_used_bytes', '')
        set_setting('traffic_period_sync_total_bytes', '')
        set_setting('traffic_alert_sent_1tb', 'false')
        set_setting('traffic_alert_sent_300gb', 'false')
    return start, end


def sync_current_period_usage_from_hoster(used_bytes: int) -> None:
    totals = _update_monotonic_totals()
    start, _ = _ensure_cycle_initialized(totals)
    set_setting('traffic_cycle_start_date', start.isoformat())
    set_setting('traffic_period_sync_used_bytes', str(max(0, int(used_bytes))))
    set_setting('traffic_period_sync_total_bytes', str(totals['total']))
    set_setting('traffic_period_sync_set_at', _now().isoformat(timespec='seconds'))


def reset_current_period_anchor() -> None:
    totals = _update_monotonic_totals()
    start, _ = _ensure_cycle_initialized(totals)
    set_setting('traffic_cycle_start_date', start.isoformat())
    _save_total_snapshot('traffic_period_anchor', totals)
    set_setting('traffic_period_sync_used_bytes', '')
    set_setting('traffic_period_sync_total_bytes', '')
    set_setting('traffic_alert_sent_1tb', 'false')
    set_setting('traffic_alert_sent_300gb', 'false')


def get_quota_status() -> Dict[str, Any]:
    mode = get_setting('traffic_mode', 'unlimited')
    interface = get_traffic_interface()
    totals = _update_monotonic_totals()
    _ensure_cycle_initialized(totals)

    today_anchor = _load_total_snapshot('traffic_today_anchor', default=0)
    today_usage = {
        'sent': max(0, totals['sent'] - today_anchor['sent']),
        'recv': max(0, totals['recv'] - today_anchor['recv']),
    }
    today_usage['total'] = today_usage['sent'] + today_usage['recv']
    yesterday_usage = _load_total_snapshot('traffic_yesterday', default=0)

    if mode != 'quota':
        return {
            'mode': 'unlimited',
            'interface': interface,
            'label': f'Безлимитный трафик ({interface})',
            'remaining_gb': None,
            'used_gb': None,
            'quota_gb': None,
            'total_bytes': totals['total'],
            'total_sent_bytes': totals['sent'],
            'total_recv_bytes': totals['recv'],
            'yesterday_bytes': yesterday_usage['total'],
            'yesterday_sent_bytes': yesterday_usage['sent'],
            'yesterday_recv_bytes': yesterday_usage['recv'],
            'today_bytes': today_usage['total'],
            'today_sent_bytes': today_usage['sent'],
            'today_recv_bytes': today_usage['recv'],
            'current_bytes': today_usage['total'],
            'period_used_bytes': None,
            'period_used_sent_bytes': None,
            'period_used_recv_bytes': None,
            'days_left': None,
            'cycle_end': None,
        }

    quota_gb = _safe_float(get_setting('traffic_quota_gb', '3072'), 3072.0)
    start, end = _resolve_period(_date_or_none(get_setting('traffic_cycle_start_date', '')))
    anchor_totals = _load_total_snapshot('traffic_period_anchor', default=0)
    period_usage = {
        'sent': max(0, totals['sent'] - anchor_totals['sent']),
        'recv': max(0, totals['recv'] - anchor_totals['recv']),
    }
    period_usage['total'] = period_usage['sent'] + period_usage['recv']

    sync_used = get_setting('traffic_period_sync_used_bytes', '')
    sync_total = get_setting('traffic_period_sync_total_bytes', '')
    if str(sync_used).strip() != '' and str(sync_total).strip() != '':
        sync_used_bytes = _safe_int(sync_used, 0)
        sync_total_bytes = _safe_int(sync_total, totals['total'])
        period_usage['total'] = max(period_usage['total'], sync_used_bytes + max(0, totals['total'] - sync_total_bytes))

    if period_usage['total'] > totals['total']:
        period_usage['total'] = totals['total']

    used_gb = period_usage['total'] / GB
    remaining_gb = max(0.0, quota_gb - used_gb)
    overage_gb = max(0.0, used_gb - quota_gb)
    days_left = max(0, (end - _today()).days)
    overage_price_rub_per_tb = _safe_float(get_setting('traffic_overage_price_rub_per_tb', '200'), 200.0)

    return {
        'mode': 'quota',
        'interface': interface,
        'used_gb': used_gb,
        'remaining_gb': remaining_gb,
        'quota_gb': quota_gb,
        'label': f'{format_gb(used_gb)} из {format_gb(quota_gb)} ({interface})',
        'cycle_start': start.isoformat(),
        'cycle_end': end.isoformat(),
        'days_left': days_left,
        'overage_gb': overage_gb,
        'overage_price_rub_per_tb': overage_price_rub_per_tb,
        'total_bytes': totals['total'],
        'total_sent_bytes': totals['sent'],
        'total_recv_bytes': totals['recv'],
        'yesterday_bytes': yesterday_usage['total'],
        'yesterday_sent_bytes': yesterday_usage['sent'],
        'yesterday_recv_bytes': yesterday_usage['recv'],
        'today_bytes': today_usage['total'],
        'today_sent_bytes': today_usage['sent'],
        'today_recv_bytes': today_usage['recv'],
        'current_bytes': today_usage['total'],
        'period_used_bytes': period_usage['total'],
        'period_used_sent_bytes': period_usage['sent'],
        'period_used_recv_bytes': period_usage['recv'],
    }


def get_quota_summary_text() -> str:
    status = get_quota_status()
    if status['mode'] == 'unlimited':
        return (
            f'Трафик {status["interface"]}: '
            f'↑ {format_size(status["total_sent_bytes"])} / '
            f'↓ {format_size(status["total_recv_bytes"])}'
        )
    return (
        f"Трафик {status['interface']}: ↑ {format_size(status['period_used_sent_bytes'])} / "
        f"↓ {format_size(status['period_used_recv_bytes'])}, "
        f"всего {format_size(status['period_used_bytes'])} из {format_gb(status['quota_gb'])}, "
        f"остаток {format_gb(status['remaining_gb'])} до {status['cycle_end']}"
    )


def get_dashboard_traffic_lines() -> list[str]:
    status = get_quota_status()
    if status['mode'] == 'unlimited':
        return [
            f'• Интерфейс: {status["interface"]}',
            f'• Всего: ↑ {format_size(status["total_sent_bytes"])} / ↓ {format_size(status["total_recv_bytes"])}',
            f'• Сегодня: ↑ {format_size(status["today_sent_bytes"])} / ↓ {format_size(status["today_recv_bytes"])}',
            f'• Вчера: ↑ {format_size(status["yesterday_sent_bytes"])} / ↓ {format_size(status["yesterday_recv_bytes"])}',
            '• Статус: безлимитный',
        ]
    lines = [
        f'• Интерфейс: {status["interface"]}',
        f'• Всего: ↑ {format_size(status["total_sent_bytes"])} / ↓ {format_size(status["total_recv_bytes"])}',
        f'• Сегодня: ↑ {format_size(status["today_sent_bytes"])} / ↓ {format_size(status["today_recv_bytes"])}',
        f'• Вчера: ↑ {format_size(status["yesterday_sent_bytes"])} / ↓ {format_size(status["yesterday_recv_bytes"])}',
        f'• Период: ↑ {format_size(status["period_used_sent_bytes"])} / ↓ {format_size(status["period_used_recv_bytes"])}',
        f'• Период всего: {format_size(status["period_used_bytes"])} из {format_gb(status["quota_gb"])}',
        f'• Остаток пакета: {format_gb(status["remaining_gb"])} • До сброса: {status["days_left"]} дн.',
    ]
    if float(status.get('overage_gb') or 0.0) > 0:
        lines.append(f'• Перерасход: {format_gb(status["overage_gb"])}')
    return lines


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
