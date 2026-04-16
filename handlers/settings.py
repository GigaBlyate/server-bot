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
from services.system_info import find_manual_service_candidate, get_service_scan_snapshot
from services.traffic_quota import (
    get_quota_summary_text,
    get_quota_status,
    reset_current_period_anchor,
    sync_current_period_usage_from_hoster,
)
from ui.keyboards import (
    back_main_keyboard,
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
    text = (
        '⚙️ <b>Настройки</b>\n\n'
        'Здесь собраны только полезные рабочие параметры: пороги, отчёт, '
        'лимит трафика, обновление сервера, обновление бота, бэкап и ключевые сервисы.\n\n'
        f'Текущий режим трафика: <b>{get_quota_summary_text()}</b>'
    )
    await query.edit_message_text(
        text,
        reply_markup=settings_keyboard(settings),
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

        else:
            return False

    except Exception:
        await update.message.reply_text(
            '❌ Некорректное значение. Попробуйте ещё раз или вернитесь назад.',
            reply_markup=back_main_keyboard('settings_menu', 'menu'),
        )
        return True

    finally:
        context.user_data.pop('awaiting_settings_input', None)

    return True
