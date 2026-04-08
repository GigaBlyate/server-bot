#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from telegram import Update
from telegram.ext import ContextTypes

from core.formatting import escape_html
from services.prosody_service import (
    add_user,
    delete_user,
    get_domains,
    list_users,
    restart_prosody,
    set_password,
    update_prosody,
    validate_domain,
    validate_jid,
)
from ui.keyboards import (
    back_main_keyboard,
    prosody_domains_keyboard,
    prosody_menu_keyboard,
    prosody_user_actions_keyboard,
    prosody_users_keyboard,
)

PAGE_SIZE = 10


def _prosody_main_text() -> str:
    return (
        '💬 <b>Управление Prosody</b>\n\n'
        'Здесь можно обновить и перезапустить Prosody, добавить клиента, '
        'удалить клиента, сбросить пароль и посмотреть список клиентов по домену.'
    )


async def show_prosody_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(
            _prosody_main_text(),
            reply_markup=prosody_menu_keyboard(),
            parse_mode='HTML',
        )
        return
    await update.message.reply_text(
        _prosody_main_text(),
        reply_markup=prosody_menu_keyboard(),
        parse_mode='HTML',
    )


async def _show_domains(query, purpose: str = 'list') -> None:
    ok, domains, details = await get_domains()
    if not ok:
        await query.edit_message_text(
            '❌ <b>Не удалось получить домены Prosody</b>\n\n'
            f'<code>{escape_html(details[-3000:])}</code>',
            reply_markup=back_main_keyboard('prosody_menu', 'menu'),
            parse_mode='HTML',
        )
        return
    if not domains:
        await query.edit_message_text(
            '⚠️ Домены Prosody не найдены в конфигурации.\n\n'
            'Проверьте /etc/prosody/prosody.cfg.lua и /etc/prosody/conf.d/*.cfg.lua.',
            reply_markup=back_main_keyboard('prosody_menu', 'menu'),
            parse_mode='HTML',
        )
        return

    title_map = {
        'list': 'Выберите домен для просмотра клиентов:',
        'password': 'Выберите домен для сброса пароля клиента:',
        'delete': 'Выберите домен для удаления клиента:',
    }
    await query.edit_message_text(
        f'💬 <b>Prosody</b>\n\n{escape_html(title_map.get(purpose, "Выберите домен:"))}',
        reply_markup=prosody_domains_keyboard(domains, purpose=purpose),
        parse_mode='HTML',
    )


async def _show_users(query, domain: str, page: int = 0, action: str = 'list') -> None:
    host = (domain or '').strip().lower()
    if not validate_domain(host):
        await query.edit_message_text(
            '❌ Некорректный домен Prosody.',
            reply_markup=back_main_keyboard('prosody_menu', 'menu'),
            parse_mode='HTML',
        )
        return

    ok, users, details = await list_users(host)
    if not ok:
        await query.edit_message_text(
            f'❌ <b>Не удалось получить клиентов для {escape_html(host)}</b>\n\n'
            f'<code>{escape_html(details[-3000:])}</code>',
            reply_markup=back_main_keyboard('prosody_menu', 'menu'),
            parse_mode='HTML',
        )
        return

    total = len(users)
    page = max(page, 0)
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    page_users = users[start:end]

    mode_title = {
        'list': 'Клиенты Prosody',
        'password': 'Сброс пароля клиента',
        'delete': 'Удаление клиента',
    }.get(action, 'Клиенты Prosody')
    help_text = {
        'list': 'Нажмите на клиента, чтобы открыть действия.',
        'password': 'Нажмите на клиента, чтобы задать новый пароль.',
        'delete': 'Нажмите на клиента, чтобы удалить его.',
    }.get(action, 'Нажмите на клиента, чтобы открыть действия.')

    lines = [
        f'👥 <b>{mode_title}</b>',
        f'Домен: <code>{escape_html(host)}</code>',
        '',
    ]
    if total == 0:
        lines.append('Клиенты не найдены.')
    else:
        lines.append(f'Всего клиентов: <b>{total}</b>')
        lines.append(help_text)
        lines.append('')
        for idx, jid in enumerate(page_users, start=start + 1):
            lines.append(f'{idx}. <code>{escape_html(jid)}</code>')

    await query.edit_message_text(
        '\n'.join(lines),
        reply_markup=prosody_users_keyboard(host, users, page, PAGE_SIZE, action=action),
        parse_mode='HTML',
    )


async def _show_user_actions(query, jid: str, back_target: str = 'prosody_list_menu') -> None:
    login = (jid or '').strip().lower()
    if not validate_jid(login):
        await query.edit_message_text(
            '❌ Некорректный JID.',
            reply_markup=back_main_keyboard(back_target, 'menu'),
            parse_mode='HTML',
        )
        return
    await query.edit_message_text(
        '👤 <b>Клиент Prosody</b>\n\n'
        f'JID: <code>{escape_html(login)}</code>\n\n'
        'Выберите действие.',
        reply_markup=prosody_user_actions_keyboard(login, back_target=back_target),
        parse_mode='HTML',
    )


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    awaiting = context.user_data.get('awaiting')
    text = (update.message.text or '').strip()

    if awaiting == 'prosody_add_jid':
        if not validate_jid(text):
            await update.message.reply_text(
                '❌ Некорректный JID. Нужен формат <code>user@domain</code>.',
                reply_markup=back_main_keyboard('prosody_menu', 'menu'),
                parse_mode='HTML',
            )
            return True
        context.user_data['prosody_new_jid'] = text.lower()
        context.user_data['awaiting'] = 'prosody_add_password'
        await update.message.reply_text(
            f'🔑 Введите пароль для <code>{escape_html(text.lower())}</code>.',
            reply_markup=back_main_keyboard('prosody_menu', 'menu'),
            parse_mode='HTML',
        )
        return True

    if awaiting == 'prosody_add_password':
        jid = str(context.user_data.get('prosody_new_jid') or '').strip().lower()
        context.user_data.pop('awaiting', None)
        context.user_data.pop('prosody_new_jid', None)
        ok, details = await add_user(jid, text)
        title = 'Клиент создан' if ok else 'Ошибка создания клиента'
        prefix = '✅' if ok else '❌'
        await update.message.reply_text(
            f'{prefix} <b>{title}</b>\n\n'
            f'<code>{escape_html(details[-3000:])}</code>',
            reply_markup=prosody_menu_keyboard(),
            parse_mode='HTML',
        )
        return True

    if awaiting == 'prosody_delete_jid':
        context.user_data.pop('awaiting', None)
        if not validate_jid(text):
            await update.message.reply_text(
                '❌ Некорректный JID. Нужен формат <code>user@domain</code>.',
                reply_markup=prosody_menu_keyboard(),
                parse_mode='HTML',
            )
            return True
        ok, details = await delete_user(text.lower())
        title = 'Клиент удалён' if ok else 'Ошибка удаления клиента'
        prefix = '✅' if ok else '❌'
        await update.message.reply_text(
            f'{prefix} <b>{title}</b>\n\n'
            f'<code>{escape_html(details[-3000:])}</code>',
            reply_markup=prosody_menu_keyboard(),
            parse_mode='HTML',
        )
        return True

    if awaiting == 'prosody_password_jid':
        if not validate_jid(text):
            await update.message.reply_text(
                '❌ Некорректный JID. Нужен формат <code>user@domain</code>.',
                reply_markup=prosody_menu_keyboard(),
                parse_mode='HTML',
            )
            return True
        context.user_data['prosody_password_jid'] = text.lower()
        context.user_data['awaiting'] = 'prosody_password_value'
        await update.message.reply_text(
            f'🔐 Введите новый пароль для <code>{escape_html(text.lower())}</code>.',
            reply_markup=back_main_keyboard('prosody_menu', 'menu'),
            parse_mode='HTML',
        )
        return True

    if awaiting == 'prosody_password_value':
        jid = str(context.user_data.get('prosody_password_jid') or '').strip().lower()
        context.user_data.pop('awaiting', None)
        context.user_data.pop('prosody_password_jid', None)
        ok, details = await set_password(jid, text)
        title = 'Пароль обновлён' if ok else 'Ошибка смены пароля'
        prefix = '✅' if ok else '❌'
        await update.message.reply_text(
            f'{prefix} <b>{title}</b>\n\n'
            f'Клиент: <code>{escape_html(jid)}</code>\n\n'
            f'<code>{escape_html(details[-3000:])}</code>',
            reply_markup=prosody_menu_keyboard(),
            parse_mode='HTML',
        )
        return True

    return False


async def handle_prosody_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> bool:
    query = update.callback_query

    if data == 'prosody_menu':
        await show_prosody_menu(update, context)
        return True

    if data == 'prosody_update_confirm':
        await query.answer()
        await query.edit_message_text(
            '⬆️ <b>Обновить Prosody</b>\n\n'
            'Будет выполнено обновление пакета Prosody через apt. Продолжить?',
            reply_markup=prosody_menu_keyboard(confirm_action='prosody_update_yes'),
            parse_mode='HTML',
        )
        return True

    if data == 'prosody_update_yes':
        await query.answer('Обновляю Prosody...')
        await query.edit_message_text('⏳ Обновляю Prosody...', parse_mode='HTML')
        ok, details = await update_prosody()
        title = 'Prosody обновлён' if ok else 'Ошибка обновления Prosody'
        prefix = '✅' if ok else '❌'
        await query.edit_message_text(
            f'{prefix} <b>{title}</b>\n\n'
            f'<code>{escape_html(details[-3000:])}</code>',
            reply_markup=back_main_keyboard('prosody_menu', 'menu'),
            parse_mode='HTML',
        )
        return True

    if data == 'prosody_restart_confirm':
        await query.answer()
        await query.edit_message_text(
            '🔁 <b>Перезагрузить Prosody</b>\n\n'
            'Будет выполнен systemctl restart prosody. Продолжить?',
            reply_markup=prosody_menu_keyboard(confirm_action='prosody_restart_yes'),
            parse_mode='HTML',
        )
        return True

    if data == 'prosody_restart_yes':
        await query.answer('Перезапускаю Prosody...')
        await query.edit_message_text('⏳ Перезапускаю Prosody...', parse_mode='HTML')
        ok, details = await restart_prosody()
        title = 'Prosody перезапущен' if ok else 'Ошибка перезапуска Prosody'
        prefix = '✅' if ok else '❌'
        await query.edit_message_text(
            f'{prefix} <b>{title}</b>\n\n'
            f'<code>{escape_html(details[-3000:])}</code>',
            reply_markup=back_main_keyboard('prosody_menu', 'menu'),
            parse_mode='HTML',
        )
        return True

    if data == 'prosody_add_prompt':
        context.user_data['awaiting'] = 'prosody_add_jid'
        await query.answer()
        await query.edit_message_text(
            '➕ <b>Добавить клиента Prosody</b>\n\n'
            'Отправьте JID в формате <code>user@domain</code>.',
            reply_markup=back_main_keyboard('prosody_menu', 'menu'),
            parse_mode='HTML',
        )
        return True

    if data == 'prosody_delete_prompt':
        context.user_data['awaiting'] = 'prosody_delete_jid'
        await query.answer()
        await query.edit_message_text(
            '🗑 <b>Удалить клиента Prosody</b>\n\n'
            'Отправьте JID в формате <code>user@domain</code>.\n'
            'Либо откройте список клиентов и удалите пользователя кнопкой.',
            reply_markup=back_main_keyboard('prosody_menu', 'menu'),
            parse_mode='HTML',
        )
        return True

    if data == 'prosody_password_prompt':
        context.user_data['awaiting'] = 'prosody_password_jid'
        context.user_data.pop('prosody_password_jid', None)
        await query.answer()
        await query.edit_message_text(
            '🔐 <b>Сбросить пароль клиента Prosody</b>\n\n'
            'Отправьте JID в формате <code>user@domain</code>.\n'
            'Либо откройте список клиентов и выберите пользователя кнопкой.',
            reply_markup=back_main_keyboard('prosody_menu', 'menu'),
            parse_mode='HTML',
        )
        return True

    if data == 'prosody_list_menu':
        await query.answer()
        await _show_domains(query, purpose='list')
        return True

    if data == 'prosody_password_menu':
        await query.answer()
        await _show_domains(query, purpose='password')
        return True

    if data.startswith('prosody_list_domain:'):
        await query.answer()
        payload = data.split(':', 1)[1]
        parts = payload.split('|')
        host = parts[0]
        page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        await _show_users(query, host, page, action='list')
        return True

    if data.startswith('prosody_password_domain:'):
        await query.answer()
        payload = data.split(':', 1)[1]
        parts = payload.split('|')
        host = parts[0]
        page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        await _show_users(query, host, page, action='password')
        return True

    if data.startswith('prosody_user_actions:'):
        await query.answer()
        jid = data.split(':', 1)[1].strip().lower()
        await _show_user_actions(query, jid)
        return True

    if data.startswith('prosody_password_select:'):
        await query.answer()
        jid = data.split(':', 1)[1].strip().lower()
        if not validate_jid(jid):
            await query.edit_message_text(
                '❌ Некорректный JID.',
                reply_markup=back_main_keyboard('prosody_password_menu', 'menu'),
                parse_mode='HTML',
            )
            return True
        context.user_data['prosody_password_jid'] = jid
        context.user_data['awaiting'] = 'prosody_password_value'
        await query.edit_message_text(
            '🔐 <b>Сбросить пароль клиента Prosody</b>\n\n'
            f'Клиент: <code>{escape_html(jid)}</code>\n\n'
            'Отправьте новый пароль сообщением.',
            reply_markup=back_main_keyboard('prosody_password_menu', 'menu'),
            parse_mode='HTML',
        )
        return True

    if data.startswith('prosody_delete_confirm:'):
        await query.answer()
        jid = data.split(':', 1)[1].strip().lower()
        if not validate_jid(jid):
            await query.edit_message_text(
                '❌ Некорректный JID.',
                reply_markup=back_main_keyboard('prosody_menu', 'menu'),
                parse_mode='HTML',
            )
            return True
        await query.edit_message_text(
            '🗑 <b>Удалить клиента Prosody</b>\n\n'
            f'Клиент: <code>{escape_html(jid)}</code>\n\n'
            'Подтвердите удаление.',
            reply_markup=prosody_menu_keyboard(confirm_action=f'prosody_delete_yes:{jid}', back_target='prosody_list_menu'),
            parse_mode='HTML',
        )
        return True

    if data.startswith('prosody_delete_yes:'):
        await query.answer('Удаляю клиента...')
        jid = data.split(':', 1)[1].strip().lower()
        ok, details = await delete_user(jid)
        title = 'Клиент удалён' if ok else 'Ошибка удаления клиента'
        prefix = '✅' if ok else '❌'
        await query.edit_message_text(
            f'{prefix} <b>{title}</b>\n\n'
            f'Клиент: <code>{escape_html(jid)}</code>\n\n'
            f'<code>{escape_html(details[-3000:])}</code>',
            reply_markup=back_main_keyboard('prosody_menu', 'menu'),
            parse_mode='HTML',
        )
        return True

    return False
