#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from datetime import date

from telegram import Update
from telegram.ext import ContextTypes

from core.db import add_vps, delete_vps, get_vps_list, update_vps_expiry
from core.formatting import days_left_text, escape_html
from services.vps_service import calculate_vps_extension
from ui.keyboards import calendar_keyboard, vps_actions_keyboard, vps_menu_keyboard


def _find_vps(vps_id: int):
    return next((row for row in get_vps_list() if int(row['id']) == vps_id), None)


async def _open_vps_card(query, vps_id: int) -> None:
    item = _find_vps(vps_id)
    if not item:
        await query.edit_message_text(
            '❌ VPS не найден.',
            reply_markup=vps_menu_keyboard(get_vps_list()),
        )
        return

    days_left = (date.fromisoformat(item['expiry_date']) - date.today()).days
    text = (
        f'🖥️ <b>{escape_html(item["name"])}</b>\n\n'
        f'Дата окончания: <code>{item["expiry_date"]}</code>\n'
        f'Осталось: <b>{days_left_text(days_left)}</b>\n\n'
        'Можно быстро продлить срок кнопками ниже или выбрать точную дату из личного кабинета.'
    )
    await query.edit_message_text(
        text,
        reply_markup=vps_actions_keyboard(vps_id),
        parse_mode='HTML',
    )


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
        await _open_vps_card(query, vps_id)
        return True

    if data.startswith('vps_extend_'):
        _, _, raw_id, duration_code = data.split('_')
        vps_id = int(raw_id)
        item = _find_vps(vps_id)
        if not item:
            await query.answer('VPS не найден', show_alert=True)
            await show_vps_menu(update, context)
            return True

        old_expiry, new_expiry, label = calculate_vps_extension(item['expiry_date'], duration_code)
        update_vps_expiry(vps_id, new_expiry)
        new_days_left = (date.fromisoformat(new_expiry) - date.today()).days
        await query.answer('Дата продлена')
        await query.edit_message_text(
            (
                f'✅ <b>{escape_html(item["name"])}</b> продлён\n\n'
                f'Было: <code>{old_expiry}</code>\n'
                f'Стало: <code>{new_expiry}</code>\n'
                f'Действие: <b>{label}</b>\n'
                f'Теперь осталось: <b>{days_left_text(new_days_left)}</b>\n\n'
                'Если дата в личном кабинете отличается, нажмите <b>Точная дата</b> и укажите её вручную.'
            ),
            reply_markup=vps_actions_keyboard(vps_id),
            parse_mode='HTML',
        )
        return True

    if data.startswith('vps_exact_'):
        await query.answer()
        vps_id = int(data.split('_')[2])
        item = _find_vps(vps_id)
        if not item:
            await query.edit_message_text('❌ VPS не найден.', reply_markup=vps_menu_keyboard(get_vps_list()))
            return True

        current = date.fromisoformat(item['expiry_date'])
        start = current if current >= date.today() else date.today()
        await query.edit_message_text(
            (
                f'📅 <b>{escape_html(item["name"])}</b>\n\n'
                f'Текущая дата: <code>{item["expiry_date"]}</code>\n'
                'Выберите точную дату <b>оплачено до</b> из личного кабинета хостера.'
            ),
            reply_markup=calendar_keyboard(
                start.year,
                start.month,
                mode='edit',
                vps_id=vps_id,
                cancel_callback=f'vps_open_{vps_id}',
            ),
            parse_mode='HTML',
        )
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

    if data.startswith('vps_cal_new_'):
        await query.answer()
        _, _, _, direction, year, month = data.split('_')
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
        await query.edit_message_reply_markup(reply_markup=calendar_keyboard(year_i, month_i, mode='new'))
        return True

    if data.startswith('vps_cal_edit_'):
        await query.answer()
        _, _, _, raw_id, direction, year, month = data.split('_')
        vps_id = int(raw_id)
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
        await query.edit_message_reply_markup(
            reply_markup=calendar_keyboard(year_i, month_i, mode='edit', vps_id=vps_id, cancel_callback=f'vps_open_{vps_id}')
        )
        return True

    if data.startswith('vps_pick_new_'):
        await query.answer('Дата выбрана')
        _, _, _, year, month, day = data.split('_')
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

    if data.startswith('vps_pick_edit_'):
        await query.answer('Дата обновлена')
        _, _, _, raw_id, year, month, day = data.split('_')
        vps_id = int(raw_id)
        item = _find_vps(vps_id)
        if not item:
            await query.edit_message_text('❌ VPS не найден.', reply_markup=vps_menu_keyboard(get_vps_list()))
            return True
        old_expiry = item['expiry_date']
        new_expiry = date(int(year), int(month), int(day)).isoformat()
        update_vps_expiry(vps_id, new_expiry)
        new_days_left = (date.fromisoformat(new_expiry) - date.today()).days
        await query.edit_message_text(
            (
                f'✅ <b>{escape_html(item["name"])}</b> обновлён\n\n'
                f'Было: <code>{old_expiry}</code>\n'
                f'Стало: <code>{new_expiry}</code>\n'
                f'Теперь осталось: <b>{days_left_text(new_days_left)}</b>'
            ),
            reply_markup=vps_actions_keyboard(vps_id),
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
        reply_markup=calendar_keyboard(today.year, today.month, mode='new'),
    )
    return True
