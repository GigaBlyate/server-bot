#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
from typing import Optional

from telegram import Message, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from core.auth import is_admin
from services.reports import build_dashboard_text
from services.system_info import get_server_info
from services.prosody_service import is_prosody_installed
from ui.keyboards import menu_keyboard

DASHBOARD_REFRESH_INTERVAL = 15
DASHBOARD_REFRESH_LIFETIME = 120


async def render_dashboard(
    context: ContextTypes.DEFAULT_TYPE,
    first_name: str,
    target_message: Optional[Message] = None,
    edit: bool = False,
) -> Optional[Message]:
    snapshot = await get_server_info(context.application.bot_data)
    text = await build_dashboard_text(first_name, context.application.bot_data, snapshot)
    show_prosody = is_prosody_installed()
    if target_message and edit:
        try:
            await target_message.edit_text(
                text,
                reply_markup=menu_keyboard(show_prosody=show_prosody),
                parse_mode='HTML',
            )
        except BadRequest as exc:
            if 'message is not modified' not in str(exc).lower():
                raise
        return target_message
    if target_message:
        return await target_message.reply_text(
            text,
            reply_markup=menu_keyboard(show_prosody=show_prosody),
            parse_mode='HTML',
        )
    return None


async def send_dashboard_to_chat(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    first_name: str,
) -> Optional[Message]:
    snapshot = await get_server_info(context.application.bot_data)
    text = await build_dashboard_text(first_name, context.application.bot_data, snapshot)
    show_prosody = is_prosody_installed()
    return await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=menu_keyboard(show_prosody=show_prosody),
        parse_mode='HTML',
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        return
    message = await update.message.reply_text('⏳ Готовлю главное меню...')
    first_name = update.effective_user.first_name if update.effective_user else 'Администратор'
    await render_dashboard(context, first_name, message, edit=True)
    schedule_dashboard_refresh(context, message.chat_id, message.message_id, first_name)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start_command(update, context)


async def show_dashboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    first_name = query.from_user.first_name if query.from_user else 'Администратор'
    await render_dashboard(context, first_name, query.message, edit=True)
    schedule_dashboard_refresh(
        context,
        query.message.chat_id,
        query.message.message_id,
        first_name,
    )


def cancel_dashboard_refresh(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    if context.job_queue is None:
        return
    job_name = f'dashboard-refresh-{chat_id}'
    for job in context.job_queue.get_jobs_by_name(job_name):
        job.schedule_removal()


async def dashboard_refresh_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data
    if time.time() > data['expires_at']:
        context.job.schedule_removal()
        return
    snapshot = await get_server_info(context.application.bot_data)
    text = await build_dashboard_text(data['first_name'], context.application.bot_data, snapshot)
    show_prosody = is_prosody_installed()
    try:
        await context.bot.edit_message_text(
            chat_id=data['chat_id'],
            message_id=data['message_id'],
            text=text,
            reply_markup=menu_keyboard(show_prosody=show_prosody),
            parse_mode='HTML',
        )
    except BadRequest as exc:
        if 'message is not modified' not in str(exc).lower():
            context.job.schedule_removal()
    except Exception:
        context.job.schedule_removal()


def schedule_dashboard_refresh(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    first_name: str,
) -> None:
    if context.job_queue is None:
        return
    job_name = f'dashboard-refresh-{chat_id}'
    for job in context.job_queue.get_jobs_by_name(job_name):
        job.schedule_removal()
    context.job_queue.run_repeating(
        dashboard_refresh_job,
        interval=DASHBOARD_REFRESH_INTERVAL,
        first=DASHBOARD_REFRESH_INTERVAL,
        data={
            'chat_id': chat_id,
            'message_id': message_id,
            'first_name': first_name,
            'expires_at': time.time() + DASHBOARD_REFRESH_LIFETIME,
        },
        name=job_name,
    )
