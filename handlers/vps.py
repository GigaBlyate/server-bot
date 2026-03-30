#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from datetime import date

from telegram import Update
from telegram.ext import ContextTypes

from core.db import add_vps, delete_vps, get_vps_list, update_vps_expiry
from core.formatting import days_left_text, escape_html
from services.vps_service import extend_vps_date
from ui.keyboards import calendar_keyboard, vps_actions_keyboard, vps_menu_keyboard


async def show_vps_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query:
        await query.answer()
    rows = get_vps_list()
    if rows:
        today = date.today()
        lines = ['📋 <b>VPS и аренда</b>', '']
        for item in rows[:15]:
            days_left = (date.fromisoformat(item['expiry_date']) - today).days
            prefix = '🚨' if days_left <= 5 else '⚠️' if days_left <= 30 else '•'
            lines.append(
                f"{prefix} <b>{escape_html(item['name'])}</b> — "
                f"{days_left_text(days_left)} ({item['expiry_date']})"
            )
        text = '\n'.join(lines)
    else:
        text = '📋 <b>VPS и аренда</b>\n\nСписок пуст. Можно добавить новый VPS ниже.'
    keyboard = vps_menu_keyboard(rows)
    if query:
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode='HTML')
    else:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode='HTML')


async def handle_vps_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> bool:
    query = update.callback_query
    if data == 'vps_menu':
        await show_vps_menu(update, context)
        return True
    if data == 'vps_add':
        await query.answer()
        context.user_data['awaiting'] = 'vps_name'
        await query.edit_message_text('✍️ Введите название VPS одним сообщением.')
        return True
    if data.startswith('vps_open_'):
        await query.answer()
        vps_id = int(data.split('_')[2])
        item = next((row for row in get_vps_list() if int(row['id']) == vps_id), None)
        if not item:
            await query.edit_message_text(
                '❌ VPS не найден.',
                reply_markup=vps_menu_keyboard(get_vps_list()),
            )
            return True
        days_left = (date.fromisoformat(item['expiry_date']) - date.today()).days
        text = (
            f'🖥️ <b>{escape_html(item["name"])}</b>\n\n'
            f'Дата окончания: <code>{item["expiry_date"]}</code>\n'
            f'Осталось: <b>{days_left_text(days_left)}</b>'
        )
        await query.edit_message_text(
            text,
            reply_markup=vps_actions_keyboard(vps_id),
            parse_mode='HTML',
        )
        return True
    if data.startswith('vps_extend_'):
        await query.answer('Дата продлена')
        _, _, raw_id, duration_code = data.split('_')
        vps_id = int(raw_id)
        item = next((row for row in get_vps_list() if int(row['id']) == vps_id), None)
        if item:
            new_expiry = extend_vps_date(item['expiry_date'], duration_code)
            update_vps_expiry(vps_id, new_expiry)
        await show_vps_menu(update, context)
        return True
    if data.startswith('vps_delete_'):
        await query.answer('VPS удалён')
        vps_id = int(data.split('_')[2])
        delete_vps(vps_id)
        await show_vps_menu(update, context)
        return True
    if data == 'vps_cancel_add':
        await query.answer('Добавление отменено')
        context.user_data.pop('pending_vps_name', None)
        context.user_data.pop('awaiting', None)
        await show_vps_menu(update, context)
        return True
    if data.startswith('vps_cal_prev_') or data.startswith('vps_cal_next_'):
        await query.answer()
        _, _, direction, year, month = data.split('_')
        year_i = int(year)
        month_i = int(month)
        if direction == 'prev':
            month_i -= 1
            if month_i == 0:
                month_i = 12
                year_i -= 1
        else:
            month_i += 1
            if month_i == 13:
                month_i = 1
                year_i += 1
        await query.edit_message_reply_markup(reply_markup=calendar_keyboard(year_i, month_i))
        return True
    if data.startswith('vps_pick_'):
        await query.answer('Дата выбрана')
        _, _, year, month, day = data.split('_')
        name = context.user_data.pop('pending_vps_name', None)
        if not name:
            await query.edit_message_text(
                '❌ Сначала введите имя VPS.',
                reply_markup=vps_menu_keyboard(get_vps_list()),
            )
            return True
        expiry_date = date(int(year), int(month), int(day)).isoformat()
        add_vps(name, expiry_date)
        await query.edit_message_text(
            f'✅ VPS <b>{escape_html(name)}</b> добавлен.\n'
            f'Дата окончания: <code>{expiry_date}</code>',
            reply_markup=vps_menu_keyboard(get_vps_list()),
            parse_mode='HTML',
        )
        return True
    if data == 'noop':
        await query.answer()
        return True
    return False


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    awaiting = context.user_data.get('awaiting')
    if awaiting != 'vps_name':
        return False
    context.user_data.pop('awaiting', None)
    name = (update.message.text or '').strip()
    if not name:
        await update.message.reply_text('❌ Имя VPS не может быть пустым.')
        return True
    context.user_data['pending_vps_name'] = name
    today = date.today()
    await update.message.reply_text(
        '📅 Теперь выберите дату окончания аренды.',
        reply_markup=calendar_keyboard(today.year, today.month),
    )
    return True
