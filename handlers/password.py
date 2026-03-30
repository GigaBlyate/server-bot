#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import secrets
import string

from telegram import Update
from telegram.ext import ContextTypes

from ui.keyboards import back_button, password_keyboard


async def show_password_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        '🔐 <b>Генератор паролей</b>\n\nВыберите длину.',
        reply_markup=password_keyboard(),
        parse_mode='HTML',
    )


async def handle_password_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> bool:
    query = update.callback_query
    if data == 'pass_menu':
        await show_password_menu(update, context)
        return True
    if not data.startswith('password_'):
        return False
    await query.answer()
    length = int(data.split('_')[1])
    alphabet = string.ascii_letters + string.digits + '!@#$%^&*'
    password = ''.join(secrets.choice(alphabet) for _ in range(length))
    text = (
        '🔐 <b>Готовый пароль</b>\n\n'
        f'<code>{password}</code>\n\n'
        'Скопируйте пароль и сохраните его в менеджере паролей.'
    )
    await query.edit_message_text(text, reply_markup=back_button('pass_menu'), parse_mode='HTML')
    return True
