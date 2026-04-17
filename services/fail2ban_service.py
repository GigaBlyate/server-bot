#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import ipaddress
import json
import logging
import os
import shutil
import time
from typing import Any, Dict, List, Tuple

import config
from core.db import add_alert_event, get_setting
from core.formatting import escape_html
from security import safe_run_command
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)
FAIL2BAN_CACHE_TTL = 20
FAIL2BAN_CONFIG_CACHE_TTL = 15


def _root_helper(*args: str) -> List[str]:
    return ['sudo', config.ROOT_HELPER, *args]


async def is_fail2ban_installed(bot_data: Dict[str, Any] | None = None, force: bool = False) -> bool:
    now = time.time()
    cache = (bot_data or {}).get('fail2ban_installed_cache') if bot_data is not None else None
    if cache and not force and now - float(cache.get('cached_at', 0)) < FAIL2BAN_CACHE_TTL:
        return bool(cache.get('value'))

    present = any(
        [
            shutil.which('fail2ban-client') is not None,
            os.path.isdir('/etc/fail2ban'),
            os.path.exists('/etc/systemd/system/fail2ban.service'),
            os.path.exists('/lib/systemd/system/fail2ban.service'),
        ]
    )
    if bot_data is not None:
        bot_data['fail2ban_installed_cache'] = {'cached_at': now, 'value': bool(present)}
    return bool(present)


async def get_fail2ban_snapshot(bot_data: Dict[str, Any] | None = None, force: bool = False) -> Dict[str, Any]:
    now = time.time()
    cache = (bot_data or {}).get('fail2ban_snapshot') if bot_data is not None else None
    if cache and not force and now - float(cache.get('cached_at', 0)) < FAIL2BAN_CACHE_TTL:
        return dict(cache.get('data') or {})

    installed = await is_fail2ban_installed(bot_data, force=force)
    empty = {
        'installed': installed,
        'active': False,
        'enabled': False,
        'jails': [],
        'bans': {},
        'total_banned': 0,
        'error': '',
    }
    if not installed:
        if bot_data is not None:
            bot_data['fail2ban_snapshot'] = {'cached_at': now, 'data': empty}
        return empty

    code, out, err = await safe_run_command(_root_helper('fail2ban-status-json'), timeout=25)
    raw = (out or err or '').strip()
    if code != 0:
        data = dict(empty)
        data['error'] = raw or 'Не удалось получить статус Fail2Ban.'
    else:
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError('invalid payload')
        except Exception:
            data = dict(empty)
            data['error'] = raw or 'Неверный ответ от Fail2Ban.'

    data.setdefault('installed', installed)
    data.setdefault('active', False)
    data.setdefault('enabled', False)
    data.setdefault('jails', [])
    data.setdefault('bans', {})
    data.setdefault('total_banned', 0)
    data.setdefault('error', '')
    normalized_bans: Dict[str, List[str]] = {}
    for jail, ips in (data.get('bans') or {}).items():
        if not isinstance(ips, list):
            continue
        normalized_bans[str(jail)] = [str(ip).strip() for ip in ips if str(ip).strip()]
    data['bans'] = normalized_bans
    data['jails'] = [str(item).strip() for item in (data.get('jails') or []) if str(item).strip()]
    try:
        data['total_banned'] = int(data.get('total_banned') or 0)
    except Exception:
        data['total_banned'] = sum(len(v) for v in normalized_bans.values())

    if bot_data is not None:
        bot_data['fail2ban_snapshot'] = {'cached_at': now, 'data': data}
    return data


async def run_fail2ban_service_action(action: str, bot_data: Dict[str, Any] | None = None) -> Tuple[bool, str]:
    action = (action or '').strip().lower()
    if action not in {'start', 'stop', 'restart'}:
        return False, 'Неподдерживаемое действие.'
    code, out, err = await safe_run_command(_root_helper('fail2ban-service', action), timeout=30)
    if bot_data is not None:
        bot_data.pop('fail2ban_snapshot', None)
        bot_data.pop('fail2ban_installed_cache', None)
    raw = (out or err or '').strip()
    if code == 0:
        return True, raw or f'Действие {action} выполнено.'
    return False, raw or f'Не удалось выполнить {action}.'


def format_fail2ban_menu_text(snapshot: Dict[str, Any], alerts_enabled: bool) -> str:
    if not snapshot.get('installed'):
        return (
            '🛡 <b>Fail2Ban</b>\n\n'
            'Статус установки: <b>не установлен</b>\n'
            'Кнопка будет активна после установки сервиса.'
        )

    status_icon = '🟢' if snapshot.get('active') else '🔴'
    enabled_icon = '✅' if snapshot.get('enabled') else '❌'
    lines = [
        '🛡 <b>Fail2Ban</b>',
        '',
        f'Установка: <b>есть</b>',
        f'Сервис: {status_icon} <b>{"активен" if snapshot.get("active") else "остановлен"}</b>',
        f'Автозапуск: {enabled_icon}',
        f'Jails: <b>{len(snapshot.get("jails") or [])}</b>',
        f'Сейчас забанено: <b>{int(snapshot.get("total_banned") or 0)}</b>',
        f'Уведомления об атаке: <b>{"включены" if alerts_enabled else "выключены"}</b>',
    ]
    jails = list(snapshot.get('jails') or [])
    if jails:
        lines.extend(['', 'Активные jail: ' + ', '.join(escape_html(j) for j in jails[:8])])
        if len(jails) > 8:
            lines.append(f'… ещё {len(jails) - 8}')
    if snapshot.get('error'):
        lines.extend(['', f'⚠️ {escape_html(snapshot["error"])}'])
    return '\n'.join(lines)


def format_fail2ban_bans_text(snapshot: Dict[str, Any]) -> str:
    if not snapshot.get('installed'):
        return '🛡 <b>Fail2Ban</b>\n\nСервис не установлен.'
    if not snapshot.get('active'):
        return '🛡 <b>Fail2Ban</b>\n\nСервис установлен, но сейчас остановлен.'

    bans = snapshot.get('bans') or {}
    lines = ['🚫 <b>Бан-лист Fail2Ban</b>']
    if not bans:
        lines.extend(['', 'Сейчас забаненных IP нет.'])
        return '\n'.join(lines)

    for jail in snapshot.get('jails') or sorted(bans):
        ips = list(bans.get(jail) or [])
        lines.extend(['', f'<b>{escape_html(jail)}</b>: {len(ips)}'])
        if ips:
            for ip in ips[:20]:
                lines.append(f'• <code>{escape_html(ip)}</code>')
            if len(ips) > 20:
                lines.append(f'… ещё {len(ips) - 20}')
    return '\n'.join(lines)


def parse_fail2ban_target(text: str, jails: List[str]) -> Tuple[str, str]:
    raw = (text or '').replace(',', ' ').strip()
    if not raw:
        raise ValueError('Введите jail и IP')
    parts = [part for part in raw.split() if part]
    if len(parts) == 1 and len(jails) == 1:
        ipaddress.ip_address(parts[0])
        return jails[0], parts[0]
    if len(parts) < 2:
        raise ValueError('Нужно указать jail и IP')

    first, last = parts[0], parts[-1]
    try:
        ipaddress.ip_address(first)
        ip = first
        jail = last
    except ValueError:
        ipaddress.ip_address(last)
        jail = first
        ip = last

    jail = jail.strip()
    if jails and jail not in jails:
        raise ValueError('Неизвестный jail')
    return jail, ip


async def fail2ban_ban_ip(jail: str, ip: str, bot_data: Dict[str, Any] | None = None) -> Tuple[bool, str]:
    code, out, err = await safe_run_command(_root_helper('fail2ban-ban-ip', jail, ip), timeout=20)
    if bot_data is not None:
        bot_data.pop('fail2ban_snapshot', None)
    raw = (out or err or '').strip()
    if code == 0:
        return True, raw or f'IP {ip} забанен в {jail}.'
    return False, raw or f'Не удалось забанить IP {ip}.'


async def fail2ban_unban_ip(jail: str, ip: str, bot_data: Dict[str, Any] | None = None) -> Tuple[bool, str]:
    code, out, err = await safe_run_command(_root_helper('fail2ban-unban-ip', jail, ip), timeout=20)
    if bot_data is not None:
        bot_data.pop('fail2ban_snapshot', None)
    raw = (out or err or '').strip()
    if code == 0:
        return True, raw or f'IP {ip} разбанен в {jail}.'
    return False, raw or f'Не удалось разбанить IP {ip}.'




async def get_fail2ban_config_snapshot(bot_data: Dict[str, Any] | None = None, force: bool = False) -> Dict[str, Any]:
    now = time.time()
    cache = (bot_data or {}).get('fail2ban_config_snapshot') if bot_data is not None else None
    if cache and not force and now - float(cache.get('cached_at', 0)) < FAIL2BAN_CONFIG_CACHE_TTL:
        return dict(cache.get('data') or {})

    installed = await is_fail2ban_installed(bot_data, force=force)
    empty = {
        'installed': installed,
        'path': '/etc/fail2ban/jail.local',
        'exists': False,
        'available_sections': [],
        'sections': {'DEFAULT': {}, 'sshd': {}},
        'error': '',
    }
    if not installed:
        if bot_data is not None:
            bot_data['fail2ban_config_snapshot'] = {'cached_at': now, 'data': empty}
        return empty

    code, out, err = await safe_run_command(_root_helper('fail2ban-config-json'), timeout=25)
    raw = (out or err or '').strip()
    if code != 0:
        data = dict(empty)
        data['error'] = raw or 'Не удалось получить конфигурацию Fail2Ban.'
    else:
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError('invalid payload')
        except Exception:
            data = dict(empty)
            data['error'] = raw or 'Неверный ответ от редактора конфигурации.'

    data.setdefault('installed', installed)
    data.setdefault('path', '/etc/fail2ban/jail.local')
    data.setdefault('exists', False)
    data.setdefault('available_sections', [])
    data.setdefault('sections', {'DEFAULT': {}, 'sshd': {}})
    data.setdefault('error', '')
    sections = data.get('sections') or {}
    if not isinstance(sections, dict):
        sections = {}
    normalized_sections: Dict[str, Dict[str, str]] = {}
    for section_name, values in sections.items():
        if not isinstance(values, dict):
            continue
        normalized_sections[str(section_name)] = {
            str(k): str(v) for k, v in values.items() if str(v).strip() != ''
        }
    normalized_sections.setdefault('DEFAULT', {})
    normalized_sections.setdefault('sshd', {})
    data['sections'] = normalized_sections
    data['available_sections'] = [str(item) for item in (data.get('available_sections') or []) if str(item).strip()]

    if bot_data is not None:
        bot_data['fail2ban_config_snapshot'] = {'cached_at': now, 'data': data}
    return data


def _cfg_value(data: Dict[str, Any], section: str, option: str) -> str:
    return str((((data.get('sections') or {}).get(section) or {}).get(option, '')) or '').strip()


def format_fail2ban_config_text(config_data: Dict[str, Any]) -> str:
    if not config_data.get('installed'):
        return '⚙️ <b>Редактор конфигурации Fail2Ban</b>\n\nFail2Ban не установлен.'

    def show(section: str, option: str, fallback: str = 'не задано') -> str:
        value = _cfg_value(config_data, section, option)
        return escape_html(value or fallback)

    sshd_enabled_raw = _cfg_value(config_data, 'sshd', 'enabled').lower()
    sshd_enabled = sshd_enabled_raw in {'1', 'true', 'yes', 'on'}
    enabled_text = 'true' if sshd_enabled else (_cfg_value(config_data, 'sshd', 'enabled') or 'не задано')
    lines = [
        '⚙️ <b>Редактор конфигурации Fail2Ban</b>',
        '',
        f'Файл для записи: <code>{escape_html(str(config_data.get("path") or "/etc/fail2ban/jail.local"))}</code>',
        f'Локальный override: <b>{"есть" if config_data.get("exists") else "ещё не создан"}</b>',
        'Каждое изменение сохраняется в <code>jail.local</code> с backup и проверкой перезапуска сервиса.',
        '',
        '<b>[DEFAULT]</b>',
        f'• bantime: <code>{show("DEFAULT", "bantime")}</code>',
        f'• findtime: <code>{show("DEFAULT", "findtime")}</code>',
        f'• maxretry: <code>{show("DEFAULT", "maxretry")}</code>',
        f'• ignoreip: <code>{show("DEFAULT", "ignoreip")}</code>',
        '',
        '<b>[sshd]</b>',
        f'• enabled: <code>{escape_html(enabled_text)}</code>',
        f'• port: <code>{show("sshd", "port")}</code>',
        f'• logpath: <code>{show("sshd", "logpath")}</code>',
    ]
    sections = list(config_data.get('available_sections') or [])
    if sections:
        lines.extend(['', 'Разделы: ' + ', '.join(escape_html(section) for section in sections[:12])])
        if len(sections) > 12:
            lines.append(f'… ещё {len(sections) - 12}')
    if config_data.get('error'):
        lines.extend(['', f'⚠️ {escape_html(str(config_data["error"]))}'])
    return '\n'.join(lines)

async def set_fail2ban_config_value(
    section: str,
    option: str,
    value: str,
    bot_data: Dict[str, Any] | None = None,
) -> Tuple[bool, str]:
    section = str(section or '').strip()
    option = str(option or '').strip().lower()
    value = str(value or '').strip()
    if not section or not option or not value:
        return False, 'Нужно указать раздел, параметр и значение.'

    code, out, err = await safe_run_command(_root_helper('fail2ban-config-set', section, option, value), timeout=40)
    if bot_data is not None:
        bot_data.pop('fail2ban_snapshot', None)
        bot_data.pop('fail2ban_config_snapshot', None)
        bot_data.pop('fail2ban_installed_cache', None)
    raw = (out or err or '').strip()
    if code != 0:
        return False, raw or 'Не удалось сохранить конфигурацию Fail2Ban.'
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            backup_path = str(payload.get('backup_path') or '').strip()
            suffix = f' Backup: {backup_path}' if backup_path else ''
            return True, f'Сохранено: [{section}] {option} = {value}.{suffix}'
    except Exception:
        pass
    return True, raw or f'Сохранено: [{section}] {option} = {value}.'

async def fail2ban_monitor_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    if get_setting('fail2ban_alerts_enabled', 'true') != 'true':
        return

    snapshot = await get_fail2ban_snapshot(context.application.bot_data, force=True)
    if not snapshot.get('installed') or not snapshot.get('active'):
        context.application.bot_data['fail2ban_last_bans'] = snapshot.get('bans') or {}
        return

    current: Dict[str, List[str]] = {
        str(jail): list(ips or [])
        for jail, ips in (snapshot.get('bans') or {}).items()
    }
    previous: Dict[str, List[str]] | None = context.application.bot_data.get('fail2ban_last_bans')
    context.application.bot_data['fail2ban_last_bans'] = current
    if previous is None:
        return

    new_items: List[Tuple[str, List[str]]] = []
    for jail, ips in current.items():
        known = set(previous.get(jail, []))
        added = [ip for ip in ips if ip not in known]
        if added:
            new_items.append((jail, added))

    if not new_items:
        return

    lines = ['🚨 <b>Fail2Ban: обнаружена атака</b>', '']
    for jail, ips in new_items:
        joined = ', '.join(f'<code>{escape_html(ip)}</code>' for ip in ips[:10])
        suffix = f' … ещё {len(ips) - 10}' if len(ips) > 10 else ''
        lines.append(f'• <b>{escape_html(jail)}</b>: {joined}{suffix}')
    lines.extend(['', f'Всего сейчас забанено: <b>{int(snapshot.get("total_banned") or 0)}</b>'])
    message = '\n'.join(lines)
    try:
        await context.bot.send_message(
            chat_id=context.application.bot_data['admin_id'],
            text=message,
            parse_mode='HTML',
        )
        add_alert_event('fail2ban_attack', message)
    except Exception:
        logger.exception('Failed to send Fail2Ban attack notification')
