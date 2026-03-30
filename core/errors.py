#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import html
import logging

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error_text = str(context.error)
    if 'message is not modified' in error_text.lower():
        logger.info('Skipped benign Telegram error: %s', error_text)
        return

    logger.exception('Unhandled exception', exc_info=context.error)
    tg_update = update if isinstance(update, Update) else None
    if tg_update and tg_update.effective_chat:
        try:
            await context.bot.send_message(
                chat_id=tg_update.effective_chat.id,
                text=(
                    '❌ Произошла ошибка при обработке действия.\n\n'
                    f'<code>{html.escape(error_text)}</code>'
                ),
                parse_mode='HTML',
            )
        except Exception:
            logger.exception('Failed to send error notification')
