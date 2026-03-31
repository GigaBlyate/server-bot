#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import calendar
import json
from typing import Dict, Iterable, List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton('🔄 Обновить', callback_data='refresh_dashboard'),
                InlineKeyboardButton('🏓 Ping', callback_data='ping_menu'),
            ],
            [
                InlineKeyboardButton('📋 VPS', callback_data='vps_menu'),
                InlineKeyboardButton('📦 Бэкап', callback_data='backup_menu'),
            ],
            [
                InlineKeyboardButton('ℹ️ Информация', callback_data='info_menu'),
                InlineKeyboardButton('⚙️ Настройки', callback_data='settings_menu'),
            ],
            [
                InlineKeyboardButton('🔐 Пароль', callback_data='pass_menu'),
                InlineKeyboardButton('🔁 Перезагрузка', callback_data='reboot_confirm'),
            ],
        ]
    )


def back_button(target: str = 'menu') -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton('◀️ Назад', callback_data=target)]]
    )


def info_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton('🖥️ О сервере', callback_data='info_server')],
            [InlineKeyboardButton('🔐 Сертификаты', callback_data='info_certs')],
            [InlineKeyboardButton('◀️ Назад', callback_data='menu')],
        ]
    )


def settings_keyboard(settings: Dict[str, str]) -> InlineKeyboardMarkup:
    report = '✅' if settings.get('enable_daily_report') == 'true' else '❌'
    traffic = (
        '∞'
        if settings.get('traffic_mode') == 'unlimited'
        else f"{settings.get('traffic_quota_gb', '3072')} GB"
    )
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(
                f'CPU порог: {settings.get("cpu_threshold", "85")}% ',
                callback_data='set_cpu_threshold',
            )],
            [InlineKeyboardButton(
                f'RAM порог: {settings.get("ram_threshold", "90")}% ',
                callback_data='set_ram_threshold',
            )],
            [InlineKeyboardButton(
                f'SSD порог: {settings.get("disk_threshold", "90")}% ',
                callback_data='set_disk_threshold',
            )],
            [InlineKeyboardButton(
                f'Ежедневный отчёт: {report}',
                callback_data='toggle_daily_report',
            )],
            [InlineKeyboardButton(
                f'Время отчёта: {settings.get("report_time", "09:00")}',
                callback_data='set_report_time',
            )],
            [InlineKeyboardButton(
                f'Лимит трафика: {traffic}',
                callback_data='traffic_menu',
            )],
            [InlineKeyboardButton('Ключевые сервисы', callback_data='service_monitor_menu')],
            [InlineKeyboardButton('Обновить сервер', callback_data='system_update_check')],
            [InlineKeyboardButton('Обновить бота', callback_data='bot_update_check')],
            [InlineKeyboardButton('◀️ Назад', callback_data='menu')],
        ]
    )


def traffic_keyboard(settings: Dict[str, str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton('Безлимит', callback_data='traffic_mode_unlimited'),
                InlineKeyboardButton('Пакет', callback_data='traffic_mode_quota'),
            ],
            [InlineKeyboardButton(
                f'Размер пакета: {settings.get("traffic_quota_gb", "3072")} GB',
                callback_data='traffic_set_quota',
            )],
            [InlineKeyboardButton(
                f'Период: {settings.get("traffic_cycle_days", "30")} дн.',
                callback_data='traffic_set_cycle',
            )],
            [InlineKeyboardButton('Сбросить текущий цикл', callback_data='traffic_reset_cycle')],
            [InlineKeyboardButton('◀️ Назад', callback_data='settings_menu')],
        ]
    )


def service_monitor_keyboard(manual_items: List[Dict[str, str]], docker_permission_needed: bool = False) -> InlineKeyboardMarkup:
    keyboard: List[List[InlineKeyboardButton]] = [
        [InlineKeyboardButton('🔎 Пересканировать', callback_data='service_rescan')],
        [
            InlineKeyboardButton('➕ systemd', callback_data='service_add_systemd'),
            InlineKeyboardButton('➕ process', callback_data='service_add_process'),
        ],
        [InlineKeyboardButton('➕ docker', callback_data='service_add_docker')],
    ]
    if docker_permission_needed:
        keyboard.append([InlineKeyboardButton('🔐 Дать доступ к Docker', callback_data='service_grant_docker')])

    for idx, item in enumerate(manual_items[:8]):
        label = item.get('label') or item.get('name') or f'#{idx + 1}'
        keyboard.append([
            InlineKeyboardButton(f'🗑 Удалить: {label}', callback_data=f'service_remove_{idx}')
        ])
    if manual_items:
        keyboard.append([InlineKeyboardButton('🧹 Очистить ручной список', callback_data='service_clear_manual')])
    keyboard.append([InlineKeyboardButton('◀️ Назад', callback_data='settings_menu')])
    return InlineKeyboardMarkup(keyboard)


def confirm_keyboard(yes_callback: str, no_callback: str = 'menu') -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton('✅ Да', callback_data=yes_callback),
                InlineKeyboardButton('❌ Нет', callback_data=no_callback),
            ]
        ]
    )


def ping_keyboard(region: str) -> InlineKeyboardMarkup:
    region_label = {
        'europe': 'Европа',
        'north_america': 'Северная Америка',
        'asia_pacific': 'Азия/Тихий океан',
        'global': 'Глобально',
    }.get(region, 'регион')
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton('⚡ Быстрая проверка', callback_data='ping_run_quick')],
            [InlineKeyboardButton('🌐 Проверить DNS', callback_data='ping_run_dns')],
            [InlineKeyboardButton(
                f'🧭 Региональные точки ({region_label})',
                callback_data='ping_run_regional',
            )],
            [InlineKeyboardButton('✍️ Свой хост', callback_data='ping_custom_prompt')],
            [InlineKeyboardButton('◀️ Назад', callback_data='menu')],
        ]
    )


def password_keyboard() -> InlineKeyboardMarkup:
    rows = [['10', '12', '16'], ['20', '24', '32']]
    keyboard = [
        [
            InlineKeyboardButton(length, callback_data=f'password_{length}')
            for length in row
        ]
        for row in rows
    ]
    keyboard.append([InlineKeyboardButton('◀️ Назад', callback_data='menu')])
    return InlineKeyboardMarkup(keyboard)


def backup_keyboard(settings: Dict[str, str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton('📦 Базовый бэкап', callback_data='backup_create')],
            [InlineKeyboardButton('🎯 Умный бэкап', callback_data='backup_smart')],
            [InlineKeyboardButton('📖 Инструкция по восстановлению', callback_data='backup_instructions')],
            [InlineKeyboardButton(
                f'Интервал: {settings.get("backup_interval", "24")} ч',
                callback_data='backup_set_interval',
            )],
            [InlineKeyboardButton(
                f'Хранить: {settings.get("backup_keep_count", "10")}',
                callback_data='backup_set_keep',
            )],
            [InlineKeyboardButton('Настройки Google Drive', callback_data='backup_gdrive_settings')],
            [InlineKeyboardButton('◀️ Назад', callback_data='menu')],
        ]
    )


def vps_menu_keyboard(vps_rows: List[Dict[str, str]]) -> InlineKeyboardMarkup:
    keyboard = []
    for item in vps_rows[:15]:
        keyboard.append([
            InlineKeyboardButton(
                f"{item['name']} • {item['expiry_date']}",
                callback_data=f"vps_open_{item['id']}",
            )
        ])
    keyboard.extend(
        [
            [InlineKeyboardButton('➕ Добавить VPS', callback_data='vps_add')],
            [InlineKeyboardButton('◀️ Назад', callback_data='menu')],
        ]
    )
    return InlineKeyboardMarkup(keyboard)


def vps_actions_keyboard(vps_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton('Продлить на 30 дней', callback_data=f'vps_extend_{vps_id}_30d'),
                InlineKeyboardButton('3 месяца', callback_data=f'vps_extend_{vps_id}_3m'),
            ],
            [
                InlineKeyboardButton('6 месяцев', callback_data=f'vps_extend_{vps_id}_6m'),
                InlineKeyboardButton('12 месяцев', callback_data=f'vps_extend_{vps_id}_12m'),
            ],
            [InlineKeyboardButton('Удалить', callback_data=f'vps_delete_{vps_id}')],
            [InlineKeyboardButton('◀️ Назад', callback_data='vps_menu')],
        ]
    )


def calendar_keyboard(year: int, month: int) -> InlineKeyboardMarkup:
    cal = calendar.Calendar(firstweekday=0)
    keyboard: List[List[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton('◀', callback_data=f'vps_cal_prev_{year}_{month}'),
            InlineKeyboardButton(f'{calendar.month_name[month]} {year}', callback_data='noop'),
            InlineKeyboardButton('▶', callback_data=f'vps_cal_next_{year}_{month}'),
        ],
        [
            InlineKeyboardButton(day, callback_data='noop')
            for day in ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']
        ],
    ]
    for week in cal.monthdayscalendar(year, month):
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(' ', callback_data='noop'))
            else:
                row.append(
                    InlineKeyboardButton(
                        str(day),
                        callback_data=f'vps_pick_{year}_{month}_{day}',
                    )
                )
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton('Отмена', callback_data='vps_cancel_add')])
    return InlineKeyboardMarkup(keyboard)


def smart_backup_keyboard(
    items: List[Dict[str, str]],
    selected: Iterable[str],
    page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    selected_set = set(selected)
    keyboard = []
    for item in items:
        mark = '✅' if item['id'] in selected_set else '⬜️'
        keyboard.append([
            InlineKeyboardButton(
                f"{mark} {item['name']} ({item['size_text']})",
                callback_data=f"backup_toggle_{item['id']}_{page}",
            )
        ])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton('◀', callback_data=f'backup_page_{page - 1}'))
    nav.append(InlineKeyboardButton(f'{page + 1}/{total_pages}', callback_data='noop'))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton('▶', callback_data=f'backup_page_{page + 1}'))
    keyboard.append(nav)
    keyboard.append([
        InlineKeyboardButton('✅ Выбрать всё', callback_data='backup_select_all'),
        InlineKeyboardButton('🧹 Снять выбранное', callback_data='backup_clear_selection'),
    ])
    keyboard.append([InlineKeyboardButton('💾 Запомнить выбор', callback_data='backup_save_selection')])
    keyboard.append([InlineKeyboardButton('📦 Создать бэкап', callback_data='backup_create_selected')])
    keyboard.append([InlineKeyboardButton('◀️ Назад', callback_data='backup_menu')])
    return InlineKeyboardMarkup(keyboard)
