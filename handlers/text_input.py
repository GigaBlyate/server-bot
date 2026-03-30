#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from telegram import Update
from telegram.ext import ContextTypes

from core.auth import ensure_admin_access
from handlers.backup import handle_text_input as handle_backup_input
from handlers.ping import run_custom_ping
from handlers.settings import handle_text_input as handle_settings_input
from handlers.vps import handle_text_input as handle_vps_input


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_admin_access(update):
        return

    awaiting = context.user_data.get('awaiting')
    if awaiting == 'ping_host':
        context.user_data.pop('awaiting', None)
        await run_custom_ping(update, context, (update.message.text or '').strip())
        return
    if await handle_vps_input(update, context):
        return
    if await handle_backup_input(update, context):
        return
    if await handle_settings_input(update, context):
        return
    await update.message.reply_text('Не понял сообщение. Откройте /start и выберите действие кнопкой.')
