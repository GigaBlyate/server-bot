#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from datetime import date


import config
import psutil
from telegram import Update
from telegram.ext import ContextTypes

from core.db import get_all_settings, get_setting, set_setting
from core.formatting import escape_html
from core.scheduler import schedule_daily_report_job
from security import safe_run_command, validate_google_drive_id
from services.fail2ban_service import (
    fail2ban_ban_ip,
    fail2ban_monitor_job,
    fail2ban_unban_ip,
    format_fail2ban_bans_text,
    format_fail2ban_config_text,
    format_fail2ban_menu_text,
    get_fail2ban_config_snapshot,
    get_fail2ban_snapshot,
    is_fail2ban_installed,
    parse_fail2ban_target,
    run_fail2ban_service_action,
    set_fail2ban_config_value,
)
from services.system_info import find_manual_service_candidate, get_service_scan_snapshot
from services.traffic_quota import (
    get_quota_summary_text,
    get_quota_status,
    reset_current_period_anchor,
    sync_current_period_usage_from_hoster,
)
from ui.keyboards import (
    back_main_keyboard,
    fail2ban_config_keyboard,
    fail2ban_keyboard,
    service_monitor_keyboard,
    settings_keyboard,
    traffic_keyboard,
)


def _load_manual_services() -> list[dict]:
    raw = str(get_setting('manual_services_json', '[]') or '[]')
    try:
        payload = json.loads(raw)
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
    except Exception:
        pass
    return []


def _save_manual_services(items: list[dict]) -> None:
    set_setting('manual_services_json', json.dumps(items, ensure_ascii=False))


def _humanize(name: str) -> str:
    clean = name.replace('.service', '').replace('_', ' ').replace('-', ' ').strip()
    return ' '.join(word.capitalize() for word in clean.split()) or name


def _parse_human_bytes(text: str) -> int:
    src = (text or '').strip().upper().replace(' ', '').replace(',', '.')
    if not src:
        raise ValueError('Пустое значение')
    units = {
        'B': 1,
        'KB': 1024,
        'MB': 1024 ** 2,
        'GB': 1024 ** 3,
        'TB': 1024 ** 4,
    }
    for unit in ('TB', 'GB', 'MB', 'KB', 'B'):
        if src.endswith(unit):
            num = src[:-len(unit)]
            return int(float(num) * units[unit])
    return int(float(src) * 1024 ** 3)


def _format_mb_gb(bytes_value: int | float) -> str:
    size = max(0.0, float(bytes_value))
    mb = size / (1024 ** 2)
    gb = size / (1024 ** 3)
    return f'{mb:,.1f} MB / {gb:,.2f} GB'.replace(',', ' ')


def _storage_text(path: str = '/') -> str:
    usage = psutil.disk_usage(path)
    free_percent = max(0.0, 100.0 - float(usage.percent))
    return (
        '💾 <b>Хранилище сервера</b>\n\n'
        f'Точка монтирования: <code>{path}</code>\n'
        f'• Занято: <b>{_format_mb_gb(usage.used)}</b> ({usage.percent:.1f}%)\n'
        f'• Свободно: <b>{_format_mb_gb(usage.free)}</b> ({free_percent:.1f}%)\n'
        f'• Всего: <b>{_format_mb_gb(usage.total)}</b> (100%)'
    )


def _root_helper(*args: str) -> list[str]:
    return ['sudo', config.ROOT_HELPER, *args]


FAIL2BAN_CONFIG_FIELDS = {
    'fail2ban_cfg_bantime': {
        'section': 'DEFAULT',
        'option': 'bantime',
        'title': '⏳ Bantime',
        'hint': 'Введите новое значение для <code>bantime</code>. Примеры: <code>10m</code>, <code>1h</code>, <code>86400</code>.',
    },
    'fail2ban_cfg_findtime': {
        'section': 'DEFAULT',
        'option': 'findtime',
        'title': '🕒 Findtime',
        'hint': 'Введите новое значение для <code>findtime</code>. Примеры: <code>10m</code>, <code>1h</code>, <code>600</code>.',
    },
    'fail2ban_cfg_maxretry': {
        'section': 'DEFAULT',
        'option': 'maxretry',
        'title': '🔁 Maxretry',
        'hint': 'Введите число попыток до бана. Пример: <code>5</code>.',
    },
    'fail2ban_cfg_ignoreip': {
        'section': 'DEFAULT',
        'option': 'ignoreip',
        'title': '🧾 IgnoreIP',
        'hint': 'Введите список IP/CIDR через пробел. Пример: <code>127.0.0.1/8 ::1 1.2.3.4/32</code>.',
    },
    'fail2ban_cfg_sshd_port': {
        'section': 'sshd',
        'option': 'port',
        'title': '🚪 SSH port',
        'hint': 'Введите порт или список портов для jail <code>sshd</code>. Примеры: <code>ssh</code>, <code>22</code>, <code>22,2222</code>.',
    },
    'fail2ban_cfg_sshd_logpath': {
        'section': 'sshd',
        'option': 'logpath',
        'title': '📄 SSH logpath',
        'hint': 'Введите путь к логам jail <code>sshd</code>. Примеры: <code>%(sshd_log)s</code> или <code>/var/log/auth.log</code>.',
    },
}


def _normalize_fail2ban_input(value: str, awaiting: str) -> str:
    cleaned = (value or '').strip()
    if not cleaned or '\n' in cleaned or '\r' in cleaned:
        raise ValueError
    if len(cleaned) > 400:
        raise ValueError
    if awaiting == 'fail2ban_cfg_maxretry':
        number = int(cleaned)
        if number <= 0 or number > 1000:
            raise ValueError
        return str(number)
    return cleaned

def _parse_fail2ban_custom_update(text: str) -> tuple[str, str, str]:
    raw = (text or '').strip()
    if not raw or '\n' in raw or '\r' in raw:
        raise ValueError
    if '=' in raw:
        left, value = raw.split('=', 1)
        value = value.strip()
    else:
        parts = raw.split(None, 2)
        if len(parts) < 3:
            raise ValueError
        left = f'{parts[0]} {parts[1]}'
        value = parts[2].strip()
    left_parts = left.strip().split(None, 1)
    if len(left_parts) != 2:
        raise ValueError
    section, option = left_parts[0].strip(), left_parts[1].strip()
    if not section or not option or not value:
        raise ValueError
    return section, option, value

async def _show_storage_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        _storage_text('/'),
        reply_markup=back_main_keyboard('settings_menu', 'menu'),
        parse_mode='HTML',
    )


async def _show_disk_cleanup_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    text = (
        '🧹 <b>Безопасная очистка диска</b>\n\n'
        'Будут удалены только безопасные категории мусора:\n'
        '• временные файлы в <code>/tmp</code> и <code>/var/tmp</code> старше 14 дней;\n'
        '• старые журналы systemd старше 180 дней;\n'
        '• старые ротированные логи в <code>/var/log</code> старше 180 дней;\n'
        '• старые crash dump файлы старше 180 дней;\n'
        '• кэш пакетов APT.\n\n'
        'Не удаляются:\n'
        '• проекты, базы данных, конфиги, docker-данные;\n'
        '• домашние каталоги и пользовательские файлы;\n'
        '• активные текущие логи.\n\n'
        'Запустить безопасную очистку сейчас?'
    )
    from ui.keyboards import confirm_keyboard
    await query.edit_message_text(
        text,
        reply_markup=confirm_keyboard('disk_cleanup_run', 'settings_menu'),
        parse_mode='HTML',
    )


async def _perform_disk_cleanup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    before = psutil.disk_usage('/')
    await query.edit_message_text('⏳ Выполняю безопасную очистку диска...', parse_mode='HTML')
    code, out, err = await safe_run_command(_root_helper('cleanup-disk-safe', '180'), timeout=1200)
    after = psutil.disk_usage('/')
    freed = max(0, int(after.free) - int(before.free))

    details = (out or err or '').strip()
    if code != 0:
        await query.edit_message_text(
            '❌ <b>Очистка диска завершилась с ошибкой</b>\n\n'
            f'<code>{escape_html(details[-3000:] or "Неизвестная ошибка")}</code>',
            reply_markup=back_main_keyboard('settings_menu', 'menu'),
            parse_mode='HTML',
        )
        return

    lines = [
        '✅ <b>Очистка диска завершена</b>',
        '',
        f'Освобождено: <b>{escape_html(_format_mb_gb(freed))}</b>',
        '',
        _storage_text('/'),
    ]
    if details:
        lines.extend(['', '<b>Отчёт:</b>', f'<code>{escape_html(details[-2500:])}</code>'])
    await query.edit_message_text(
        '\n'.join(lines),
        reply_markup=back_main_keyboard('settings_menu', 'menu'),
        parse_mode='HTML',
    )


async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    settings = get_all_settings()
    fail2ban_available = await is_fail2ban_installed(context.application.bot_data)
    text = (
        '⚙️ <b>Настройки</b>\n\n'
        'Здесь собраны только полезные рабочие параметры: пороги, отчёт, '
        'лимит трафика, обновление сервера, обновление бота, бэкап и ключевые сервисы.\n\n'
        f'Текущий режим трафика: <b>{get_quota_summary_text()}</b>'
    )
    await query.edit_message_text(
        text,
        reply_markup=settings_keyboard(settings, fail2ban_available=fail2ban_available),
        parse_mode='HTML',
    )


async def show_traffic_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    settings = get_all_settings()
    status = get_quota_status()
    details = []
    if status.get('mode') == 'quota':
        details.append(f"Период: <b>{status.get('used_gb', 0):.1f} GB из {status.get('quota_gb', 0):.1f} GB</b>")
        details.append(f"Остаток: <b>{status.get('remaining_gb', 0):.1f} GB</b>")
        if status.get('days_left') is not None:
            details.append(f"До сброса: <b>{status.get('days_left')} дн.</b>")
    text = '📦 <b>Лимит трафика</b>\n\n' + '\n'.join(details or [f'Текущий режим: <b>{get_quota_summary_text()}</b>'])
    await query.edit_message_text(
        text,
        reply_markup=traffic_keyboard(settings),
        parse_mode='HTML',
    )


async def _show_service_monitor(update: Update, context: ContextTypes.DEFAULT_TYPE, force: bool = False) -> None:
    query = update.callback_query
    snapshot = await get_service_scan_snapshot(context.application.bot_data, force=force)
    auto_items = snapshot.get('auto') or []
    manual_items = _load_manual_services()
    lines = ['🧩 <b>Ключевые сервисы</b>']
    if auto_items:
        lines.append('')
        lines.append('<b>Найдено автоматически:</b>')
        for label in auto_items[:12]:
            status = (snapshot.get('data') or {}).get(label, 'unknown')
            lines.append(f'• {label}: <b>{status}</b>')
    if manual_items:
        lines.append('')
        lines.append('<b>Добавлено вручную:</b>')
        for item in manual_items[:8]:
            lines.append(f"• {item.get('label') or item.get('name')}")
    if snapshot.get('scan_sources'):
        lines.append('')
        lines.append('Сканирование: ' + ', '.join(snapshot['scan_sources']))
    if snapshot.get('docker_permission_needed'):
        lines.append('')
        lines.append('⚠️ Для полного сканирования Docker нужен доступ к docker.sock.')
    await query.edit_message_text(
        '\n'.join(lines),
        reply_markup=service_monitor_keyboard(manual_items, snapshot.get('docker_permission_needed', False)),
        parse_mode='HTML',
    )




async def _show_fail2ban_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, notice: str | None = None) -> None:
    query = update.callback_query
    snapshot = await get_fail2ban_snapshot(context.application.bot_data, force=True)
    alerts_enabled = get_setting('fail2ban_alerts_enabled', 'true') == 'true'
    text = format_fail2ban_menu_text(snapshot, alerts_enabled)
    if notice:
        text += f'\n\nℹ️ {notice}'
    await query.edit_message_text(
        text,
        reply_markup=fail2ban_keyboard(
            installed=bool(snapshot.get('installed')),
            active=bool(snapshot.get('active')),
            alerts_enabled=alerts_enabled,
        ),
        parse_mode='HTML',
    )


async def _show_fail2ban_ban_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    snapshot = await get_fail2ban_snapshot(context.application.bot_data, force=True)
    await query.edit_message_text(
        format_fail2ban_bans_text(snapshot),
        reply_markup=back_main_keyboard('fail2ban_menu', 'menu'),
        parse_mode='HTML',
    )


async def _show_fail2ban_config_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, notice: str | None = None) -> None:
    query = update.callback_query
    snapshot = await get_fail2ban_config_snapshot(context.application.bot_data, force=True)
    text = format_fail2ban_config_text(snapshot)
    if notice:
        text += f'\n\nℹ️ {notice}'
    sshd_enabled = str(((snapshot.get('sections') or {}).get('sshd') or {}).get('enabled', '')).strip().lower() in {'1', 'true', 'yes', 'on'}
    await query.edit_message_text(
        text,
        reply_markup=fail2ban_config_keyboard(installed=bool(snapshot.get('installed')), sshd_enabled=sshd_enabled),
        parse_mode='HTML',
    )

async def handle_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> bool:
    query = update.callback_query

    if data == 'settings_menu':
        await show_settings(update, context)
        return True
    if data == 'traffic_menu':
        await show_traffic_menu(update, context)
        return True
    if data == 'storage_info':
        await _show_storage_info(update, context)
        return True
    if data == 'disk_cleanup_confirm':
        await _show_disk_cleanup_confirm(update, context)
        return True
    if data == 'disk_cleanup_run':
        await _perform_disk_cleanup(update, context)
        return True

    if data == 'fail2ban_unavailable':
        await query.answer('Fail2Ban не установлен на сервере.', show_alert=True)
        return True

    if data == 'fail2ban_menu':
        await query.answer()
        await _show_fail2ban_menu(update, context)
        return True

    if data == 'fail2ban_refresh':
        await query.answer('Обновляю статус...')
        await _show_fail2ban_menu(update, context)
        return True

    if data == 'fail2ban_bans':
        await query.answer()
        await _show_fail2ban_ban_list(update, context)
        return True


    if data == 'fail2ban_config_menu':
        await query.answer()
        await _show_fail2ban_config_menu(update, context)
        return True

    if data == 'fail2ban_config_refresh':
        await query.answer('Обновляю конфиг...')
        await _show_fail2ban_config_menu(update, context)
        return True

    if data == 'fail2ban_config_toggle_sshd':
        snapshot = await get_fail2ban_config_snapshot(context.application.bot_data, force=True)
        current = str(((snapshot.get('sections') or {}).get('sshd') or {}).get('enabled', '')).strip().lower() in {'1', 'true', 'yes', 'on'}
        ok, message = await set_fail2ban_config_value('sshd', 'enabled', 'false' if current else 'true', context.application.bot_data)
        await _show_fail2ban_config_menu(update, context, notice=message if ok else f'Ошибка: {message}')
        return True

    if data in FAIL2BAN_CONFIG_FIELDS:
        meta = FAIL2BAN_CONFIG_FIELDS[data]
        context.user_data['awaiting_settings_input'] = data
        await query.answer()
        await query.edit_message_text(
            f"{meta['title']}\n\n{meta['hint']}\n\nИзменение будет записано в <code>/etc/fail2ban/jail.local</code> с backup и проверкой перезапуска Fail2Ban.",
            reply_markup=back_main_keyboard('fail2ban_config_menu', 'menu'),
            parse_mode='HTML',
        )
        return True

    if data == 'fail2ban_cfg_custom':
        context.user_data['awaiting_settings_input'] = 'fail2ban_cfg_custom'
        await query.answer()
        await query.edit_message_text(
            '✍️ <b>Произвольный параметр Fail2Ban</b>\n\n'
            'Введите в формате <code>section option = value</code>.\n'
            'Примеры:\n'
            '• <code>DEFAULT bantime = 1h</code>\n'
            '• <code>sshd enabled = true</code>\n'
            '• <code>nginx-http-auth maxretry = 3</code>\n\n'
            'Изменение будет записано в <code>/etc/fail2ban/jail.local</code> с backup и проверкой перезапуска Fail2Ban.',
            reply_markup=back_main_keyboard('fail2ban_config_menu', 'menu'),
            parse_mode='HTML',
        )
        return True

    if data == 'fail2ban_toggle_alerts':
        current = get_setting('fail2ban_alerts_enabled', 'true') == 'true'
        set_setting('fail2ban_alerts_enabled', 'false' if current else 'true')
        await query.answer('Уведомления выключены' if current else 'Уведомления включены')
        await _show_fail2ban_menu(update, context)
        return True

    if data in {'fail2ban_start', 'fail2ban_stop', 'fail2ban_restart'}:
        action = data.replace('fail2ban_', '')
        await query.answer(f'Выполняю: {action}')
        ok, message = await run_fail2ban_service_action(action, context.application.bot_data)
        await _show_fail2ban_menu(update, context, notice=message if ok else f'Ошибка: {message}')
        return True

    if data == 'fail2ban_prompt_ban':
        snapshot = await get_fail2ban_snapshot(context.application.bot_data, force=True)
        if not snapshot.get('installed'):
            await query.answer('Fail2Ban не установлен.', show_alert=True)
            return True
        context.user_data['awaiting_settings_input'] = 'fail2ban_ban'
        hint = 'Введите <code>jail IP</code>. Пример: <code>sshd 1.2.3.4</code>.'
        if len(snapshot.get('jails') or []) == 1:
            hint += f"\nМожно просто IP: <code>1.2.3.4</code>, jail будет <code>{snapshot['jails'][0]}</code>."
        await query.answer()
        await query.edit_message_text(
            '⛔ <b>Забанить IP через Fail2Ban</b>\n\n' + hint,
            reply_markup=back_main_keyboard('fail2ban_menu', 'menu'),
            parse_mode='HTML',
        )
        return True

    if data == 'fail2ban_prompt_unban':
        snapshot = await get_fail2ban_snapshot(context.application.bot_data, force=True)
        if not snapshot.get('installed'):
            await query.answer('Fail2Ban не установлен.', show_alert=True)
            return True
        context.user_data['awaiting_settings_input'] = 'fail2ban_unban'
        hint = 'Введите <code>jail IP</code>. Пример: <code>sshd 1.2.3.4</code>.'
        if len(snapshot.get('jails') or []) == 1:
            hint += f"\nМожно просто IP: <code>1.2.3.4</code>, jail будет <code>{snapshot['jails'][0]}</code>."
        await query.answer()
        await query.edit_message_text(
            '♻️ <b>Разбанить IP через Fail2Ban</b>\n\n' + hint,
            reply_markup=back_main_keyboard('fail2ban_menu', 'menu'),
            parse_mode='HTML',
        )
        return True

    if data == 'set_cpu_threshold':
        context.user_data['awaiting_settings_input'] = 'cpu_threshold'
        await query.answer()
        await query.edit_message_text(
            'Введите порог CPU в процентах. Пример: <code>85</code>.',
            reply_markup=back_main_keyboard('settings_menu', 'menu'),
            parse_mode='HTML',
        )
        return True

    if data == 'set_ram_threshold':
        context.user_data['awaiting_settings_input'] = 'ram_threshold'
        await query.answer()
        await query.edit_message_text(
            'Введите порог RAM в процентах. Пример: <code>90</code>.',
            reply_markup=back_main_keyboard('settings_menu', 'menu'),
            parse_mode='HTML',
        )
        return True

    if data == 'set_disk_threshold':
        context.user_data['awaiting_settings_input'] = 'disk_threshold'
        await query.answer()
        await query.edit_message_text(
            'Введите порог SSD в процентах. Пример: <code>90</code>.',
            reply_markup=back_main_keyboard('settings_menu', 'menu'),
            parse_mode='HTML',
        )
        return True

    if data == 'toggle_daily_report':
        current = str(get_setting('enable_daily_report', 'false')).lower() == 'true'
        set_setting('enable_daily_report', 'false' if current else 'true')
        schedule_daily_report_job(context.application)
        await query.answer('Ежедневный отчёт выключен' if current else 'Ежедневный отчёт включён')
        await show_settings(update, context)
        return True

    if data == 'set_report_time':
        context.user_data['awaiting_settings_input'] = 'report_time'
        await query.answer()
        await query.edit_message_text(
            'Введите время ежедневного отчёта в формате <code>HH:MM</code>. Пример: <code>09:00</code>.',
            reply_markup=back_main_keyboard('settings_menu', 'menu'),
            parse_mode='HTML',
        )
        return True

    if data == 'traffic_mode_unlimited':
        set_setting('traffic_mode', 'unlimited')
        await show_traffic_menu(update, context)
        return True

    if data == 'traffic_mode_quota':
        set_setting('traffic_mode', 'quota')
        if not get_setting('traffic_activation_date', ''):
            set_setting('traffic_activation_date', date.today().isoformat())
        if not get_setting('traffic_cycle_start_date', ''):
            set_setting('traffic_cycle_start_date', get_setting('traffic_activation_date', date.today().isoformat()))
        await show_traffic_menu(update, context)
        return True

    if data == 'traffic_set_quota':
        context.user_data['awaiting_settings_input'] = 'traffic_quota_gb'
        await query.answer()
        await query.edit_message_text(
            'Введите размер пакета трафика в GB.\nПримеры: <code>3072</code> или <code>3000</code>.',
            reply_markup=back_main_keyboard('traffic_menu', 'menu'),
            parse_mode='HTML',
        )
        return True

    if data == 'traffic_set_activation':
        context.user_data['awaiting_settings_input'] = 'traffic_activation_date'
        await query.answer()
        await query.edit_message_text(
            'Введите дату активации услуги в формате <code>YYYY-MM-DD</code>.',
            reply_markup=back_main_keyboard('traffic_menu', 'menu'),
            parse_mode='HTML',
        )
        return True

    if data == 'traffic_set_overage':
        context.user_data['awaiting_settings_input'] = 'traffic_overage_price_rub_per_tb'
        await query.answer()
        await query.edit_message_text(
            'Введите стоимость перерасхода в RUB за 1 TB.\nПример: <code>200</code>.',
            reply_markup=back_main_keyboard('traffic_menu', 'menu'),
            parse_mode='HTML',
        )
        return True

    if data == 'traffic_sync_used':
        context.user_data['awaiting_settings_input'] = 'traffic_sync_used'
        await query.answer()
        await query.edit_message_text(
            'Отправьте уже использованный объём трафика в текущем периоде.\nПримеры: <code>120 GB</code>, <code>1.4 TB</code>.',
            reply_markup=back_main_keyboard('traffic_menu', 'menu'),
            parse_mode='HTML',
        )
        return True

    if data == 'traffic_reset_cycle':
        reset_current_period_anchor()
        await query.answer('Период трафика сброшен')
        await show_traffic_menu(update, context)
        return True

    if data == 'service_monitor_menu':
        await query.answer()
        await _show_service_monitor(update, context, force=False)
        return True

    if data == 'service_rescan':
        await query.answer('Пересканирование...')
        await _show_service_monitor(update, context, force=True)
        return True

    if data == 'service_add_systemd':
        context.user_data['awaiting_settings_input'] = 'service_add_systemd'
        await query.answer()
        await query.edit_message_text(
            'Введите имя systemd unit, например <code>nginx</code> или <code>ssh.service</code>.',
            reply_markup=back_main_keyboard('service_monitor_menu', 'menu'),
            parse_mode='HTML',
        )
        return True

    if data == 'service_add_process':
        context.user_data['awaiting_settings_input'] = 'service_add_process'
        await query.answer()
        await query.edit_message_text(
            'Введите имя процесса, который уже запущен.\nПример: <code>xray</code> или <code>telemt</code>.',
            reply_markup=back_main_keyboard('service_monitor_menu', 'menu'),
            parse_mode='HTML',
        )
        return True

    if data == 'service_add_docker':
        context.user_data['awaiting_settings_input'] = 'service_add_docker'
        await query.answer()
        await query.edit_message_text(
            'Введите имя Docker-контейнера.\nПример: <code>3x-ui</code>.',
            reply_markup=back_main_keyboard('service_monitor_menu', 'menu'),
            parse_mode='HTML',
        )
        return True

    if data.startswith('service_remove_'):
        try:
            idx = int(data.split('_')[-1])
        except Exception:
            return True
        items = _load_manual_services()
        if 0 <= idx < len(items):
            items.pop(idx)
            _save_manual_services(items)
            context.application.bot_data.pop('service_statuses', None)
        await query.answer('Удалено')
        await _show_service_monitor(update, context, force=True)
        return True

    if data == 'service_clear_manual':
        _save_manual_services([])
        context.application.bot_data.pop('service_statuses', None)
        await query.answer('Список очищен')
        await _show_service_monitor(update, context, force=True)
        return True

    return False


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    awaiting = context.user_data.get('awaiting_settings_input')
    if not awaiting:
        return False

    text = (update.message.text or '').strip()

    try:
        if awaiting in ('cpu_threshold', 'ram_threshold', 'disk_threshold'):
            value = float(text.replace(',', '.'))
            if value <= 0 or value > 100:
                raise ValueError
            set_setting(awaiting, str(int(value) if value.is_integer() else value))
            await update.message.reply_text(
                '✅ Порог сохранён.',
                reply_markup=back_main_keyboard('settings_menu', 'menu'),
            )

        elif awaiting == 'report_time':
            hour, minute = [int(part) for part in text.split(':', 1)]
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
            normalized = f'{hour:02d}:{minute:02d}'
            set_setting('report_time', normalized)
            schedule_daily_report_job(context.application)
            await update.message.reply_text(
                f'✅ Время ежедневного отчёта сохранено: {normalized}',
                reply_markup=back_main_keyboard('settings_menu', 'menu'),
            )

        elif awaiting == 'traffic_quota_gb':
            value = float(text.replace(',', '.'))
            if value <= 0:
                raise ValueError
            set_setting('traffic_mode', 'quota')
            set_setting('traffic_quota_gb', str(int(value) if value.is_integer() else value))
            await update.message.reply_text(
                '✅ Размер пакета трафика сохранён.',
                reply_markup=back_main_keyboard('traffic_menu', 'menu'),
            )

        elif awaiting == 'traffic_activation_date':
            parsed = date.fromisoformat(text)
            set_setting('traffic_activation_date', parsed.isoformat())
            set_setting('traffic_cycle_start_date', parsed.isoformat())
            await update.message.reply_text(
                '✅ Дата активации услуги сохранена.',
                reply_markup=back_main_keyboard('traffic_menu', 'menu'),
            )

        elif awaiting == 'traffic_overage_price_rub_per_tb':
            value = float(text.replace(',', '.'))
            if value < 0:
                raise ValueError
            set_setting('traffic_overage_price_rub_per_tb', str(int(value) if value.is_integer() else value))
            await update.message.reply_text(
                '✅ Стоимость перерасхода сохранена.',
                reply_markup=back_main_keyboard('traffic_menu', 'menu'),
            )

        elif awaiting == 'traffic_sync_used':
            used_bytes = _parse_human_bytes(text)
            sync_current_period_usage_from_hoster(used_bytes)
            await update.message.reply_text(
                '✅ Трафик текущего периода синхронизирован.',
                reply_markup=back_main_keyboard('traffic_menu', 'menu'),
            )

        elif awaiting in ('service_add_systemd', 'service_add_process', 'service_add_docker'):
            service_type = awaiting.replace('service_add_', '')
            found, item, message = find_manual_service_candidate(service_type, text, context.application.bot_data)
            if not found:
                await update.message.reply_text(
                    message,
                    reply_markup=back_main_keyboard('service_monitor_menu', 'menu'),
                    parse_mode='HTML',
                )
                return True

            items = _load_manual_services()
            exists = any(
                (x.get('type'), x.get('name')) == (item.get('type'), item.get('name'))
                for x in items
            )
            if not exists:
                items.append(item)
                _save_manual_services(items)

            context.application.bot_data.pop('service_statuses', None)
            await update.message.reply_text(
                f"✅ Добавлено: {item.get('label') or _humanize(item.get('name', 'service'))}",
                reply_markup=back_main_keyboard('service_monitor_menu', 'menu'),
            )

        elif awaiting in ('fail2ban_ban', 'fail2ban_unban'):
            snapshot = await get_fail2ban_snapshot(context.application.bot_data, force=True)
            jail, ip = parse_fail2ban_target(text, list(snapshot.get('jails') or []))
            if awaiting == 'fail2ban_ban':
                ok, message = await fail2ban_ban_ip(jail, ip, context.application.bot_data)
            else:
                ok, message = await fail2ban_unban_ip(jail, ip, context.application.bot_data)
            prefix = '✅' if ok else '❌'
            await update.message.reply_text(
                f'{prefix} {message}',
                reply_markup=back_main_keyboard('fail2ban_menu', 'menu'),
            )

        elif awaiting in FAIL2BAN_CONFIG_FIELDS or awaiting == 'fail2ban_cfg_custom':
            if awaiting == 'fail2ban_cfg_custom':
                section, option, value = _parse_fail2ban_custom_update(text)
            else:
                meta = FAIL2BAN_CONFIG_FIELDS[awaiting]
                section = meta['section']
                option = meta['option']
                value = _normalize_fail2ban_input(text, awaiting)
            ok, message = await set_fail2ban_config_value(section, option, value, context.application.bot_data)
            prefix = '✅' if ok else '❌'
            await update.message.reply_text(
                f'{prefix} {message}',
                reply_markup=back_main_keyboard('fail2ban_config_menu', 'menu'),
            )

        else:
            return False

    except Exception:
        error_back_target = 'settings_menu'
        if awaiting in ('fail2ban_ban', 'fail2ban_unban'):
            error_back_target = 'fail2ban_menu'
        elif awaiting in FAIL2BAN_CONFIG_FIELDS or awaiting == 'fail2ban_cfg_custom':
            error_back_target = 'fail2ban_config_menu'
        elif awaiting and str(awaiting).startswith('traffic_'):
            error_back_target = 'traffic_menu'
        elif awaiting and str(awaiting).startswith('service_'):
            error_back_target = 'service_monitor_menu'
        await update.message.reply_text(
            '❌ Некорректное значение. Попробуйте ещё раз или вернитесь назад.',
            reply_markup=back_main_keyboard(error_back_target, 'menu'),
        )
        return True

    finally:
        context.user_data.pop('awaiting_settings_input', None)

    return True
