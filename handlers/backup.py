#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import math
import os
from pathlib import Path
from typing import Dict

import config
from telegram import Update
from telegram.ext import ContextTypes

from backup_manager import BackupManager, UniversalScanner, create_selected_backup
from core.db import (
    get_all_settings,
    get_saved_backup_selection,
    save_backup_result,
    set_saved_backup_selection,
)
from core.formatting import escape_html
from ui.keyboards import backup_keyboard, confirm_keyboard, smart_backup_keyboard

PAGE_SIZE = 8


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _backup_instructions_text() -> str:
    return (
        '📖 <b>Как восстановиться из бэкапа</b>\n\n'
        '1. Установите бот на новый сервер или подготовьте пустую папку проекта.\n'
        '2. Скопируйте архив бэкапа и распакуйте его.\n'
        '3. Верните в проект файлы <code>vps_data.db</code>, '
        '<code>oauth-credentials.json</code>, <code>token.pickle</code>, '
        '<code>.env</code> и нужные каталоги сервисов.\n'
        '4. Проверьте права доступа к секретам: '
        '<code>chmod 600 .env oauth-credentials.json token.pickle</code>.\n'
        '5. Перезапустите сервис: <code>sudo systemctl restart server-bot</code>.\n\n'
        'Для умного бэкапа откройте <code>manifest.json</code> и '
        '<code>RESTORE.txt</code> внутри архива.'
    )


def _gdrive_settings_text(settings: Dict[str, str]) -> str:
    root = _project_root()
    folder_id = settings.get('google_drive_folder_id', '').strip()
    creds_exists = (root / 'oauth-credentials.json').exists()
    token_exists = (root / 'token.pickle').exists()
    db_exists = (root / 'vps_data.db').exists()

    lines = [
        '☁️ <b>Настройки Google Drive</b>',
        '',
        f'📁 ID папки: {"✅ задан" if folder_id else "❌ не задан"}',
        f'🔑 oauth-credentials.json: {"✅ найден" if creds_exists else "❌ не найден"}',
        f'🎟 token.pickle: {"✅ найден" if token_exists else "❌ не найден"}',
        f'🗄 vps_data.db: {"✅ найден" if db_exists else "❌ не найден"}',
        '',
        '<b>Как настроить загрузку бэкапов в Google Drive</b>',
        '1. В Google Cloud создайте проект и включите Google Drive API.',
        '2. Создайте OAuth client type: <b>Desktop App</b>.',
        '3. Скачайте JSON и положите его в папку проекта как <code>oauth-credentials.json</code>.',
        '4. На сервере выполните <code>python3 auth_manual.py</code> и пройдите авторизацию.',
        '5. После успешной авторизации появится файл <code>token.pickle</code>.',
        '6. Создайте папку на Google Drive для бэкапов и откройте её в браузере.',
        '7. ID папки — это часть ссылки после <code>/folders/</code>.',
        '8. Нажмите кнопку ниже и вставьте ID папки в бота.',
        '',
        'Когда все три пункта готовы — бот сможет автоматически выгружать архивы в Google Drive.',
    ]
    return '\n'.join(lines)


async def show_backup_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query:
        await query.answer()
    settings = get_all_settings()
    text = (
        '📦 <b>Бэкапы</b>\n\n'
        '• Базовый бэкап — база бота и конфиги проекта\n'
        '• Умный бэкап — выбор сервисов и данных для переезда на новый VPS\n'
        '• Google Drive — загрузка готового архива в облако'
    )
    if query:
        await query.edit_message_text(
            text,
            reply_markup=backup_keyboard(settings),
            parse_mode='HTML',
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=backup_keyboard(settings),
            parse_mode='HTML',
        )


async def show_gdrive_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    settings = get_all_settings()
    await query.edit_message_text(
        _gdrive_settings_text(settings),
        reply_markup=backup_keyboard(settings),
        parse_mode='HTML',
    )


async def _upload_if_configured(
    context: ContextTypes.DEFAULT_TYPE,
    manager: BackupManager,
    archive_path: str,
) -> str:
    settings = get_all_settings()
    folder_id = settings.get('google_drive_folder_id', '').strip()
    if not folder_id:
        return 'Google Drive не настроен, архив сохранён локально.'
    ok, message = await manager.upload_to_google_drive(archive_path, folder_id)
    return f'Google Drive: {message}' if ok else f'Google Drive: {message}'


async def create_basic_backup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    manager = BackupManager(config.DB_PATH)

    async def progress(text: str) -> None:
        await query.edit_message_text(f'⏳ {escape_html(text)}', parse_mode='HTML')

    archive_path = await manager.create_backup(include_configs=True, progress_cb=progress)
    if not archive_path:
        await query.edit_message_text(
            '❌ Не удалось создать бэкап.',
            reply_markup=backup_keyboard(get_all_settings()),
        )
        return

    size_mb = os.path.getsize(archive_path) / 1024 / 1024
    save_backup_result(size_mb)
    manager.cleanup_old_backups(int(get_all_settings().get('backup_keep_count', '10')))
    upload_result = await _upload_if_configured(context, manager, archive_path)
    await query.edit_message_text(
        '✅ <b>Бэкап создан</b>\n\n'
        f'Файл: <code>{escape_html(archive_path)}</code>\n'
        f'Размер: {size_mb:.1f} MB\n'
        f'{escape_html(upload_result)}',
        reply_markup=backup_keyboard(get_all_settings()),
        parse_mode='HTML',
    )




async def confirm_basic_backup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        '📦 <b>Создать базовый бэкап?</b>\n\n'
        'Будут сохранены база бота, конфиги проекта и файлы, нужные для восстановления.',
        reply_markup=confirm_keyboard('backup_create_confirm', 'backup_menu'),
        parse_mode='HTML',
    )


async def confirm_selected_backup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    scanner: UniversalScanner = context.application.bot_data.get('smart_backup_scanner')
    if not scanner or not scanner.get_selected():
        await query.edit_message_text(
            '❌ Сначала выберите хотя бы один компонент для умного бэкапа.',
            reply_markup=backup_keyboard(get_all_settings()),
        )
        return
    await query.edit_message_text(
        '🎯 <b>Создать умный бэкап?</b>\n\n'
        f'Выбрано элементов: <b>{len(scanner.get_selected())}</b>\n'
        f'Оценка размера: <b>{escape_html(scanner.get_total_size())}</b>',
        reply_markup=confirm_keyboard('backup_create_selected_confirm', 'backup_menu'),
        parse_mode='HTML',
    )

async def open_smart_backup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    scanner = UniversalScanner()

    async def progress(text: str) -> None:
        await query.edit_message_text(f'⏳ {escape_html(text)}', parse_mode='HTML')

    await scanner.scan_all(progress_cb=progress)
    saved_selection = get_saved_backup_selection()
    if saved_selection:
        scanner.set_selected(saved_selection)
    context.application.bot_data['smart_backup_scanner'] = scanner
    await render_smart_backup_page(update, context, page=0)


async def render_smart_backup_page(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    page: int,
) -> None:
    query = update.callback_query
    scanner: UniversalScanner = context.application.bot_data.get('smart_backup_scanner')
    if not scanner:
        await query.edit_message_text(
            '❌ Сначала запустите умный бэкап заново.',
            reply_markup=backup_keyboard(get_all_settings()),
        )
        return
    services = scanner.get_services_list()
    total_pages = max(1, math.ceil(len(services) / PAGE_SIZE))
    page = max(0, min(page, total_pages - 1))
    start = page * PAGE_SIZE
    chunk = services[start:start + PAGE_SIZE]
    items = [
        {
            'id': sid,
            'name': name,
            'description': description,
            'size_text': size_text,
        }
        for sid, name, description, size_text, selected in chunk
    ]
    selected = [sid for sid, _, _, _, is_selected in services if is_selected]
    text_lines = [
        '🎯 <b>Умный бэкап</b>',
        '',
        f'Найдено компонентов: <b>{len(services)}</b>',
        f'Выбрано: <b>{len(selected)}</b>',
        f'Примерный размер: <b>{escape_html(scanner.get_total_size())}</b>',
    ]
    if scanner.skipped_paths:
        text_lines.extend(['', f'Пропущено путей без доступа: {len(scanner.skipped_paths)}'])
    if scanner.scan_errors:
        text_lines.extend(['', f'Шагов с ошибками: {len(scanner.scan_errors)}'])
    await query.edit_message_text(
        '\n'.join(text_lines),
        reply_markup=smart_backup_keyboard(items, selected, page, total_pages),
        parse_mode='HTML',
    )


async def handle_backup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> bool:
    query = update.callback_query
    if data == 'backup_menu':
        await show_backup_menu(update, context)
        return True
    if data == 'backup_create':
        await confirm_basic_backup(update, context)
        return True
    if data == 'backup_create_confirm':
        await create_basic_backup(update, context)
        return True
    if data == 'backup_smart':
        await open_smart_backup(update, context)
        return True
    if data == 'backup_gdrive_settings':
        await show_gdrive_settings(update, context)
        return True
    if data.startswith('backup_page_'):
        await query.answer()
        page = int(data.split('_')[2])
        await render_smart_backup_page(update, context, page)
        return True
    if data.startswith('backup_toggle_'):
        await query.answer()
        _, _, sid, page = data.split('_')
        scanner: UniversalScanner = context.application.bot_data.get('smart_backup_scanner')
        if scanner:
            scanner.toggle_selection(sid)
        await render_smart_backup_page(update, context, int(page))
        return True
    if data == 'backup_select_all':
        await query.answer('Выбраны все найденные элементы')
        scanner: UniversalScanner = context.application.bot_data.get('smart_backup_scanner')
        if scanner:
            scanner.select_all()
        await render_smart_backup_page(update, context, 0)
        return True
    if data == 'backup_clear_selection':
        await query.answer('Выбор очищен')
        scanner: UniversalScanner = context.application.bot_data.get('smart_backup_scanner')
        if scanner:
            scanner.clear_selection()
        await render_smart_backup_page(update, context, 0)
        return True
    if data == 'backup_save_selection':
        await query.answer('Выбор сохранён')
        scanner: UniversalScanner = context.application.bot_data.get('smart_backup_scanner')
        if scanner:
            set_saved_backup_selection(list(scanner.get_selected().keys()))
        await render_smart_backup_page(update, context, 0)
        return True
    if data == 'backup_create_selected':
        await confirm_selected_backup(update, context)
        return True
    if data == 'backup_create_selected_confirm':
        await query.answer()
        scanner: UniversalScanner = context.application.bot_data.get('smart_backup_scanner')
        if not scanner:
            await query.edit_message_text(
                '❌ Сканер недоступен.',
                reply_markup=backup_keyboard(get_all_settings()),
            )
            return True

        async def progress(text: str) -> None:
            await query.edit_message_text(f'⏳ {escape_html(text)}', parse_mode='HTML')

        archive_path = await create_selected_backup(scanner.get_selected(), progress_cb=progress)
        if not archive_path:
            await query.edit_message_text(
                '❌ Не удалось создать умный бэкап.',
                reply_markup=backup_keyboard(get_all_settings()),
            )
            return True

        manager = BackupManager(config.DB_PATH)
        size_mb = os.path.getsize(archive_path) / 1024 / 1024
        save_backup_result(size_mb)
        upload_result = await _upload_if_configured(context, manager, archive_path)
        await query.edit_message_text(
            '✅ <b>Умный бэкап создан</b>\n\n'
            f'Файл: <code>{escape_html(archive_path)}</code>\n'
            f'Размер: {size_mb:.1f} MB\n'
            f'{escape_html(upload_result)}',
            reply_markup=backup_keyboard(get_all_settings()),
            parse_mode='HTML',
        )
        return True
    if data == 'backup_set_interval':
        await query.answer()
        context.user_data['awaiting'] = 'backup_interval'
        await query.edit_message_text(
            'Введите интервал автоматического бэкапа в часах. Например: 24'
        )
        return True
    if data == 'backup_set_keep':
        await query.answer()
        context.user_data['awaiting'] = 'backup_keep_count'
        await query.edit_message_text(
            'Введите, сколько последних архивов хранить. Например: 10'
        )
        return True
    if data == 'backup_set_gdrive':
        await query.answer()
        context.user_data['awaiting'] = 'google_drive_folder_id'
        await query.edit_message_text(
            'Отправьте ID папки Google Drive. Он находится в ссылке после /folders/'
        )
        return True
    if data == 'backup_instructions':
        await query.answer()
        await query.edit_message_text(
            _backup_instructions_text(),
            reply_markup=backup_keyboard(get_all_settings()),
            parse_mode='HTML',
        )
        return True
    return False


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    awaiting = context.user_data.get('awaiting')
    if awaiting not in {'backup_interval', 'backup_keep_count'}:
        return False

    text = (update.message.text or '').strip()
    context.user_data.pop('awaiting', None)
    if not text.isdigit() or int(text) <= 0:
        await update.message.reply_text('❌ Нужны положительные целые числа.')
        return True

    if awaiting == 'backup_interval':
        from core.db import set_setting

        set_setting('backup_interval', text)
        await update.message.reply_text('✅ Интервал бэкапа сохранён.')
        return True

    if awaiting == 'backup_keep_count':
        from core.db import set_setting

        set_setting('backup_keep_count', text)
        await update.message.reply_text('✅ Количество хранимых архивов сохранено.')
        return True

    return False
