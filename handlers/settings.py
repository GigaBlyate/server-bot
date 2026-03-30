#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from telegram import Update
from telegram.ext import ContextTypes

from core.db import get_all_settings, get_setting, set_setting
from core.scheduler import schedule_daily_report_job
from security import validate_google_drive_id
from services.traffic_quota import get_quota_summary_text
from ui.keyboards import settings_keyboard, traffic_keyboard


async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    settings = get_all_settings()
    text = (
        '⚙️ <b>Настройки</b>\n\n'
        'Здесь собраны только полезные рабочие параметры: пороги, отчёт, '
        'лимит трафика, обновление сервера, обновление бота и бэкап.\n\n'
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
        set_setting('traffic_alert_sent_1tb', 'false')
        set_setting('traffic_alert_sent_300gb', 'false')
        await show_traffic_menu(update, context)
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

    return False
