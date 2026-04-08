#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from telegram import Update
from telegram.ext import ContextTypes

from core.formatting import escape_html
from services.geolocation import get_public_ip_info
from services.ping_service import get_ping_targets, latency_bar, run_ping
from ui.keyboards import back_button, ping_keyboard


async def show_ping_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query:
        await query.answer()
    geo = await get_public_ip_info(context.application.bot_data)
    region = geo.get('region', 'global')
    text = (
        '🏓 <b>Диагностика сети</b>\n\n'
        'Здесь можно проверить интернет, DNS, региональные точки или свой домен.\n'
        f'Сервер находится ближе к региону: <b>{escape_html(region)}</b>.\n\n'
        '• Быстрая проверка — несколько надёжных IP\n'
        '• DNS — домены и резолвинг\n'
        '• Региональные точки — точки ближе к серверу\n'
        '• Свой хост — ручной ввод адреса'
    )
    if query:
        await query.edit_message_text(text, reply_markup=ping_keyboard(region), parse_mode='HTML')
    else:
        await update.message.reply_text(text, reply_markup=ping_keyboard(region), parse_mode='HTML')


async def run_predefined_ping(update: Update, context: ContextTypes.DEFAULT_TYPE, category: str) -> None:
    query = update.callback_query
    await query.answer()
    geo = await get_public_ip_info(context.application.bot_data)
    targets = get_ping_targets(geo.get('region', 'global'), category)
    await query.edit_message_text('⏳ Провожу сетевой тест...', parse_mode='HTML')

    results = []
    for target in targets:
        result = await run_ping(target['host'])
        result['label'] = target['label']
        results.append(result)

    lines = ['🏓 <b>Результаты проверки сети</b>', '']
    ok_count = 0
    for result in results:
        if result.get('ok'):
            ok_count += 1
            lines.append(
                f"• <b>{escape_html(result['label'])}</b> — {result['rating']}\n"
                f"  avg {result['avg']:.1f} ms {latency_bar(result['avg'])} · "
                f"loss {result['loss']:.0f}% · min/max {result['min']:.1f}/{result['max']:.1f}"
            )
        else:
            lines.append(
                f"• <b>{escape_html(result['label'])}</b> — ошибка: {escape_html(result.get('error', 'неизвестно'))}"
            )

    lines.extend(['', '<b>Вывод</b>'])
    if ok_count == len(results):
        lines.append('• Сеть отвечает стабильно, базовая связность в норме.')
    elif ok_count == 0:
        lines.append('• Нет ответа ни от одной точки. Похоже на проблему с каналом или ICMP.')
    else:
        lines.append('• Часть точек отвечает, часть нет. Проверьте DNS, фильтрацию ICMP и маршрут.')

    await query.edit_message_text(
        '\n'.join(lines),
        reply_markup=back_button('ping_menu'),
        parse_mode='HTML',
    )


async def ask_custom_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    context.user_data['awaiting'] = 'ping_host'
    await query.edit_message_text(
        '✍️ <b>Свой хост</b>\n\nОтправьте IP или домен одним сообщением.',
        reply_markup=back_button('ping_menu'),
        parse_mode='HTML',
    )


async def run_custom_ping(update: Update, context: ContextTypes.DEFAULT_TYPE, host: str) -> None:
    message = await update.message.reply_text(f'⏳ Пингую <code>{escape_html(host)}</code>...', parse_mode='HTML')
    result = await run_ping(host)
    if not result.get('ok'):
        await message.edit_text(
            f'❌ Не удалось проверить <code>{escape_html(host)}</code>: {escape_html(result.get("error", "ошибка"))}',
            reply_markup=back_button('menu'),
            parse_mode='HTML',
        )
        return

    text = (
        '🏓 <b>Результат ping</b>\n\n'
        f'Хост: <code>{escape_html(host)}</code>\n'
        f'Качество: <b>{escape_html(result["rating"])}</b>\n'
        f'Задержка: avg {result["avg"]:.1f} ms {latency_bar(result["avg"])}\n'
        f'Потери: {result["loss"]:.0f}%\n'
        f'Min/Max: {result["min"]:.1f}/{result["max"]:.1f} ms\n\n'
    )
    if result['loss'] == 0 and result['avg'] <= 80:
        text += 'Соединение выглядит нормальным для повседневной работы.'
    elif result['loss'] > 0:
        text += 'Есть потери пакетов. Это может ощущаться как нестабильность соединения.'
    else:
        text += 'Ответ есть, но задержка заметная. Проверьте маршрут или удалённую точку.'

    await message.edit_text(text, reply_markup=back_button('ping_menu'), parse_mode='HTML')
