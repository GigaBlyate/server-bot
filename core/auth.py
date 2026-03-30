#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
from typing import Optional

from telegram import Update

import config

logger = logging.getLogger(__name__)


def get_admin_id() -> str:
    return str(config.ADMIN_CHAT_ID).strip()


def get_effective_user_id(update: Update) -> str:
    user = getattr(update, 'effective_user', None)
    return str(getattr(user, 'id', '') or '').strip()


def get_effective_chat_id(update: Update) -> str:
    chat = getattr(update, 'effective_chat', None)
    return str(getattr(chat, 'id', '') or '').strip()


def is_private_chat(update: Update) -> bool:
    chat = getattr(update, 'effective_chat', None)
    return getattr(chat, 'type', '') == 'private'


def is_admin(update: Update) -> bool:
    admin_id = get_admin_id()
    if not admin_id or admin_id == 'YOUR_ADMIN_ID_HERE':
        return False
    return get_effective_user_id(update) == admin_id


def is_admin_private(update: Update) -> bool:
    admin_id = get_admin_id()
    if not admin_id or admin_id == 'YOUR_ADMIN_ID_HERE':
        return False
    return is_private_chat(update) and get_effective_user_id(update) == admin_id and get_effective_chat_id(update) == admin_id


async def ensure_admin_access(update: Update) -> bool:
    if is_admin_private(update):
        return True

    is_owner = is_admin(update)
    reason = (
        '🔒 Управление ботом разрешено только в личном чате с владельцем.'
        if is_owner else
        '⛔ Доступ разрешён только владельцу бота.'
    )

    query = getattr(update, 'callback_query', None)
    message = getattr(update, 'message', None)

    if query is not None:
        try:
            await query.answer(reason, show_alert=True)
        except Exception:
            logger.debug('Cannot answer callback access denial', exc_info=True)
    elif message is not None:
        try:
            await message.reply_text(reason)
        except Exception:
            logger.debug('Cannot send access denial message', exc_info=True)

    logger.warning(
        'Blocked bot access: user_id=%s chat_id=%s private=%s',
        get_effective_user_id(update),
        get_effective_chat_id(update),
        is_private_chat(update),
    )
    return False
