#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from datetime import date, timedelta
from typing import Dict, List

from dateutil.relativedelta import relativedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core.db import get_due_vps, get_notifiable_vps, mark_vps_notified
from core.formatting import days_left_text, escape_html


EXTEND_LABELS = {
    '30d': ('Продлить на 30 дней', timedelta(days=30)),
    '3m': ('Продлить на 3 месяца', relativedelta(months=3)),
    '6m': ('Продлить на 6 месяцев', relativedelta(months=6)),
    '12m': ('Продлить на 12 месяцев', relativedelta(months=12)),
}


def build_vps_summary(days_limit: int = 30) -> List[str]:
    rows = get_due_vps(days_limit)
    lines = []
    for item in rows[:5]:
        prefix = '🚨' if item['days_left'] <= 5 else '⚠️'
        lines.append(
            f'{prefix} {escape_html(item["name"])} — {days_left_text(item["days_left"])} '
            f'({item["expiry_date"]})'
        )
    return lines


async def send_vps_expiry_notifications(context: ContextTypes.DEFAULT_TYPE) -> None:
    for item in get_notifiable_vps():
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        '30 дней',
                        callback_data=f'vps_extend_{item["id"]}_30d',
                    ),
                    InlineKeyboardButton(
                        '3 месяца',
                        callback_data=f'vps_extend_{item["id"]}_3m',
                    ),
                ],
                [InlineKeyboardButton('Открыть VPS', callback_data='vps_menu')],
            ]
        )
        urgency = '🚨' if item['days_left'] <= 5 else '🔔'
        await context.bot.send_message(
            chat_id=context.application.bot_data['admin_id'],
            text=(
                f'{urgency} <b>Напоминание об аренде VPS</b>\n\n'
                f'Сервер: <b>{escape_html(item["name"])}</b>\n'
                f'До окончания: <b>{days_left_text(item["days_left"])}</b>\n'
                f'Дата окончания: <code>{item["expiry_date"]}</code>\n\n'
                'Продлите сервер заранее, чтобы избежать отключения.'
            ),
            parse_mode='HTML',
            reply_markup=kb,
        )
        mark_vps_notified(int(item['id']))


def extend_vps_date(expiry_date: str, duration_code: str) -> str:
    base = date.fromisoformat(expiry_date)
    if base < date.today():
        base = date.today()
    _, delta = EXTEND_LABELS.get(duration_code, EXTEND_LABELS['30d'])
    if isinstance(delta, timedelta):
        target = base + delta
    else:
        target = base + delta
    return target.isoformat()
