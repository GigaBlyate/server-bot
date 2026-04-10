#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from telegram import Update
from telegram.ext import ContextTypes

from core.formatting import days_left_text, escape_html, format_size
from services.certificates import get_certificates, get_expiring_certificates
from services.system_info import get_process_detail, get_server_info, get_top_processes
from ui.keyboards import (
    back_button,
    info_detail_keyboard,
    info_keyboard,
    process_detail_keyboard,
    process_list_keyboard,
    process_overview_keyboard,
)


async def show_info_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        'ℹ️ <b>Информация</b>\n\nВыберите, что показать.',
        reply_markup=info_keyboard(),
        parse_mode='HTML',
    )


async def show_server_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    info = await get_server_info(context.application.bot_data)
    geo = info['public_geo']
    docker_line = 'Docker недоступен'
    if info['docker_total'] is not None:
        docker_line = f'{info["docker_running"]}/{info["docker_total"]} контейнеров запущено'

    board_line = ' / '.join(
        part for part in [info['product_vendor'], info['product_name']] if part != 'N/A'
    ) or 'N/A'
    board_model = ' / '.join(
        part for part in [info['board_vendor'], info['board_name']] if part != 'N/A'
    ) or 'N/A'
    disk_lines = info['disk_models'] or ['N/A']
    nic_lines = info['nic_models'] or ['N/A']

    text_lines = [
        '🖥️ <b>Информация о сервере</b>',
        '',
        '<b>Платформа</b>',
        f'• Hostname: <code>{escape_html(info["hostname"])}</code>',
        f'• ОС: {escape_html(info["os_name"])}',
        f'• Ядро: {escape_html(info["kernel"])} ({escape_html(info["arch"])})',
        f'• Аптайм: {escape_html(info["uptime"])}',
        '',
        '<b>Железо</b>',
        f'• CPU: {escape_html(info["cpu_model"])}',
        f'• Ядра/потоки: {info["cpu_cores"]}/{info["cpu_count"]}',
        f'• RAM: {escape_html(info["ram_total"])}',
        f'• Платформа VPS/сервер: {escape_html(board_line)}',
        f'• Материнская плата: {escape_html(board_model)}',
        '',
        '<b>Диски</b>',
        *[f'• {escape_html(line)}' for line in disk_lines[:6]],
        '',
        '<b>Сетевые адаптеры</b>',
        *[f'• {escape_html(line)}' for line in nic_lines[:6]],
        '',
        '<b>Сеть и расположение</b>',
        f'• Публичный IP: <code>{escape_html(geo.get("ip", "N/A"))}</code>',
        f'• Гео: {escape_html(geo.get("city", "N/A"))}, {escape_html(geo.get("country", "N/A"))}',
        f'• Провайдер: {escape_html(geo.get("org", "N/A"))}',
        f'• ASN: {escape_html(geo.get("asn", "N/A"))}',
        f'• Локальные IP: {escape_html(", ".join(info["local_ips"]) or "N/A")}',
        f'• Docker: {escape_html(docker_line)}',
    ]
    await query.edit_message_text(
        '\n'.join(text_lines),
        reply_markup=info_detail_keyboard(),
        parse_mode='HTML',
    )


async def show_certificates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    certificates = await get_certificates(context.application.bot_data, force=True)
    if not certificates:
        text = (
            '🔐 <b>Сертификаты</b>\n\n'
            'Сертификаты не найдены в типовых путях.\n'
            'Проверьте Nginx, Let\'s Encrypt, Prosody или панели в /opt, /srv, /usr/local.'
        )
    else:
        expiring = await get_expiring_certificates(context.application.bot_data, 30)
        lines = [
            '🔐 <b>Сертификаты</b>',
            '',
            f'Найдено: <b>{len(certificates)}</b>',
            f'До 30 дней: <b>{len(expiring)}</b>',
            '',
        ]
        for item in certificates[:15]:
            lines.append(
                f'• {escape_html(item["common_name"])} — {days_left_text(item["days_left"])} '
                f'[{escape_html(item["service"])}]'
            )
            lines.append(f'  <code>{escape_html(item["path"])}</code>')
        text = '\n'.join(lines)
    await query.edit_message_text(
        text,
        reply_markup=back_button('info_menu'),
        parse_mode='HTML',
    )


async def show_top_processes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    snapshot = await get_top_processes(limit=6)
    cpu_top = snapshot.get('cpu_top') or []
    ram_top = snapshot.get('ram_top') or []

    cpu_line = '• Нет данных'
    if cpu_top:
        item = cpu_top[0]
        cpu_line = f"• {escape_html(item['name'])} · PID <code>{item['pid']}</code> · {item['cpu_percent']:.1f}% CPU"

    ram_line = '• Нет данных'
    if ram_top:
        item = ram_top[0]
        ram_line = f"• {escape_html(item['name'])} · PID <code>{item['pid']}</code> · {escape_html(format_size(item['ram_bytes']))}"

    lines = [
        '🔥 <b>CPU / RAM процессы</b>',
        '',
        '<b>Сейчас больше всего нагружают:</b>',
        cpu_line,
        ram_line,
        '',
        'Нажмите кнопку ниже, чтобы открыть подробный список и карточку конкретного процесса.',
    ]
    await query.edit_message_text(
        '\n'.join(lines),
        reply_markup=process_overview_keyboard(),
        parse_mode='HTML',
    )


async def show_process_list(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str) -> None:
    query = update.callback_query
    await query.answer()
    snapshot = await get_top_processes(limit=8)
    items = snapshot.get('cpu_top' if mode == 'cpu' else 'ram_top') or []
    lines = [f"🔥 <b>Топ процессов по {'CPU' if mode == 'cpu' else 'RAM'}</b>", '']
    for item in items:
        if mode == 'cpu':
            lines.append(
                f"• {escape_html(item['name'])} · PID <code>{item['pid']}</code> · {item['cpu_percent']:.1f}% CPU · {escape_html(format_size(item['ram_bytes']))} RAM"
            )
        else:
            lines.append(
                f"• {escape_html(item['name'])} · PID <code>{item['pid']}</code> · {escape_html(format_size(item['ram_bytes']))} RAM · {item['cpu_percent']:.1f}% CPU"
            )
    if not items:
        lines.append('• Недостаточно данных для оценки.')
    await query.edit_message_text(
        '\n'.join(lines),
        reply_markup=process_list_keyboard(items, mode),
        parse_mode='HTML',
    )


async def show_process_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, pid: int) -> None:
    query = update.callback_query
    await query.answer()
    item = await get_process_detail(pid)
    if not item:
        await query.edit_message_text(
            '❌ Процесс не найден или доступ к нему запрещён.',
            reply_markup=back_button('info_top_processes'),
        )
        return

    lines = [
        '🔎 <b>Процесс</b>',
        '',
        f"• Имя: {escape_html(item['name'])}",
        f"• PID: <code>{item['pid']}</code>",
        f"• PPID: <code>{item['ppid']}</code>",
        f"• Пользователь: {escape_html(item['username'])}",
        f"• Статус: {escape_html(item['status'])}",
        f"• CPU: <b>{item['cpu_percent']:.1f}%</b>",
        f"• RAM: <b>{escape_html(format_size(item['rss']))}</b> ({item['ram_percent']:.1f}%)",
        f"• VMS: {escape_html(format_size(item['vms']))}",
        f"• Потоки: {item['threads']}",
        f"• Uptime: {escape_html(item['uptime'])}",
        '',
        '<b>Команда</b>',
        f"<code>{escape_html(item['cmdline'])}</code>",
    ]
    await query.edit_message_text(
        '\n'.join(lines),
        reply_markup=process_detail_keyboard(pid),
        parse_mode='HTML',
    )
