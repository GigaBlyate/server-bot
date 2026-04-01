#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json

import config
from telegram import Update
from telegram.ext import ContextTypes

from core.db import get_all_settings, get_setting, set_setting
from core.scheduler import schedule_daily_report_job
from security import safe_run_command, validate_google_drive_id
from services.system_info import find_manual_service_candidate, get_service_scan_snapshot
from services.traffic_quota import (
    get_quota_summary_text,
    get_quota_status,
    reset_current_period_anchor,
    sync_current_period_usage_from_hoster,
)
from ui.keyboards import (
    back_main_keyboard,
    service_monitor_keyboard,
    settings_keyboard,
    traffic_keyboard,
)


def _load_manual_services() -> list[dict]:
    raw = str(get_setting('manual_services_json', '[]') or '[]')
    try:
        payload = json.loads(raw)
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
    except Exception:
        pass
    return []


def _save_manual_services(items: list[dict]) -> None:
    set_setting('manual_services_json', json.dumps(items, ensure_ascii=False))


def _humanize(name: str) -> str:
    clean = name.replace('.service', '').replace('_', ' ').replace('-', ' ').strip()
    return ' '.join(word.capitalize() for word in clean.split()) or name


async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    settings = get_all_settings()
    text = (
        '⚙️ <b>Настройки</b>\n\n'
        'Здесь собраны только полезные рабочие параметры: пороги, отчёт, '
        'лимит трафика, обновление сервера, обновление бота, бэкап и ключевые сервисы.\n\n'
        f'Текущий режим трафика: <b>{get_quota_summary_text()}</b>'
    )
    await query.edit_message_text(
        '\n'.join(text),
        reply_markup=traffic_keyboard(settings),
        parse_mode='HTML',
    )

