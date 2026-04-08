#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from datetime import datetime
from typing import Any, Dict, List

from telegram.ext import ContextTypes

import config
from core.db import (
    get_backup_result,
    get_daily_metrics_summary,
    get_daily_top_processes,
    get_due_vps,
    get_previous_day_alert_count,
    get_setting,
)
from core.formatting import compact_bar, days_left_text, escape_html, format_size
from services.certificates import get_expiring_certificates
from services.system_info import get_service_statuses, get_system_update_cache
from services.traffic_quota import get_dashboard_traffic_lines, get_quota_status
from services.vps_service import build_vps_summary
from services.updater import get_current_version


def _service_icon(status: str) -> str:
    status = str(status).lower()
    if status == 'running':
        return '🟢'
    if status == 'stopped':
        return '🟡'
    return '🔴'


def _load_status(snapshot: Dict[str, Any]) -> str:
    cores = max(1, int(snapshot.get('cpu_cores') or snapshot.get('cpu_count') or 1))
    ratio = float(snapshot.get('load1') or 0.0) / cores
    if ratio < 0.70:
        return f'🟢 Низкая ({snapshot["load1"]:.2f})'
    if ratio < 1.20:
        return f'🟡 Нормальная ({snapshot["load1"]:.2f})'
    return f'🔴 Высокая ({snapshot["load1"]:.2f})'


def _backup_age_line() -> str:
    backup_info = get_backup_result()
    raw = str(backup_info.get('last_backup_success') or '').strip()
    if not raw:
        return '• Последний бэкап: ещё не выполнялся'
    try:
        dt = datetime.fromisoformat(raw)
        days = max(0, (datetime.now() - dt).days)
        if days == 0:
            return '• Последний бэкап: сегодня'
        if days == 1:
            return '• Последний бэкап: 1 день назад'
        return f'• Последний бэкап: {days} дн. назад'
    except Exception:
        return f'• Последний бэкап: {escape_html(raw)}'


async def build_dashboard_text(
    first_name: str,
    bot_data: Dict[str, Any],
    snapshot: Dict[str, Any],
) -> str:
    geo = snapshot['public_geo']
    service_lines = []
    for name, status in snapshot['services'].items():
        service_lines.append(f'{_service_icon(status)} {escape_html(name)}: {escape_html(status)}')

    due_vps = build_vps_summary(30)
    certs = await get_expiring_certificates(bot_data, 30)
    cert_lines = [
        f'⚠️ {escape_html(item["common_name"])} — {days_left_text(item["days_left"])}'
        for item in certs[:5]
    ]
    network_state = bot_data.get('network_state', {})
    tx = format_size(float(network_state.get('tx_rate_bps', 0.0)))
    rx = format_size(float(network_state.get('rx_rate_bps', 0.0)))
    updates_cache = await get_system_update_cache(bot_data)
    updates = updates_cache.get('count')
    updates_line = 'Проверка не выполнялась'
    if updates is not None:
        updates_line = 'Система актуальна' if int(updates) == 0 else f'Доступно обновлений: {updates}'

    text = [
        f'👋 <b>{escape_html(first_name or "Администратор")}</b>, это главное меню <b>{escape_html(config.SERVER_NAME)}</b>.',
        '',
        '<b>Текущая сводка</b>',
        f'CPU  {snapshot["cpu_percent"]:.1f}% {compact_bar(snapshot["cpu_percent"])}',
        f'RAM  {snapshot["ram_percent"]:.1f}% {compact_bar(snapshot["ram_percent"])}',
        f'SSD  {snapshot["disk_percent"]:.1f}% {compact_bar(snapshot["disk_percent"])}',
        f'NET  ↑ {tx}/s  ↓ {rx}/s',
        f'UP   {escape_html(snapshot["uptime"])}',
        '',
        '<b>Сервер</b>',
        f'• ОС: {escape_html(snapshot["os_name"])}',
        f'• {escape_html(geo.get("city", "N/A"))}, {escape_html(geo.get("country", "N/A"))} • {escape_html(geo.get("ip", "N/A"))}',
        f'• Версия бота: {escape_html(get_current_version())}',
        f'• Нагрузка: {_load_status(snapshot)}',
        f'• Обновления: {updates_line}',
    ]
    # Inline extend keeps formatting compact and readable.
    text.extend(get_dashboard_traffic_lines())
    text.append(_backup_age_line())

    if due_vps:
        text.extend(['', '<b>Скоро закончится аренда VPS</b>', *due_vps])

    if cert_lines:
        text.extend(['', '<b>Сертификаты до 30 дней</b>', *cert_lines])

    if service_lines:
        text.extend(['', '<b>Ключевые сервисы</b>', *service_lines[:12]])

    text.extend(['', 'Нажми кнопку ниже для действия или обнови данные.'])
    return '\n'.join(text)


async def build_daily_report(bot_data: Dict[str, Any]) -> str:
    summary = get_daily_metrics_summary()
    target_day = summary['target_day']
    if not summary.get('samples'):
        return (
            '📊 <b>Ежедневный отчёт</b>\n\n'
            f'За {target_day:%d.%m.%Y} данных ещё недостаточно. '
            'Оставь бота включённым хотя бы на сутки.'
        )

    top_cpu = get_daily_top_processes('cpu')
    top_ram = get_daily_top_processes('ram')
    certs = await get_expiring_certificates(bot_data, 30)
    due_vps = get_due_vps(30)
    quota = get_quota_status()
    backup_info = get_backup_result()
    alerts = get_previous_day_alert_count()
    services = await get_service_statuses(bot_data)
    updates_cache = await get_system_update_cache(bot_data)

    highlights: List[str] = []
    if float(summary.get('avg_cpu') or 0) >= 70:
        highlights.append('• Средняя загрузка CPU была заметно высокой.')
    if float(summary.get('avg_ram') or 0) >= 80:
        highlights.append('• Память большую часть дня была близка к пределу.')
    if alerts:
        highlights.append(f'• За сутки сработало алертов: {alerts}.')
    if quota['mode'] == 'quota' and float(quota['remaining_gb']) <= 1024:
        highlights.append(
            f'• До конца пакета трафика осталось {quota["remaining_gb"]:.0f} GB.'
        )
    if certs:
        highlights.append('• Есть сертификаты, требующие внимания в ближайшие 30 дней.')
    if updates_cache.get('count'):
        highlights.append(
            f'• Доступны системные обновления: {updates_cache.get("count")} пакет(ов).'
        )
    if not highlights:
        highlights.append('• Сутки прошли спокойно, критичных отклонений не найдено.')

    report = [
        '📊 <b>Ежедневный отчёт</b>',
        f'Дата: <b>{target_day:%d.%m.%Y}</b>',
        '',
        '<b>Главное за сутки</b>',
        *highlights,
        '',
        '<b>Средние значения за предыдущий день</b>',
        f'CPU: {float(summary.get("avg_cpu") or 0):.1f}% (пик {float(summary.get("max_cpu") or 0):.1f}%)',
        f'RAM: {float(summary.get("avg_ram") or 0):.1f}% (пик {float(summary.get("max_ram") or 0):.1f}%)',
        f'SSD: {float(summary.get("avg_disk") or 0):.1f}% (пик {float(summary.get("max_disk") or 0):.1f}%)',
        f'Load average: {float(summary.get("avg_load1") or 0):.2f} / {float(summary.get("avg_load5") or 0):.2f} / {float(summary.get("avg_load15") or 0):.2f}',
        f'Трафик за сутки: ↑ {format_size(summary.get("traffic_sent") or 0)} / ↓ {format_size(summary.get("traffic_recv") or 0)}',
        '',
        '<b>Топ процессов по CPU</b>',
    ]

    for item in top_cpu[:5]:
        report.append(
            f'• {escape_html(item["process_name"])} — {float(item["max_cpu"] or 0):.1f}%'
        )

    report.extend(['', '<b>Топ процессов по RAM</b>'])
    for item in top_ram[:5]:
        report.append(
            f'• {escape_html(item["process_name"])} — '
            f'{float(item["max_memory_percent"] or 0):.1f}% '
            f'({float(item["max_memory_mb"] or 0):.1f} MB)'
        )

    report.extend(['', '<b>Что ещё полезно знать</b>'])
    report.append(f'• Алертов за сутки: {alerts}')
    if backup_info['last_backup_success']:
        report.append(
            f'• Последний бэкап: {escape_html(backup_info["last_backup_success"])} '
            f'({escape_html(backup_info["last_backup_size_mb"])} MB)'
        )
    else:
        report.append('• Последний бэкап: ещё не зафиксирован')

    if quota['mode'] == 'quota':
        report.append(
            f'• Остаток трафика: {quota["remaining_gb"]:.0f} GB из {quota["quota_gb"]:.0f} GB'
        )
    else:
        report.append('• Трафик: безлимитный')

    if due_vps:
        report.append('• VPS к продлению:')
        for item in due_vps[:5]:
            report.append(
                f'  - {escape_html(item["name"])} — {days_left_text(item["days_left"])}'
            )

    if certs:
        report.append('• Сертификаты до 30 дней:')
        for item in certs[:5]:
            report.append(
                f'  - {escape_html(item["common_name"])} — {days_left_text(item["days_left"])}'
            )

    if services:
        report.append('• Сервисы:')
        for name, status in list(services.items())[:5]:
            report.append(f'  - {escape_html(name)}: {escape_html(status)}')

    return '\n'.join(report)


async def daily_report_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    if get_setting('enable_daily_report', 'false') != 'true':
        return
    report = await build_daily_report(context.application.bot_data)
    await context.bot.send_message(
        chat_id=context.application.bot_data['admin_id'],
        text=report,
        parse_mode='HTML',
    )
