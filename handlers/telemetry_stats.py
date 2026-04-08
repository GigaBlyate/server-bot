#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from telegram import Update
from telegram.ext import ContextTypes

from services.telemetry import fetch_owner_telemetry_recent, fetch_owner_telemetry_summary, telemetry_owner_enabled
from ui.keyboards import back_button, telemetry_stats_keyboard


def _fmt_versions(summary: dict) -> str:
    versions = summary.get('versions') or []
    if isinstance(versions, dict):
        items = sorted(versions.items(), key=lambda item: str(item[0]), reverse=True)
        return '\n'.join(f'• <code>{name}</code> — <b>{count}</b>' for name, count in items[:8]) or '• нет данных'
    if isinstance(versions, list):
        lines = []
        for item in versions[:8]:
            if isinstance(item, dict):
                lines.append(f"• <code>{item.get('version', 'unknown')}</code> — <b>{item.get('count', 0)}</b>")
        return '\n'.join(lines) or '• нет данных'
    return '• нет данных'


async def show_telemetry_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query:
        await query.answer()
    if not telemetry_owner_enabled():
        text = (
            '📊 <b>Статистика проекта</b>\n\n'
            'Приватная статистика не настроена.\n'
            'Укажите <code>TELEMETRY_OWNER_TOKEN</code> только на своей управляющей установке.'
        )
        if query:
            await query.edit_message_text(text, reply_markup=back_button('menu'), parse_mode='HTML')
        else:
            await update.effective_message.reply_text(text, reply_markup=back_button('menu'), parse_mode='HTML')
        return

    summary = await fetch_owner_telemetry_summary() or {}
    text = (
        '📊 <b>Статистика проекта</b>\n\n'
        f"Всего установок: <b>{summary.get('total_installs', '—')}</b>\n"
        f"Активны сейчас: <b>{summary.get('active_15m', summary.get('active_now', '—'))}</b>\n"
        f"Активны за 24ч: <b>{summary.get('active_24h', '—')}</b>\n"
        f"Новые за 7 дней: <b>{summary.get('new_7d', '—')}</b>\n"
        f"Последнее обновление: <b>{summary.get('updated_at', '—')}</b>\n\n"
        '<b>Версии</b>\n'
        f"{_fmt_versions(summary)}"
    )
    markup = telemetry_stats_keyboard()
    if query:
        await query.edit_message_text(text, reply_markup=markup, parse_mode='HTML')
    else:
        await update.effective_message.reply_text(text, reply_markup=markup, parse_mode='HTML')


async def show_telemetry_recent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    recent = await fetch_owner_telemetry_recent() or {}
    installs = recent.get('recent_installs') or []
    heartbeats = recent.get('recent_heartbeats') or []
    lines = ['📈 <b>Последняя активность проекта</b>', '']
    lines.append('<b>Новые установки</b>')
    if installs:
        for item in installs[:10]:
            if isinstance(item, dict):
                lines.append(
                    f"• {item.get('seen_at', '—')} — <code>{item.get('bot_version', 'unknown')}</code> — <code>{str(item.get('install_id', ''))[:8]}…</code>"
                )
    else:
        lines.append('• нет данных')
    lines.extend(['', '<b>Последние heartbeat</b>'])
    if heartbeats:
        for item in heartbeats[:10]:
            if isinstance(item, dict):
                lines.append(
                    f"• {item.get('seen_at', '—')} — <code>{item.get('bot_version', 'unknown')}</code> — <code>{str(item.get('install_id', ''))[:8]}…</code>"
                )
    else:
        lines.append('• нет данных')
    await query.edit_message_text('\n'.join(lines), reply_markup=telemetry_stats_keyboard(), parse_mode='HTML')
