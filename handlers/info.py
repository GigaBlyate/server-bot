#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from telegram import Update
from telegram.ext import ContextTypes

from core.formatting import days_left_text, escape_html
from services.certificates import get_certificates, get_expiring_certificates
from services.system_info import get_server_info
from ui.keyboards import back_button, info_keyboard


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
    service_lines = []
    for name, status in info['services'].items():
        service_lines.append(f'• {escape_html(name)} — {escape_html(status)}')

    docker_line = 'Docker недоступен'
    if info['docker_total'] is not None:
        docker_line = (
            f'{info["docker_running"]}/{info["docker_total"]} контейнеров запущено'
        )

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
        '',
        '<b>Ключевые сервисы</b>',
        *service_lines[:7],
    ]
    await query.edit_message_text(
        '\n'.join(text_lines),
        reply_markup=back_button('info_menu'),
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
