#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import calendar
import json
from typing import Dict, Iterable, List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup



def menu_keyboard(show_prosody: bool = False) -> InlineKeyboardMarkup:
    rows = [
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
    if show_prosody:
        rows.insert(2, [InlineKeyboardButton('💬 Prosody', callback_data='prosody_menu')])
    return InlineKeyboardMarkup(rows)


def back_button(target: str = 'menu') -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton('◀️ Назад', callback_data=target)]]
    )


def back_main_keyboard(back_target: str = 'service_monitor_menu', main_target: str = 'menu') -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton('◀️ Назад', callback_data=back_target),
        InlineKeyboardButton('🏠 Главное меню', callback_data=main_target),
    ]])


def info_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton('🖥️ О сервере', callback_data='info_server')],
        [InlineKeyboardButton('🔥 CPU/RAM процессы', callback_data='info_top_processes')],
        [InlineKeyboardButton('🔐 Сертификаты', callback_data='info_certs')],
        [InlineKeyboardButton('◀️ Назад', callback_data='menu')],
    ]
    return InlineKeyboardMarkup(rows)


def info_detail_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton('🔥 CPU/RAM процессы', callback_data='info_top_processes')],
            [InlineKeyboardButton('◀️ Назад', callback_data='info_menu')],
        ]
    )


def settings_keyboard(settings: Dict[str, str], fail2ban_available: bool = False) -> InlineKeyboardMarkup:
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
            [InlineKeyboardButton(
                '🛡 Fail2Ban' if fail2ban_available else '🛡 Fail2Ban (не установлен)',
                callback_data='fail2ban_menu' if fail2ban_available else 'fail2ban_unavailable',
            )],
            [InlineKeyboardButton('Ключевые сервисы', callback_data='service_monitor_menu')],
            [InlineKeyboardButton('Обновить сервер', callback_data='system_update_check')],
            [InlineKeyboardButton('Обновить бота', callback_data='bot_update_check')],
            [InlineKeyboardButton('◀️ Назад', callback_data='menu')],
        ]
    )


def traffic_keyboard(settings: Dict[str, str]) -> InlineKeyboardMarkup:
    mode = settings.get('traffic_mode', 'unlimited')
    quota = settings.get('traffic_quota_gb', '3072')
    activation = settings.get('traffic_activation_date', '') or 'не указана'
    overage = settings.get('traffic_overage_price_rub_per_tb', '200')
    synced = 'да' if str(settings.get('traffic_period_sync_used_bytes', '')).strip() else 'нет'
    mode_label = 'Безлимит' if mode == 'unlimited' else 'Пакет'
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton('Безлимит', callback_data='traffic_mode_unlimited'),
                InlineKeyboardButton('Пакет', callback_data='traffic_mode_quota'),
            ],
            [InlineKeyboardButton(f'Режим: {mode_label}', callback_data='traffic_menu')],
            [InlineKeyboardButton(f'Размер пакета: {quota} GB', callback_data='traffic_set_quota')],
            [InlineKeyboardButton(f'Дата активации: {activation}', callback_data='traffic_set_activation')],
            [InlineKeyboardButton(f'Стоимость перерасхода: {overage} RUB/TB', callback_data='traffic_set_overage')],
            [InlineKeyboardButton(f'Синхронизация периода: {synced}', callback_data='traffic_sync_used')],
            [InlineKeyboardButton('Сбросить текущий период', callback_data='traffic_reset_cycle')],
            [
                InlineKeyboardButton('◀️ Назад', callback_data='settings_menu'),
                InlineKeyboardButton('🏠 Главное меню', callback_data='menu'),
            ],
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
    keyboard.append([
        InlineKeyboardButton('◀️ Назад', callback_data='settings_menu'),
        InlineKeyboardButton('🏠 Главное меню', callback_data='menu'),
    ])
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
            [InlineKeyboardButton('Указать ID папки Google Drive', callback_data='backup_set_gdrive')],
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
                InlineKeyboardButton('+30 дней', callback_data=f'vps_extend_{vps_id}_30d'),
                InlineKeyboardButton('+1 месяц', callback_data=f'vps_extend_{vps_id}_1m'),
            ],
            [
                InlineKeyboardButton('+3 месяца', callback_data=f'vps_extend_{vps_id}_3m'),
                InlineKeyboardButton('+6 месяцев', callback_data=f'vps_extend_{vps_id}_6m'),
            ],
            [
                InlineKeyboardButton('+12 месяцев', callback_data=f'vps_extend_{vps_id}_12m'),
                InlineKeyboardButton('Точная дата', callback_data=f'vps_exact_{vps_id}'),
            ],
            [InlineKeyboardButton('Удалить', callback_data=f'vps_delete_{vps_id}')],
            [InlineKeyboardButton('◀️ Назад', callback_data='vps_menu')],
        ]
    )


def calendar_keyboard(
    year: int,
    month: int,
    *,
    mode: str = 'new',
    vps_id: int | None = None,
    cancel_callback: str | None = None,
) -> InlineKeyboardMarkup:
    cal = calendar.Calendar(firstweekday=0)

    if mode == 'new':
        prev_cb = f'vps_cal_new_prev_{year}_{month}'
        next_cb = f'vps_cal_new_next_{year}_{month}'
    else:
        prev_cb = f'vps_cal_edit_{vps_id}_prev_{year}_{month}'
        next_cb = f'vps_cal_edit_{vps_id}_next_{year}_{month}'

    keyboard: List[List[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton('◀', callback_data=prev_cb),
            InlineKeyboardButton(f'{calendar.month_name[month]} {year}', callback_data='noop'),
            InlineKeyboardButton('▶', callback_data=next_cb),
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
                if mode == 'new':
                    pick_cb = f'vps_pick_new_{year}_{month}_{day}'
                else:
                    pick_cb = f'vps_pick_edit_{vps_id}_{year}_{month}_{day}'
                row.append(InlineKeyboardButton(str(day), callback_data=pick_cb))
        keyboard.append(row)

    keyboard.append([
        InlineKeyboardButton('Отмена', callback_data=cancel_callback or ('vps_cancel_add' if mode == 'new' else f'vps_open_{vps_id}'))
    ])
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



def process_overview_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton('⚙️ Топ CPU', callback_data='info_top_cpu'),
                InlineKeyboardButton('🧠 Топ RAM', callback_data='info_top_ram'),
            ],
            [InlineKeyboardButton('◀️ Назад', callback_data='info_menu')],
        ]
    )


def process_list_keyboard(items: list[dict], mode: str) -> InlineKeyboardMarkup:
    rows = []
    for item in items[:8]:
        label = f"{item['name']} · PID {item['pid']}"
        rows.append([InlineKeyboardButton(label[:60], callback_data=f"proc_pid_{item['pid']}")])
    rows.append([
        InlineKeyboardButton('⚙️ CPU', callback_data='info_top_cpu'),
        InlineKeyboardButton('🧠 RAM', callback_data='info_top_ram'),
    ])
    rows.append([InlineKeyboardButton('◀️ Назад', callback_data='info_top_processes')])
    return InlineKeyboardMarkup(rows)


def process_detail_keyboard(pid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton('🔄 Обновить', callback_data=f'proc_pid_{pid}')],
            [
                InlineKeyboardButton('⚙️ Топ CPU', callback_data='info_top_cpu'),
                InlineKeyboardButton('🧠 Топ RAM', callback_data='info_top_ram'),
            ],
            [InlineKeyboardButton('◀️ Назад', callback_data='info_top_processes')],
        ]
    )

def prosody_menu_keyboard(confirm_action: str | None = None, back_target: str = 'prosody_menu') -> InlineKeyboardMarkup:
    if confirm_action:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton('✅ Да', callback_data=confirm_action), InlineKeyboardButton('❌ Нет', callback_data=back_target)],
            [InlineKeyboardButton('🏠 Главное меню', callback_data='menu')],
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('📋 Список клиентов', callback_data='prosody_list_menu')],
        [InlineKeyboardButton('⬆️ Обновить Prosody', callback_data='prosody_update_confirm')],
        [InlineKeyboardButton('🔁 Перезагрузить Prosody', callback_data='prosody_restart_confirm')],
        [InlineKeyboardButton('➕ Добавить клиента', callback_data='prosody_add_prompt')],
        [InlineKeyboardButton('🗑 Удалить клиента', callback_data='prosody_delete_prompt')],
        [InlineKeyboardButton('🔐 Сбросить пароль', callback_data='prosody_password_prompt')],
        [InlineKeyboardButton('◀️ Назад', callback_data='menu'), InlineKeyboardButton('🏠 Главное меню', callback_data='menu')],
    ])

def prosody_domains_keyboard(domains: List[str], purpose: str = 'list') -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    prefix_map = {
        'list': 'prosody_list_domain:',
        'password': 'prosody_password_domain:',
        'delete': 'prosody_delete_domain:',
    }
    prefix = prefix_map.get(purpose, 'prosody_list_domain:')
    for domain in domains[:20]:
        rows.append([InlineKeyboardButton(domain, callback_data=f'{prefix}{domain}')])
    back_target = 'prosody_menu'
    rows.append([InlineKeyboardButton('◀️ Назад', callback_data=back_target), InlineKeyboardButton('🏠 Главное меню', callback_data='menu')])
    return InlineKeyboardMarkup(rows)

def prosody_users_keyboard(domain: str, users: List[str], page: int, page_size: int = 12, action: str = 'list') -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    start = page * page_size
    end = min(start + page_size, len(users))
    callback_prefix = {
        'list': 'prosody_user_actions:',
        'password': 'prosody_password_select:',
        'delete': 'prosody_delete_confirm:',
    }.get(action, 'prosody_user_actions:')
    for jid in users[start:end]:
        label = jid if len(jid) <= 32 else jid[:29] + '…'
        icon = '👤' if action == 'list' else ('🔐' if action == 'password' else '🗑')
        rows.append([InlineKeyboardButton(f'{icon} {label}', callback_data=f'{callback_prefix}{jid}')])
    nav: List[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton('⬅️', callback_data=f'prosody_{action}_domain:{domain}|{page-1}'))
    if end < len(users):
        nav.append(InlineKeyboardButton('➡️', callback_data=f'prosody_{action}_domain:{domain}|{page+1}'))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton('◀️ Домены', callback_data=f'prosody_{action}_menu'), InlineKeyboardButton('🏠 Главное меню', callback_data='menu')])
    return InlineKeyboardMarkup(rows)

def prosody_user_actions_keyboard(jid: str, back_target: str = 'prosody_list_menu') -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('🔐 Сбросить пароль', callback_data=f'prosody_password_select:{jid}')],
        [InlineKeyboardButton('🗑 Удалить клиента', callback_data=f'prosody_delete_confirm:{jid}')],
        [InlineKeyboardButton('◀️ Назад', callback_data=back_target), InlineKeyboardButton('🏠 Главное меню', callback_data='menu')],
    ])


def fail2ban_keyboard(installed: bool, active: bool, alerts_enabled: bool) -> InlineKeyboardMarkup:
    status_label = '🔄 Статус' if installed else '🔄 Проверить'
    toggle_label = f'Уведомления: {"✅" if alerts_enabled else "❌"}'
    keyboard: List[List[InlineKeyboardButton]] = [
        [InlineKeyboardButton(status_label, callback_data='fail2ban_refresh')],
    ]
    if installed:
        keyboard.extend(
            [
                [
                    InlineKeyboardButton('▶️ Start', callback_data='fail2ban_start'),
                    InlineKeyboardButton('🔁 Restart', callback_data='fail2ban_restart'),
                ],
                [InlineKeyboardButton('⏹ Stop', callback_data='fail2ban_stop')],
                [InlineKeyboardButton('🚫 Бан-лист', callback_data='fail2ban_bans')],
                [
                    InlineKeyboardButton('⛔ Забанить IP', callback_data='fail2ban_prompt_ban'),
                    InlineKeyboardButton('♻️ Разбанить IP', callback_data='fail2ban_prompt_unban'),
                ],
                [InlineKeyboardButton(toggle_label, callback_data='fail2ban_toggle_alerts')],
            ]
        )
    keyboard.append([
        InlineKeyboardButton('◀️ Назад', callback_data='settings_menu'),
        InlineKeyboardButton('🏠 Главное меню', callback_data='menu'),
    ])
    return InlineKeyboardMarkup(keyboard)
