#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json

import config
from telegram import Update
from telegram.ext import ContextTypes

from core.db import get_all_settings, get_setting, set_setting
from core.scheduler import schedule_daily_report_job
from security import safe_run_command, validate_google_drive_id
from services.system_info import get_service_scan_snapshot, resolve_manual_service_query
from services.traffic_quota import get_quota_summary_text
from ui.keyboards import (
    back_button,
    confirm_keyboard,
    prompt_back_keyboard,
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
        text,
        reply_markup=settings_keyboard(settings),
        parse_mode='HTML',
    )


async def show_traffic_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    settings = get_all_settings()
    text = (
        '📦 <b>Лимит трафика</b>\n\n'
        'Если тариф безлимитный — бот не будет слать предупреждения.\n'
        'Если у вас пакет, настрой размер и длительность расчётного периода.'
    )
    await query.edit_message_text(
        text,
        reply_markup=traffic_keyboard(settings),
        parse_mode='HTML',
    )


async def show_service_monitor_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, force: bool = False) -> None:
    query = update.callback_query
    await query.answer()
    scan = await get_service_scan_snapshot(context.application.bot_data, force=force)
    manual_items = _load_manual_services()

    auto_lines = [f'• {name}' for name in scan.get('auto', [])[:15]] or ['• Пока ничего не найдено']
    manual_lines = [f'• {item.get("label") or item.get("name")}' for item in manual_items[:15]] or ['• Нет']
    text = (
        '🧩 <b>Ключевые сервисы</b>\n\n'
        'Бот автоматически сканирует systemd-сервисы, процессы, Docker и популярные панели/VPN.\n'
        'Ручное добавление работает только для реально найденных сервисов и процессов.\n\n'
        '<b>Автоматически найдено</b>\n'
        + '\n'.join(auto_lines)
        + '\n\n<b>Добавлено вручную</b>\n'
        + '\n'.join(manual_lines)
    )
    if scan.get('docker_permission_needed'):
        text += (
            '\n\n🔐 Для отслеживания Docker-контейнеров нужен доступ к Docker socket. '
            'Если подтвердите, бот попросит минимально необходимые права для чтения контейнеров.'
        )
    await query.edit_message_text(
        text,
        reply_markup=service_monitor_keyboard(manual_items, bool(scan.get('docker_permission_needed'))),
        parse_mode='HTML',
    )


async def handle_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> bool:
    query = update.callback_query
    if data == 'settings_menu':
        await show_settings(update, context)
        return True
    if data == 'toggle_daily_report':
        current = get_setting('enable_daily_report', 'false')
        set_setting('enable_daily_report', 'false' if current == 'true' else 'true')
        await show_settings(update, context)
        return True
    if data == 'toggle_auto_update':
        current = get_setting('auto_update', 'false')
        set_setting('auto_update', 'false' if current == 'true' else 'true')
        await show_settings(update, context)
        return True
    if data in {'set_cpu_threshold', 'set_ram_threshold', 'set_disk_threshold'}:
        await query.answer()
        mapping = {
            'set_cpu_threshold': ('cpu_threshold', 'Введите новый порог CPU в процентах (например 85)'),
            'set_ram_threshold': ('ram_threshold', 'Введите новый порог RAM в процентах (например 90)'),
            'set_disk_threshold': ('disk_threshold', 'Введите новый порог SSD в процентах (например 90)'),
        }
        context.user_data['awaiting'] = mapping[data][0]
        await query.edit_message_text(mapping[data][1], reply_markup=None)
        return True
    if data == 'set_report_time':
        await query.answer()
        context.user_data['awaiting'] = 'report_time'
        await query.edit_message_text('Введите время ежедневного отчёта в формате HH:MM')
        return True
    if data == 'traffic_menu':
        await show_traffic_menu(update, context)
        return True
    if data == 'traffic_mode_unlimited':
        await query.answer('Трафик отмечен как безлимитный')
        set_setting('traffic_mode', 'unlimited')
        await show_traffic_menu(update, context)
        return True
    if data == 'traffic_mode_quota':
        await query.answer('Включён режим пакета трафика')
        set_setting('traffic_mode', 'quota')
        await show_traffic_menu(update, context)
        return True
    if data == 'traffic_set_quota':
        await query.answer()
        context.user_data['awaiting'] = 'traffic_quota_gb'
        await query.edit_message_text('Введите размер пакета трафика в GB. Например: 3072')
        return True
    if data == 'traffic_set_cycle':
        await query.answer()
        context.user_data['awaiting'] = 'traffic_cycle_days'
        await query.edit_message_text('Введите длительность расчётного периода в днях. Например: 30')
        return True
    if data == 'traffic_reset_cycle':
        await query.answer('Расчётный период сброшен')
        set_setting('traffic_cycle_start_date', '')
        set_setting('traffic_cycle_accumulated_bytes', '0')
        set_setting('traffic_last_total_bytes', '0')
        set_setting('traffic_lifetime_accumulated_bytes', '0')
        set_setting('traffic_last_raw_total_bytes', '0')
        set_setting('traffic_alert_sent_1tb', 'false')
        set_setting('traffic_alert_sent_300gb', 'false')
        await show_traffic_menu(update, context)
        return True
    if data == 'service_monitor_menu':
        await show_service_monitor_menu(update, context)
        return True
    if data == 'service_rescan':
        await query.answer('Пересканирую сервисы и процессы…')
        await show_service_monitor_menu(update, context, force=True)
        return True
    if data == 'service_add_systemd':
        await query.answer()
        context.user_data['awaiting'] = 'manual_service_systemd'
        await query.edit_message_text(
            'Введите имя systemd-сервиса.\n\nПримеры:\n• nginx\n• wg-quick@wg0\n• xray',
            reply_markup=prompt_back_keyboard('service_monitor_menu'),
        )
        return True
    if data == 'service_add_process':
        await query.answer()
        context.user_data['awaiting'] = 'manual_service_process'
        await query.edit_message_text(
            'Введите имя процесса или ключевое слово процесса.\n\nПримеры:\n• mtg\n• sing-box\n• remnawave',
            reply_markup=prompt_back_keyboard('service_monitor_menu'),
        )
        return True
    if data == 'service_add_docker':
        await query.answer()
        scan = await get_service_scan_snapshot(context.application.bot_data, force=True)
        if scan.get('docker_permission_needed'):
            await query.edit_message_text(
                '🔐 <b>Нужен доступ к Docker</b>\n\n'
                'Для отслеживания контейнеров боту нужен доступ к Docker socket.\n'
                'Если подтвердите, helper попробует выдать сервисному пользователю доступ к группе docker и перезапустить бота.',
                reply_markup=prompt_back_keyboard('service_monitor_menu'),
                parse_mode='HTML',
            )
            return True
        context.user_data['awaiting'] = 'manual_service_docker'
        await query.edit_message_text(
            'Введите имя Docker-контейнера или его часть.\n\nПримеры:\n• marzban\n• xray\n• remnawave',
            reply_markup=prompt_back_keyboard('service_monitor_menu'),
        )
        return True
    if data == 'service_grant_docker':
        await query.answer()
        await query.edit_message_text('⏳ Пытаюсь выдать доступ к Docker и перезапустить бота...', parse_mode='HTML')
        code, out, err = await safe_run_command(['sudo', config.ROOT_HELPER, 'grant-docker-access'], timeout=60)
        if code == 0:
            await query.edit_message_text(
                '✅ Доступ к Docker запрошен. Бот будет перезапущен, после чего можно заново открыть раздел ключевых сервисов.',
                reply_markup=prompt_back_keyboard('service_monitor_menu'),
                parse_mode='HTML',
            )
        else:
            await query.edit_message_text(
                '❌ Не удалось выдать доступ к Docker.\n\n'
                'Возможно, helper ещё не обновлён или группа docker отсутствует.',
                reply_markup=prompt_back_keyboard('service_monitor_menu'),
                parse_mode='HTML',
            )
        return True
    if data == 'service_clear_manual':
        await query.answer('Ручной список очищен')
        _save_manual_services([])
        await show_service_monitor_menu(update, context, force=True)
        return True
    if data.startswith('service_remove_'):
        try:
            idx = int(data.rsplit('_', 1)[1])
        except Exception:
            idx = -1
        items = _load_manual_services()
        if 0 <= idx < len(items):
            removed = items.pop(idx)
            _save_manual_services(items)
            await query.answer(f'Удалено: {removed.get("label") or removed.get("name")}')
        else:
            await query.answer('Запись не найдена')
        await show_service_monitor_menu(update, context, force=True)
        return True
    return False


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    awaiting = context.user_data.get('awaiting')
    if not awaiting:
        return False

    text = (update.message.text or '').strip()
    context.user_data.pop('awaiting', None)

    if awaiting in {'cpu_threshold', 'ram_threshold', 'disk_threshold'}:
        if not text.isdigit() or not 1 <= int(text) <= 100:
            await update.message.reply_text('❌ Нужны целые проценты от 1 до 100.')
            return True
        set_setting(awaiting, text)
        await update.message.reply_text('✅ Настройка сохранена.')
        return True

    if awaiting == 'report_time':
        if len(text) != 5 or text[2] != ':':
            await update.message.reply_text('❌ Формат времени должен быть HH:MM.')
            return True
        set_setting('report_time', text)
        schedule_daily_report_job(context.application)
        await update.message.reply_text('✅ Время отчёта сохранено.')
        return True

    if awaiting == 'traffic_quota_gb':
        try:
            value = int(text)
            if value <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text('❌ Введите целое число в GB, например 3072.')
            return True
        set_setting('traffic_quota_gb', str(value))
        set_setting('traffic_mode', 'quota')
        await update.message.reply_text('✅ Пакет трафика сохранён.')
        return True

    if awaiting == 'traffic_cycle_days':
        try:
            value = int(text)
            if value <= 0 or value > 365:
                raise ValueError
        except ValueError:
            await update.message.reply_text('❌ Введите число от 1 до 365.')
            return True
        set_setting('traffic_cycle_days', str(value))
        await update.message.reply_text('✅ Длительность расчётного периода сохранена.')
        return True

    if awaiting == 'google_drive_folder_id':
        if not validate_google_drive_id(text):
            await update.message.reply_text('❌ Похоже, это не ID папки Google Drive.')
            return True
        set_setting('google_drive_folder_id', text)
        await update.message.reply_text('✅ ID папки Google Drive сохранён.')
        return True

    if awaiting in {'manual_service_systemd', 'manual_service_process', 'manual_service_docker'}:
        service_type = awaiting.replace('manual_service_', '')
        resolved = await resolve_manual_service_query(service_type, text)
        if not resolved:
            context.user_data.pop('awaiting', None)
            await update.message.reply_text(
                '❌ Такой сервис не найден. Проверьте имя и попробуйте ещё раз. '
                'Бот добавляет только реально существующие systemd-сервисы, процессы или контейнеры.',
                reply_markup=back_button('service_monitor_menu', include_main_menu=True),
            )
            return True

        items = _load_manual_services()
        entry = {
            'type': resolved['type'],
            'name': resolved['name'],
            'label': resolved['label'],
        }
        for existing in items:
            if existing.get('type') == entry['type'] and existing.get('name') == entry['name']:
                context.user_data.pop('awaiting', None)
                await update.message.reply_text(
                    f'ℹ️ {entry["label"]} уже отслеживается.',
                    reply_markup=back_button('service_monitor_menu', include_main_menu=True),
                )
                return True
        items.append(entry)
        _save_manual_services(items)
        context.application.bot_data.pop('service_statuses', None)
        status_text = {
            'running': 'running',
            'stopped': 'stopped',
            'missing': 'not found',
        }.get(str(resolved.get('status') or '').strip().lower(), str(resolved.get('status') or 'unknown'))
        context.user_data.pop('awaiting', None)
        await update.message.reply_text(
            f'✅ Добавлено в ключевые сервисы: {entry["label"]} — {status_text}.',
            reply_markup=back_button('service_monitor_menu', include_main_menu=True),
        )
        return True

    return False
