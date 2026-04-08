#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from datetime import date, timedelta
from typing import List, Tuple

from dateutil.relativedelta import relativedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core.db import get_due_vps, get_notifiable_vps, mark_vps_notified
from core.formatting import days_left_text, escape_html


EXTEND_LABELS = {
    '30d': '30 дней',
    '1m': '1 месяц',
    '3m': '3 месяца',
    '6m': '6 месяцев',
    '12m': '12 месяцев',
}

EXTEND_DELTAS = {
    '30d': timedelta(days=30),
    '1m': relativedelta(months=1),
    '3m': relativedelta(months=3),
    '6m': relativedelta(months=6),
    '12m': relativedelta(months=12),
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
                        '+30 дней',
                        callback_data=f'vps_extend_{item["id"]}_30d',
                    ),
                    InlineKeyboardButton(
                        '+1 месяц',
                        callback_data=f'vps_extend_{item["id"]}_1m',
                    ),
                ],
                [
                    InlineKeyboardButton(
                        '+3 месяца',
                        callback_data=f'vps_extend_{item["id"]}_3m',
                    ),
                    InlineKeyboardButton(
                        'Точная дата',
                        callback_data=f'vps_exact_{item["id"]}',
                    ),
                ],
                [InlineKeyboardButton('Открыть VPS', callback_data=f'vps_open_{item["id"]}')],
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
                'После оплаты можно быстро продлить срок кнопкой или выбрать точную дату из личного кабинета.'
            ),
            parse_mode='HTML',
            reply_markup=kb,
        )
        mark_vps_notified(int(item['id']))


def _resolve_base_date(expiry_date: str, today: date | None = None) -> date:
    today = today or date.today()
    current = date.fromisoformat(expiry_date)
    return current if current >= today else today


def calculate_vps_extension(expiry_date: str, duration_code: str, today: date | None = None) -> Tuple[str, str, str]:
    today = today or date.today()
    base = _resolve_base_date(expiry_date, today=today)
    delta = EXTEND_DELTAS.get(duration_code, EXTEND_DELTAS['30d'])
    target = base + delta
    return expiry_date, target.isoformat(), EXTEND_LABELS.get(duration_code, EXTEND_LABELS['30d'])


def extend_vps_date(expiry_date: str, duration_code: str) -> str:
    _, new_expiry, _ = calculate_vps_extension(expiry_date, duration_code)
    return new_expiry
