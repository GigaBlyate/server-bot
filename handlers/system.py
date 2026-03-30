#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from pathlib import Path
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

import config
from core.formatting import escape_html
from security import safe_run_command
from services.system_info import set_system_update_cache
from services.updater import (
    get_bot_update_status,
    get_current_version,
    get_upgradable_packages,
    install_system_updates,
    update_bot_code,
)
from ui.keyboards import back_button, confirm_keyboard

REBOOT_MARKER = Path(config.PROJECT_DIR) / '.pending_reboot.json'


def _root_helper(action: str):
    return ['sudo', config.ROOT_HELPER, action]


def _write_reboot_marker(admin_id: str, first_name: str) -> None:
    payload = {'admin_id': admin_id, 'first_name': first_name}
    REBOOT_MARKER.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')


def read_reboot_marker() -> Optional[dict]:
    if not REBOOT_MARKER.exists():
        return None
    try:
        return json.loads(REBOOT_MARKER.read_text(encoding='utf-8'))
    except Exception:
        return None


def clear_reboot_marker() -> None:
    REBOOT_MARKER.unlink(missing_ok=True)


async def update_system_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = await update.message.reply_text('⏳ Проверяю системные обновления...')
    count, packages = await get_upgradable_packages(limit=10)
    await set_system_update_cache(context.application.bot_data, count, packages)
    if count == 0:
        await message.edit_text(
            '✅ Система уже актуальна.',
            reply_markup=back_button('menu'),
            parse_mode='HTML',
        )
        return
    lines = ['📦 <b>Найдены обновления системы</b>', f'Количество: <b>{count}</b>', '']
    for package in packages:
        lines.append(f'• <code>{escape_html(package)}</code>')
    lines.extend(['', 'Обновляем сейчас?'])
    await message.edit_text(
        '\n'.join(lines),
        reply_markup=confirm_keyboard('system_update_confirm', 'settings_menu'),
        parse_mode='HTML',
    )


async def _show_system_update_check(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    await query.answer()
    await query.edit_message_text('⏳ Проверяю системные обновления...', parse_mode='HTML')
    count, packages = await get_upgradable_packages(limit=10)
    await set_system_update_cache(context.application.bot_data, count, packages)
    if count == 0:
        await query.edit_message_text(
            '✅ Система уже актуальна.',
            reply_markup=back_button('settings_menu'),
            parse_mode='HTML',
        )
        return
    lines = ['📦 <b>Найдены обновления системы</b>', f'Количество: <b>{count}</b>', '']
    for package in packages:
        lines.append(f'• <code>{escape_html(package)}</code>')
    lines.extend(['', 'Установить обновления и затем очистить ненужные пакеты?'])
    await query.edit_message_text(
        '\n'.join(lines),
        reply_markup=confirm_keyboard('system_update_confirm', 'settings_menu'),
        parse_mode='HTML',
    )


async def _perform_system_update(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    await query.answer()
    await query.edit_message_text('⏳ Запускаю обновление системы...', parse_mode='HTML')

    def progress(text: str) -> None:
        context.application.create_task(
            query.message.edit_text(f'⏳ {escape_html(text)}', parse_mode='HTML')
        )

    ok, details = await install_system_updates(progress)
    if ok:
        await query.message.edit_text(
            '✅ <b>Система обновлена</b>\n\n'
            f'<code>{escape_html(details[-3000:])}</code>',
            reply_markup=back_button('settings_menu'),
            parse_mode='HTML',
        )
    else:
        await query.message.edit_text(
            '❌ <b>Ошибка обновления системы</b>\n\n'
            f'<code>{escape_html(details[-3000:])}</code>',
            reply_markup=back_button('settings_menu'),
            parse_mode='HTML',
        )


async def _show_bot_update_check(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    await query.answer()
    await query.edit_message_text('⏳ Проверяю обновления бота...', parse_mode='HTML')
    count, commits, raw = await get_bot_update_status(limit=8)
    if count <= 0:
        await query.edit_message_text(
            f'✅ Для бота обновлений нет.\n\nТекущая версия: <b>{escape_html(get_current_version())}</b>',
            reply_markup=back_button('settings_menu'),
            parse_mode='HTML',
        )
        return
    lines = [
        '🤖 <b>Найдены обновления бота</b>',
        f'Текущая версия: <b>{escape_html(get_current_version())}</b>',
        f'Коммитов впереди: <b>{count}</b>',
        '',
    ]
    for commit in commits:
        lines.append(f'• <code>{escape_html(commit)}</code>')
    if not commits:
        lines.append(f'• origin/main ahead на {escape_html(raw)} коммит(ов)')
    lines.extend(['', 'Обновить бота сейчас?'])
    await query.edit_message_text(
        '\n'.join(lines),
        reply_markup=confirm_keyboard('bot_update_confirm', 'settings_menu'),
        parse_mode='HTML',
    )


async def _perform_bot_update(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    await query.answer()
    await query.edit_message_text('⏳ Запускаю обновление бота...', parse_mode='HTML')

    def progress(text: str) -> None:
        context.application.create_task(
            query.message.edit_text(f'⏳ {escape_html(text)}', parse_mode='HTML')
        )

    ok, details = await update_bot_code(progress)
    if ok:
        code, out, err = await safe_run_command(_root_helper('restart-bot'), timeout=60)
        if code == 0:
            await query.message.edit_text(
                '✅ Бот обновлён и сервис перезапущен.\n\n'
                f'<code>{escape_html(details[-3000:])}</code>',
                reply_markup=back_button('settings_menu'),
                parse_mode='HTML',
            )
        else:
            await query.message.edit_text(
                '⚠️ Код обновлён, но сервис не удалось перезапустить автоматически.\n\n'
                f'<code>{escape_html((err or out or details)[-3000:])}</code>',
                reply_markup=back_button('settings_menu'),
                parse_mode='HTML',
            )
    else:
        await query.message.edit_text(
            '❌ Ошибка обновления бота.\n\n'
            f'<code>{escape_html(details[-3000:])}</code>',
            reply_markup=back_button('settings_menu'),
            parse_mode='HTML',
        )


async def handle_system_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> bool:
    query = update.callback_query
    if data == 'reboot_confirm':
        await query.answer()
        await query.edit_message_text(
            '🔁 <b>Перезагрузка сервера</b>\n\n'
            'После перезагрузки бот пришлёт уведомление и откроет главное меню автоматически.',
            reply_markup=confirm_keyboard('reboot_yes', 'menu'),
            parse_mode='HTML',
        )
        return True
    if data == 'reboot_yes':
        await query.answer('Команда отправлена')
        first_name = query.from_user.first_name if query.from_user else 'Администратор'
        _write_reboot_marker(str(query.message.chat_id), first_name)
        await query.edit_message_text(
            '🔁 Команда перезагрузки отправлена. После запуска сервера я пришлю уведомление.',
            parse_mode='HTML',
        )
        code, out, err = await safe_run_command(_root_helper('reboot-host'), timeout=5)
        if code != 0:
            clear_reboot_marker()
            await query.message.edit_text(
                '❌ Не удалось отправить команду перезагрузки.\n\n'
                f'<code>{escape_html((err or out or "Неизвестная ошибка")[-3000:])}</code>',
                reply_markup=back_button('menu'),
                parse_mode='HTML',
            )
        return True
    if data == 'system_update_check':
        await _show_system_update_check(query, context)
        return True
    if data == 'system_update_confirm':
        await _perform_system_update(query, context)
        return True
    if data == 'bot_update_check':
        await _show_bot_update_check(query, context)
        return True
    if data == 'bot_update_confirm':
        await _perform_bot_update(query, context)
        return True
    return False


async def reboot_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = await update.message.reply_text(
        '🔁 Подтвердите перезагрузку кнопкой в главном меню.',
        reply_markup=back_button('menu'),
        parse_mode='HTML',
    )
    return message
