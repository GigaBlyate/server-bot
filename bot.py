#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import subprocess
import psutil
import platform
import secrets
import string
import sqlite3
import os
import json
import aiohttp
import re
from datetime import datetime, timedelta, time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)
import config

# Константы
DB_PATH = os.path.join(os.path.dirname(__file__), 'vps_data.db')
PROCESS_LOG_PATH = os.path.join(os.path.dirname(__file__), 'high_cpu_processes.json')
FAIL2BAN_LOG_PATH = '/var/log/fail2ban.log'
ADMIN_ID = str(config.ADMIN_CHAT_ID)

# Версия бота и ссылка на GitHub
BOT_VERSION = "2.1.0"
GITHUB_REPO = "GigaBlyate/server-bot"
GITHUB_RAW_VERSION_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/version.txt"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"

# Состояния для ConversationHandler
WAITING_FOR_REPORT_INTERVAL = 1
WAITING_FOR_REPORT_FORMAT = 2
WAITING_FOR_CUSTOM_PATH = 3


# ==== БАЗА ДАННЫХ ====
def init_db():
    """Инициализация базы данных SQLite"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS vps_rental (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        expiry_date DATE NOT NULL,
                        notify_days TEXT DEFAULT '14,10,8,4,2,1',
                        last_notify TEXT)''')

        conn.execute('''CREATE TABLE IF NOT EXISTS process_alerts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        process_name TEXT,
                        pid INTEGER,
                        cpu_percent REAL,
                        memory_percent REAL,
                        status TEXT)''')

        conn.execute('''CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL)''')

        conn.execute('''CREATE TABLE IF NOT EXISTS directory_monitor (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        path TEXT NOT NULL,
                        threshold_mb INTEGER NOT NULL,
                        last_notify TEXT)''')

        conn.execute('''CREATE TABLE IF NOT EXISTS docker_monitor (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        container_name TEXT NOT NULL,
                        cpu_threshold REAL DEFAULT 50,
                        memory_threshold REAL DEFAULT 80,
                        enabled INTEGER DEFAULT 1,
                        last_notify TEXT)''')

        # Добавляем настройки по умолчанию
        default_settings = {
            'cpu_threshold': '30',
            'ram_threshold': '85',
            'disk_threshold': '85',
            'net_sent_threshold': '100',
            'net_recv_threshold': '100',
            'monitor_interval': '30',
            'history_limit': '100',
            'enable_daily_report': 'false',
            'report_time': '09:00',
            'report_format': 'detailed',
            'enable_fail2ban_alerts': 'false',
            'fail2ban_check_interval': '60',
            'enable_directory_monitor': 'false',
            'enable_docker_monitor': 'false',
            'docker_stats_interval': '60',
            'color_scheme': 'default',
            'show_emoji': 'true',
            'compact_mode': 'false'
        }

        for key, value in default_settings.items():
            cur = conn.execute("SELECT value FROM settings WHERE key=?", (key,))
            if not cur.fetchone():
                conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, value))


def db_execute(query, params=(), fetch=False):
    """Выполнение SQL запросов"""
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(query, params)
        if fetch:
            return cur.fetchall()
        conn.commit()
        return None


def get_setting(key, default=None):
    """Получение настройки из БД"""
    result = db_execute("SELECT value FROM settings WHERE key=?", (key,), fetch=True)
    return result[0][0] if result else default


def set_setting(key, value):
    """Установка настройки в БД"""
    db_execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))


def get_all_settings():
    """Получение всех настроек"""
    result = db_execute("SELECT key, value FROM settings ORDER BY key", fetch=True)
    return dict(result) if result else {}


# ==== РАБОТА С JSON ЛОГАМИ ====
def save_high_resource_processes(processes, resource_type='cpu'):
    """Сохраняет информацию о процессах с высоким потреблением ресурсов в JSON"""
    filename = f'high_{resource_type}_processes.json'
    filepath = os.path.join(os.path.dirname(__file__), filename)

    data = {
        'timestamp': datetime.now().isoformat(),
        'resource_type': resource_type,
        'processes': processes
    }

    history = []
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                history = json.load(f)
                if not isinstance(history, list):
                    history = []
        except Exception:
            history = []

    history.append(data)
    if len(history) > 100:
        history = history[-100:]

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def get_high_resource_history(resource_type='cpu', limit=10):
    """Получает историю процессов с высоким потреблением ресурсов"""
    filename = f'high_{resource_type}_processes.json'
    filepath = os.path.join(os.path.dirname(__file__), filename)

    if not os.path.exists(filepath):
        return []

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            history = json.load(f)
            return history[-limit:] if history else []
    except Exception:
        return []


# ==== ФУНКЦИИ ДЛЯ ФОРМАТИРОВАНИЯ ОТЧЕТОВ ====
def format_size(bytes_value):
    """Форматирует размер в человеко-читаемый вид"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_value < 1024.0:
            return f"{bytes_value:.1f} {unit}"
        bytes_value /= 1024.0
    return f"{bytes_value:.1f} PB"


def format_uptime(seconds):
    """Форматирует время работы"""
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    parts = []
    if days > 0:
        parts.append(f"{days}д")
    if hours > 0:
        parts.append(f"{hours}ч")
    if minutes > 0:
        parts.append(f"{minutes}м")
    if secs > 0 or not parts:
        parts.append(f"{secs}с")

    return " ".join(parts)


def create_progress_bar(percent, width=10):
    """Создает прогресс-бар"""
    filled = int(width * percent / 100)
    empty = width - filled

    if percent >= 90:
        bar = "🟥" * filled + "⬜" * empty
    elif percent >= 70:
        bar = "🟧" * filled + "⬜" * empty
    elif percent >= 50:
        bar = "🟨" * filled + "⬜" * empty
    else:
        bar = "🟩" * filled + "⬜" * empty

    return bar


def escape_html(text):
    """Экранирование HTML-символов"""
    if text is None:
        return ""
    text = str(text)
    return (text.replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
                .replace('"', '&quot;')
                .replace("'", '&#39;'))


# ==== МОНИТОРИНГ ПРОЦЕССОВ ====
async def monitor_high_resources(context):
    """Мониторит процессы с высоким потреблением ресурсов"""
    try:
        cpu_threshold = float(get_setting('cpu_threshold', '30'))
        ram_threshold = float(get_setting('ram_threshold', '85'))

        high_cpu_processes = []
        high_ram_processes = []

        # Получаем общую RAM для расчета процентов
        total_ram = psutil.virtual_memory().total

        for proc in psutil.process_iter(
            ['pid', 'name', 'cpu_percent', 'memory_info', 'create_time']
        ):
            try:
                cpu_percent = proc.info['cpu_percent'] or 0
                create_time = proc.info['create_time']

                if create_time:
                    process_age = datetime.now().timestamp() - create_time
                    if process_age < 30:
                        continue

                memory_info = proc.info['memory_info']
                if memory_info:
                    memory_mb = memory_info.rss / 1024 / 1024
                    memory_percent = (memory_info.rss / total_ram) * 100
                else:
                    memory_mb = 0
                    memory_percent = 0

                if cpu_percent > cpu_threshold:
                    high_cpu_processes.append({
                        'pid': proc.info['pid'],
                        'name': proc.info['name'][:50] if proc.info['name'] else 'Unknown',
                        'cpu': round(cpu_percent, 1),
                        'memory': round(memory_percent, 1),
                        'memory_mb': round(memory_mb, 1),
                        'age': round(process_age, 0) if create_time else 0
                    })

                if memory_percent > ram_threshold:
                    high_ram_processes.append({
                        'pid': proc.info['pid'],
                        'name': proc.info['name'][:50] if proc.info['name'] else 'Unknown',
                        'cpu': round(cpu_percent, 1),
                        'memory': round(memory_percent, 1),
                        'memory_mb': round(memory_mb, 1),
                        'age': round(process_age, 0) if create_time else 0
                    })

            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                continue

        if high_cpu_processes:
            high_cpu_processes.sort(key=lambda x: x['cpu'], reverse=True)
            save_high_resource_processes(high_cpu_processes, 'cpu')

            for proc in high_cpu_processes[:5]:
                db_execute(
                    "INSERT INTO process_alerts (process_name, pid, cpu_percent, memory_percent, status) VALUES (?, ?, ?, ?, ?)",
                    (proc['name'], proc['pid'], proc['cpu'], proc['memory'], 'high_cpu')
                )

            message = f"⚠️ <b>⚠️ ОБНАРУЖЕНА ВЫСОКАЯ НАГРУЗКА CPU ⚠️</b>\n\n"
            message += f"📊 <b>ПРОЦЕССЫ С ПРЕВЫШЕНИЕМ (&gt;{cpu_threshold}%):</b>\n"
            message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

            for i, proc in enumerate(high_cpu_processes[:5], 1):
                cpu_bar = create_progress_bar(proc['cpu'], 15)
                message += f"<b>{i}. {escape_html(proc['name'])}</b>\n"
                message += f"   📌 PID: <code>{proc['pid']}</code>\n"
                message += f"   💻 CPU: {cpu_bar} {proc['cpu']}%\n"
                message += f"   💾 RAM: {proc['memory']}% ({proc['memory_mb']} MB)\n"
                if proc['age'] > 0:
                    message += f"   ⏱️  Время работы: {format_uptime(proc['age'])}\n"
                message += "\n"

            if len(high_cpu_processes) > 5:
                message += f"<i>... и ещё {len(high_cpu_processes) - 5} процессов</i>\n\n"

            message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            message += "💡 <b>Что делать?</b>\n"
            message += "• Проверьте логи: <code>journalctl -xe</code>\n"
            message += "• Перезапустите проблемные процессы\n"
            message += "• Увеличьте ресурсы сервера при необходимости\n"
            message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

            await send_alert(context, message, 'cpu')

        if high_ram_processes:
            high_ram_processes.sort(key=lambda x: x['memory'], reverse=True)
            save_high_resource_processes(high_ram_processes, 'ram')

            message = f"⚠️ <b>⚠️ ОБНАРУЖЕНА ВЫСОКАЯ НАГРУЗКА RAM ⚠️</b>\n\n"
            message += f"📊 <b>ПРОЦЕССЫ С ПРЕВЫШЕНИЕМ (&gt;{ram_threshold}%):</b>\n"
            message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

            for i, proc in enumerate(high_ram_processes[:5], 1):
                mem_bar = create_progress_bar(proc['memory'], 15)
                message += f"<b>{i}. {escape_html(proc['name'])}</b>\n"
                message += f"   📌 PID: <code>{proc['pid']}</code>\n"
                message += f"   💾 RAM: {mem_bar} {proc['memory']}% ({proc['memory_mb']} MB)\n"
                message += f"   💻 CPU: {proc['cpu']}%\n"
                if proc['age'] > 0:
                    message += f"   ⏱️  Время работы: {format_uptime(proc['age'])}\n"
                message += "\n"

            if len(high_ram_processes) > 5:
                message += f"<i>... и ещё {len(high_ram_processes) - 5} процессов</i>\n\n"

            message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            message += "💡 <b>Что делать?</b>\n"
            message += "• Проверьте утечки памяти: <code>top</code>\n"
            message += "• Перезапустите проблемные сервисы\n"
            message += "• Добавьте swap при необходимости\n"
            message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

            await send_alert(context, message, 'ram')

    except Exception as e:
        print(f"Ошибка мониторинга ресурсов: {e}")


async def monitor_disk_and_network(context):
    """Мониторинг диска и сети"""
    try:
        disk_threshold = float(get_setting('disk_threshold', '85'))
        net_sent_threshold = float(get_setting('net_sent_threshold', '100'))
        net_recv_threshold = float(get_setting('net_recv_threshold', '100'))

        alerts = []

        disk = psutil.disk_usage('/')
        if disk.percent > disk_threshold:
            disk_bar = create_progress_bar(disk.percent, 15)
            message = (
                f"💿 <b>⚠️ ВЫСОКАЯ ЗАГРУЗКА ДИСКА ⚠️</b>\n\n"
                f"{disk_bar} {disk.percent}%\n\n"
                f"📊 <b>Статистика:</b>\n"
                f"• Всего: {format_size(disk.total)}\n"
                f"• Использовано: {format_size(disk.used)}\n"
                f"• Свободно: {format_size(disk.free)}\n\n"
                f"💡 <b>Что делать?</b>\n"
                f"1. Очистите временные файлы: <code>sudo apt autoremove</code>\n"
                f"2. Проверьте большие файлы: <code>du -sh /* 2&gt;/dev/null | sort -rh | head -10</code>\n"
                f"3. Архивируйте старые логи: <code>sudo logrotate -f /etc/logrotate.conf</code>\n"
                f"4. Увеличьте размер диска в панели управления VPS"
            )
            alerts.append({'type': 'disk', 'message': message})

        net = psutil.net_io_counters()
        last_net = context.bot_data.get('last_net_stats', {})

        if last_net:
            time_diff = datetime.now().timestamp() - last_net.get('timestamp', datetime.now().timestamp())
            if time_diff > 0:
                sent_speed = (
                    (net.bytes_sent - last_net.get('bytes_sent', net.bytes_sent)) /
                    time_diff / 1024 / 1024
                )
                recv_speed = (
                    (net.bytes_recv - last_net.get('bytes_recv', net.bytes_recv)) /
                    time_diff / 1024 / 1024
                )

                if sent_speed > net_sent_threshold:
                    message = (
                        f"📤 <b>⚠️ ВЫСОКИЙ ИСХОДЯЩИЙ ТРАФИК ⚠️</b>\n\n"
                        f"📊 <b>Статистика:</b>\n"
                        f"• Скорость отправки: {sent_speed:.2f} MB/s\n"
                        f"• Порог: {net_sent_threshold} MB/s\n\n"
                        f"💡 <b>Что делать?</b>\n"
                        f"1. Проверьте активные соединения: <code>netstat -tunapl</code>\n"
                        f"2. Проверьте процессы: <code>nethogs</code>\n"
                        f"3. Возможно DDoS-атака - проверьте fail2ban\n"
                        f"4. Ограничьте скорость через tc"
                    )
                    alerts.append({'type': 'network', 'message': message})

                if recv_speed > net_recv_threshold:
                    message = (
                        f"📥 <b>⚠️ ВЫСОКИЙ ВХОДЯЩИЙ ТРАФИК ⚠️</b>\n\n"
                        f"📊 <b>Статистика:</b>\n"
                        f"• Скорость приема: {recv_speed:.2f} MB/s\n"
                        f"• Порог: {net_recv_threshold} MB/s\n\n"
                        f"💡 <b>Что делать?</b>\n"
                        f"1. Проверьте загрузки/обновления\n"
                        f"2. Возможно скачивание больших файлов\n"
                        f"3. Проверьте торренты если есть\n"
                        f"4. Может быть DDoS - проверьте логи"
                    )
                    alerts.append({'type': 'network', 'message': message})

        context.bot_data['last_net_stats'] = {
            'timestamp': datetime.now().timestamp(),
            'bytes_sent': net.bytes_sent,
            'bytes_recv': net.bytes_recv
        }

        for alert in alerts:
            await send_alert(context, alert['message'], alert['type'])

    except Exception as e:
        print(f"Ошибка мониторинга диска/сети: {e}")


async def monitor_fail2ban(context):
    """Мониторинг логов fail2ban"""
    if get_setting('enable_fail2ban_alerts', 'false') != 'true':
        return

    try:
        if not os.path.exists(FAIL2BAN_LOG_PATH):
            print(f"Файл {FAIL2BAN_LOG_PATH} не существует")
            return

        if not os.access(FAIL2BAN_LOG_PATH, os.R_OK):
            print(f"Нет прав на чтение {FAIL2BAN_LOG_PATH}")
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "⚠️ <b>Проблема с мониторингом fail2ban</b>\n\n"
                    f"📁 Файл: {FAIL2BAN_LOG_PATH}\n"
                    f"🔒 Ошибка: Нет прав на чтение\n\n"
                    f"💡 <b>Решение:</b>\n"
                    f"<code>sudo chmod 644 /var/log/fail2ban.log</code>\n"
                    f"<code>sudo chown root:adm /var/log/fail2ban.log</code>\n\n"
                    f"Или отключите fail2ban в настройках."
                ),
                parse_mode='HTML'
            )
            return

        last_position = context.bot_data.get('fail2ban_last_position', 0)
        current_size = os.path.getsize(FAIL2BAN_LOG_PATH)

        if current_size < last_position:
            last_position = 0

        with open(FAIL2BAN_LOG_PATH, 'r') as f:
            f.seek(last_position)
            new_lines = f.readlines()
            context.bot_data['fail2ban_last_position'] = f.tell()

        ban_pattern = r'\[([^\]]+)\] (?:INFO|WARNING) \[([^\]]+)\] (Ban|Unban) ([\d\.]+)'

        for line in new_lines:
            match = re.search(ban_pattern, line)
            if match:
                timestamp, jail, action, ip = match.groups()

                whois_info = await get_ip_info(ip)

                action_emoji = "🔒" if action == "Ban" else "🔓"
                action_text = "ЗАБЛОКИРОВАН" if action == "Ban" else "РАЗБЛОКИРОВАН"

                message = (
                    f"{action_emoji} <b>FAIL2BAN: IP {action_text}</b>\n\n"
                    f"🕐 <b>Время:</b> {timestamp}\n"
                    f"🔒 <b>Jail:</b> <code>{jail}</code>\n"
                    f"🌍 <b>IP адрес:</b> <code>{ip}</code>\n"
                    f"📍 <b>Страна:</b> {escape_html(whois_info.get('country', 'N/A'))}\n"
                    f"🏢 <b>Провайдер:</b> {escape_html(whois_info.get('org', 'N/A'))}\n"
                )

                if action == "Ban":
                    message += (
                        f"\n💡 <b>Информация:</b> IP заблокирован на 10 минут\n"
                        f"📝 <b>Проверить:</b> <code>sudo fail2ban-client status {jail}</code>"
                    )

                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=message,
                    parse_mode='HTML'
                )

    except PermissionError:
        print(f"Permission denied: {FAIL2BAN_LOG_PATH}")
    except Exception as e:
        print(f"Ошибка мониторинга fail2ban: {e}")


async def monitor_directories(context):
    """Мониторинг директорий (пункт 10)"""
    if get_setting('enable_directory_monitor', 'false') != 'true':
        return

    try:
        directories = db_execute(
            "SELECT id, path, threshold_mb, last_notify FROM directory_monitor",
            fetch=True
        )
        today = datetime.now().date().strftime('%Y-%m-%d')

        for dir_id, path, threshold_mb, last_notify in directories:
            if not os.path.exists(path):
                continue

            result = subprocess.run(['du', '-sb', path], capture_output=True, text=True)
            size_bytes = int(result.stdout.split()[0])
            size_mb = size_bytes / 1024 / 1024

            if size_mb > threshold_mb and last_notify != today:
                large_files = subprocess.run(
                    ['find', path, '-type', 'f', '-printf', '%s %p\n', '2>/dev/null'],
                    capture_output=True, text=True, shell=True
                )
                files = []
                for line in large_files.stdout.split('\n')[:10]:
                    if line:
                        parts = line.split(' ', 1)
                        if len(parts) == 2:
                            file_size = int(parts[0]) / 1024 / 1024
                            files.append(f"• {escape_html(parts[1])}: {file_size:.1f} MB")

                fill_percent = min(100, int((size_mb / threshold_mb) * 100))
                bar = create_progress_bar(fill_percent, 20)

                message = (
                    f"📁 <b>⚠️ ДИРЕКТОРИЯ ПРЕВЫСИЛА ПОРОГ ⚠️</b>\n\n"
                    f"📂 <b>Путь:</b> <code>{escape_html(path)}</code>\n"
                    f"{bar} {fill_percent}%\n\n"
                    f"📊 <b>Статистика:</b>\n"
                    f"• Текущий размер: {size_mb:.1f} MB\n"
                    f"• Порог: {threshold_mb} MB\n"
                    f"• Превышение: +{size_mb - threshold_mb:.1f} MB\n\n"
                )

                if files:
                    message += (
                        f"📋 <b>Самые большие файлы (топ-{min(10, len(files))}):</b>\n"
                        f"{chr(10).join(files[:10])}\n\n"
                    )

                message += (
                    f"💡 <b>Что делать?</b>\n"
                    f"1. Архивируйте старые файлы: <code>tar -czf archive.tar.gz {path}</code>\n"
                    f"2. Удалите временные файлы: <code>find {path} -type f -atime +30 -delete</code>\n"
                    f"3. Настройте logrotate для логов\n"
                    f"4. Перенесите данные на другой диск"
                )

                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=message,
                    parse_mode='HTML'
                )

                db_execute(
                    "UPDATE directory_monitor SET last_notify=? WHERE id=?",
                    (today, dir_id)
                )

    except Exception as e:
        print(f"Ошибка мониторинга директорий: {e}")


async def monitor_docker_containers(context):
    """Мониторинг Docker контейнеров (пункт 11)"""
    if get_setting('enable_docker_monitor', 'false') != 'true':
        return

    try:
        containers = db_execute(
            "SELECT id, container_name, cpu_threshold, memory_threshold, enabled, last_notify "
            "FROM docker_monitor WHERE enabled=1",
            fetch=True
        )
        today = datetime.now().date().strftime('%Y-%m-%d')

        for cont_id, name, cpu_threshold, mem_threshold, enabled, last_notify in containers:
            stats_cmd = (
                f"docker stats --no-stream --format "
                f"'{{{{.CPUPerc}}}},{{{{.MemPerc}}}},{{{{.MemUsage}}}}' {name} 2>/dev/null"
            )
            out, err = await run_cmd(stats_cmd)

            if err or not out:
                continue

            try:
                parts = out.strip().split(',')
                cpu_str = parts[0]
                mem_str = parts[1]

                cpu_percent = float(cpu_str.strip('%'))
                mem_percent = float(mem_str.strip('%'))

                alerts = []
                if cpu_percent > cpu_threshold:
                    cpu_bar = create_progress_bar(cpu_percent, 15)
                    alerts.append(
                        f"💻 CPU: {cpu_bar} {cpu_percent}% (порог {cpu_threshold}%)"
                    )
                if mem_percent > mem_threshold:
                    mem_bar = create_progress_bar(mem_percent, 15)
                    alerts.append(
                        f"💾 RAM: {mem_bar} {mem_percent}% (порог {mem_threshold}%)"
                    )

                if alerts and last_notify != today:
                    inspect_cmd = (
                        f"docker inspect {name} --format "
                        f"'{{{{.State.Status}}}},{{{{.State.StartedAt}}}},{{{{.HostConfig.RestartPolicy.Name}}}}'"
                    )
                    out, _ = await run_cmd(inspect_cmd)
                    parts = out.strip().split(',') if ',' in out else ['unknown', '', 'no']
                    status = parts[0]
                    started = parts[1] if len(parts) > 1 else ''
                    restart_policy = parts[2] if len(parts) > 2 else 'no'

                    uptime_str = 'N/A'
                    if started:
                        try:
                            started_time = datetime.fromisoformat(started.replace('Z', '+00:00'))
                            uptime = datetime.now(started_time.tzinfo) - started_time
                            uptime_str = format_uptime(uptime.total_seconds())
                        except Exception:
                            pass

                    status_emoji = {
                        'running': '✅',
                        'exited': '❌',
                        'paused': '⏸️',
                        'restarting': '🔄',
                        'dead': '💀'
                    }.get(status, '❓')

                    message = (
                        f"🐳 <b>⚠️ КОНТЕЙНЕР {escape_html(name.upper())} ПРЕВЫСИЛ ЛИМИТЫ ⚠️</b>\n\n"
                        f"📊 <b>Превышения:</b>\n" + "\n".join([f"{a}" for a in alerts]) + "\n\n"
                        f"📈 <b>Состояние:</b> {status_emoji} {status}\n"
                        f"⏱️ <b>Uptime:</b> {uptime_str}\n"
                        f"🔄 <b>Restart policy:</b> {restart_policy}\n\n"
                        f"💡 <b>Что делать?</b>\n"
                        f"1. Проверьте логи: <code>docker logs --tail 50 {name}</code>\n"
                        f"2. Перезапустите: <code>docker restart {name}</code>\n"
                        f"3. Увеличьте лимиты в docker-compose.yml\n"
                        f"4. Проверьте утечки памяти в контейнере"
                    )

                    await context.bot.send_message(
                        chat_id=ADMIN_ID,
                        text=message,
                        parse_mode='HTML'
                    )

                    db_execute(
                        "UPDATE docker_monitor SET last_notify=? WHERE id=?",
                        (today, cont_id)
                    )

            except (ValueError, AttributeError, IndexError) as e:
                print(f"Ошибка парсинга данных Docker для {name}: {e}")
                continue

    except Exception as e:
        print(f"Ошибка мониторинга Docker: {e}")


async def send_alert(context, message, alert_type):
    """Отправка уведомления с кнопками"""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Подробнее о сервере", callback_data='about_server')],
        [InlineKeyboardButton("📋 История процессов", callback_data='process_history_cpu')],
        [InlineKeyboardButton("⚙️ Настройки", callback_data='settings_menu')],
        [InlineKeyboardButton("❓ Помощь", callback_data='help')]
    ])

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=message,
        reply_markup=keyboard,
        parse_mode='HTML'
    )


async def get_ip_info(ip):
    """Получение информации об IP адресе"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f'http://ip-api.com/json/{ip}', timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {
                        'country': data.get('country', 'N/A'),
                        'city': data.get('city', 'N/A'),
                        'org': data.get('org', 'N/A'),
                        'isp': data.get('isp', 'N/A'),
                        'as': data.get('as', 'N/A')
                    }
    except Exception:
        pass
    return {}


# ==== УТИЛИТЫ ====
async def run_cmd(cmd):
    """Выполнение shell команд асинхронно"""
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        executable='/bin/bash'
    )
    out, err = await proc.communicate()
    return out.decode('utf-8', errors='ignore'), err.decode('utf-8', errors='ignore')


def is_admin(update):
    """Проверка прав администратора"""
    return str(update.effective_user.id) == ADMIN_ID


def menu_keyboard():
    """Главное меню с кнопками"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Статус", callback_data='status'),
         InlineKeyboardButton("🔄 Обновить", callback_data='updates')],
        [InlineKeyboardButton("🔄 Перезагрузка", callback_data='reboot'),
         InlineKeyboardButton("🏓 Ping", callback_data='ping_menu')],
        [InlineKeyboardButton("🔐 Пароль", callback_data='pass_menu'),
         InlineKeyboardButton("📋 VPS", callback_data='vps_menu')],
        [InlineKeyboardButton("ℹ️ Информация", callback_data='info_menu'),
         InlineKeyboardButton("⚙️ Настройки", callback_data='settings_menu')],
        [InlineKeyboardButton("❓ Помощь", callback_data='help')]
    ])


def info_menu_keyboard():
    """Подменю информации"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🖥️ О сервере", callback_data='about_server'),
         InlineKeyboardButton("🤖 О боте", callback_data='about_bot')],
        [InlineKeyboardButton("📊 Системная диагностика", callback_data='system_diagnostic')],
        [InlineKeyboardButton("◀️ Назад", callback_data='menu')]
    ])


def settings_menu_keyboard():
    """Подменю настроек"""
    settings = get_all_settings()

    cpu = settings.get('cpu_threshold', '30')
    ram = settings.get('ram_threshold', '85')
    disk = settings.get('disk_threshold', '85')
    net_sent = settings.get('net_sent_threshold', '100')
    net_recv = settings.get('net_recv_threshold', '100')
    interval = settings.get('monitor_interval', '30')
    daily_report = settings.get('enable_daily_report', 'false')
    fail2ban = settings.get('enable_fail2ban_alerts', 'false')
    dir_monitor = settings.get('enable_directory_monitor', 'false')
    docker_monitor = settings.get('enable_docker_monitor', 'false')
    compact_mode = settings.get('compact_mode', 'false')

    report_status = "✅ Вкл" if daily_report == 'true' else "❌ Выкл"
    fail2ban_status = "✅ Вкл" if fail2ban == 'true' else "❌ Выкл"
    dir_status = "✅ Вкл" if dir_monitor == 'true' else "❌ Выкл"
    docker_status = "✅ Вкл" if docker_monitor == 'true' else "❌ Выкл"
    compact_status = "✅ Вкл" if compact_mode == 'true' else "❌ Выкл"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔔 CPU порог (сейчас {cpu}%)", callback_data='set_cpu_threshold')],
        [InlineKeyboardButton(f"💾 RAM порог (сейчас {ram}%)", callback_data='set_ram_threshold')],
        [InlineKeyboardButton(f"💿 Диск порог (сейчас {disk}%)", callback_data='set_disk_threshold')],
        [InlineKeyboardButton(f"📤 Исх. трафик (сейчас {net_sent} MB/s)", callback_data='set_net_sent')],
        [InlineKeyboardButton(f"📥 Вх. трафик (сейчас {net_recv} MB/s)", callback_data='set_net_recv')],
        [InlineKeyboardButton(f"⏱️ Интервал (сейчас {interval}с)", callback_data='set_interval')],
        [InlineKeyboardButton(f"📊 Ежедневный отчет ({report_status})", callback_data='toggle_daily_report')],
        [InlineKeyboardButton(f"📝 Компактный режим ({compact_status})", callback_data='toggle_compact_mode')],
        [InlineKeyboardButton(f"🚫 Fail2ban ({fail2ban_status})", callback_data='toggle_fail2ban')],
        [InlineKeyboardButton(f"📁 Мониторинг папок ({dir_status})", callback_data='directory_monitor_menu')],
        [InlineKeyboardButton(f"🐳 Мониторинг Docker ({docker_status})", callback_data='docker_monitor_menu')],
        [InlineKeyboardButton("◀️ Назад", callback_data='menu')]
    ])


def directory_monitor_keyboard():
    """Клавиатура для мониторинга директорий"""
    dirs = db_execute("SELECT id, path, threshold_mb FROM directory_monitor", fetch=True)
    keyboard = []

    for dir_id, path, threshold in dirs:
        keyboard.append([
            InlineKeyboardButton(
                f"📁 {escape_html(path)} ({threshold} MB)",
                callback_data=f'edit_dir_{dir_id}'
            )
        ])

    keyboard.append([InlineKeyboardButton("➕ Добавить папку", callback_data='add_directory')])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data='settings_menu')])

    return InlineKeyboardMarkup(keyboard)


def docker_monitor_keyboard():
    """Клавиатура для мониторинга Docker"""
    containers = db_execute(
        "SELECT id, container_name, cpu_threshold, memory_threshold, enabled FROM docker_monitor",
        fetch=True
    )
    keyboard = []

    for cont_id, name, cpu, mem, enabled in containers:
        status = "✅" if enabled else "❌"
        keyboard.append([
            InlineKeyboardButton(
                f"{status} {escape_html(name)} (CPU:{cpu}% RAM:{mem}%)",
                callback_data=f'edit_docker_{cont_id}'
            )
        ])

    out, _ = run_cmd_sync("docker ps --format '{{.Names}}' 2>/dev/null")
    if out:
        for container in out.strip().split('\n'):
            if container:
                exists = db_execute(
                    "SELECT id FROM docker_monitor WHERE container_name=?",
                    (container,),
                    fetch=True
                )
                if not exists:
                    keyboard.append([
                        InlineKeyboardButton(
                            f"➕ Добавить {escape_html(container)}",
                            callback_data=f'add_docker_{container}'
                        )
                    ])

    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data='settings_menu')])

    return InlineKeyboardMarkup(keyboard)


def run_cmd_sync(cmd):
    """Синхронное выполнение команд"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        return result.stdout, result.stderr
    except Exception:
        return "", ""


def back_btn(callback='menu'):
    """Кнопка назад"""
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data=callback)]])


# ==== ПРОВЕРКА ОБНОВЛЕНИЙ БОТА С GITHUB ====
async def check_bot_version():
    """Проверяет последнюю версию бота на GitHub"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(GITHUB_RAW_VERSION_URL, timeout=5) as resp:
                if resp.status == 200:
                    remote_version = (await resp.text()).strip()
                    if remote_version != BOT_VERSION:
                        changelog = (
                            "Что нового:\n"
                            "• Улучшенное форматирование отчетов\n"
                            "• Прогресс-бары для нагрузки\n"
                            "• Подробные инструкции по действиям\n"
                            "• Компактный режим отображения"
                        )
                        return remote_version, (
                            f"🔔 <b>Доступно обновление!</b>\n\n"
                            f"Текущая версия: {BOT_VERSION}\n"
                            f"Новая версия: {remote_version}\n\n"
                            f"{changelog}\n\n"
                            f"Скачать: {GITHUB_RELEASES_URL}"
                        )
                    else:
                        return None, f"✅ <b>У вас актуальная версия</b> {BOT_VERSION}"
                else:
                    return None, f"❌ Не удалось проверить обновления (код {resp.status})"
    except aiohttp.ClientError as e:
        return None, f"❌ Ошибка соединения с GitHub: {e}"
    except Exception as e:
        return None, f"❌ Ошибка при проверке обновлений: {e}"


# ==== СИСТЕМНАЯ ДИАГНОСТИКА ====
async def get_system_diagnostic():
    """Собирает подробную диагностику системы"""
    try:
        compact_mode = get_setting('compact_mode', 'false') == 'true'

        if compact_mode:
            result = "🔍 <b>СИСТЕМНАЯ ДИАГНОСТИКА (КОМПАКТНАЯ)</b>\n"
        else:
            result = "🔍 <b>🔍 СИСТЕМНАЯ ДИАГНОСТИКА 🔍</b>\n"

        result += f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
        result += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

        if not compact_mode:
            result += (
                "💡 <b>Инструкция:</b> Эта диагностика показывает текущее состояние сервера.\n"
                "Красные 🔴 значения требуют внимания, желтые 🟡 - скоро потребуют.\n\n"
            )

        load_avg = psutil.getloadavg()
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_bar = create_progress_bar(cpu_percent, 20)

        result += "📊 <b>ЗАГРУЗКА СИСТЕМЫ:</b>\n"
        result += f"💻 CPU: {cpu_bar} {cpu_percent}%\n"
        result += f"📈 Load average: {load_avg[0]:.2f}, {load_avg[1]:.2f}, {load_avg[2]:.2f}\n\n"

        mem = psutil.virtual_memory()
        mem_bar = create_progress_bar(mem.percent, 20)
        swap = psutil.swap_memory()

        result += "💾 <b>ПАМЯТЬ:</b>\n"
        result += f"RAM: {mem_bar} {mem.percent}%\n"
        result += (
            f"📊 Всего: {format_size(mem.total)}, "
            f"Использовано: {format_size(mem.used)}, "
            f"Свободно: {format_size(mem.available)}\n"
        )

        if swap.total > 0:
            swap_bar = create_progress_bar(swap.percent, 20)
            result += f"Swap: {swap_bar} {swap.percent}%\n"
            result += f"📊 Всего: {format_size(swap.total)}, Использовано: {format_size(swap.used)}\n"
        result += "\n"

        result += "💿 <b>ДИСКИ:</b>\n"
        for part in psutil.disk_partitions():
            if part.fstype:
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    disk_bar = create_progress_bar(usage.percent, 20)
                    result += f"📁 {part.mountpoint} ({part.fstype}):\n"
                    result += f"{disk_bar} {usage.percent}%\n"
                    result += (
                        f"📊 Всего: {format_size(usage.total)}, "
                        f"Использовано: {format_size(usage.used)}, "
                        f"Свободно: {format_size(usage.free)}\n\n"
                    )
                except Exception:
                    continue

        if not compact_mode:
            result += "📁 <b>ТОП-5 ПАПОК В /:</b>\n"
            out, _ = await run_cmd(
                "sudo du -sh /* 2>/dev/null | grep -E '^[0-9.]+[GM]' | sort -rh | head -5"
            )
            if out.strip():
                for line in out.strip().split('\n')[:5]:
                    if line:
                        result += f"<code>{escape_html(line)}</code>\n"
            else:
                result += "<i>Нет данных или недостаточно прав</i>\n"
            result += "\n"

        result += "🐳 <b>DOCKER КОНТЕЙНЕРЫ:</b>\n"
        out, err = await run_cmd(
            "sudo docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Size}}' 2>/dev/null | head -10"
        )
        if out and "CONTAINER" not in err:
            lines = out.strip().split('\n')
            for i, line in enumerate(lines):
                if i < (3 if compact_mode else 8):
                    if i == 0:
                        result += f"<code>{escape_html(line)}</code>\n"
                    else:
                        if "Up" in line:
                            line = "✅ " + line
                        elif "Exited" in line:
                            line = "❌ " + line
                        else:
                            line = "🔄 " + line
                        result += f"<code>{escape_html(line[:100])}</code>\n"
            if len(lines) > (3 if compact_mode else 8):
                result += (
                    f"<i>... и ещё {len(lines) - (3 if compact_mode else 8)} контейнеров</i>\n"
                )
        else:
            result += "Docker контейнеров нет или Docker не установлен\n"
        result += "\n"

        if not compact_mode:
            result += "🔥 <b>ТОП-5 ПРОЦЕССОВ ПО CPU:</b>\n"
            out, _ = await run_cmd("ps aux --sort=-%cpu | head -6")
            if out.strip():
                lines = out.strip().split('\n')
                for i, line in enumerate(lines):
                    if i == 0:
                        result += f"<code>{escape_html(line[:100])}</code>\n"
                    else:
                        parts = line.split()
                        if len(parts) > 10:
                            cpu = parts[2]
                            cmd = ' '.join(parts[10:])[:40]
                            cpu_bar = create_progress_bar(float(cpu), 10)
                            result += f"<code>{cpu_bar} {cpu}% {escape_html(cmd)}</code>\n"
            result += "\n"

            result += "💾 <b>ТОП-5 ПРОЦЕССОВ ПО RAM:</b>\n"
            out, _ = await run_cmd("ps aux --sort=-%mem | head -6")
            if out.strip():
                lines = out.strip().split('\n')
                for i, line in enumerate(lines):
                    if i == 0:
                        result += f"<code>{escape_html(line[:100])}</code>\n"
                    else:
                        parts = line.split()
                        if len(parts) > 10:
                            mem = parts[3]
                            cmd = ' '.join(parts[10:])[:40]
                            mem_bar = create_progress_bar(float(mem), 10)
                            result += f"<code>{mem_bar} {mem}% {escape_html(cmd)}</code>\n"

        result += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"

        if compact_mode:
            result += "💡 Для подробной диагностики отключите компактный режим в настройках"
        else:
            result += "💡 <b>Рекомендации:</b>\n"
            if cpu_percent > 80:
                result += "• 🔴 Высокая нагрузка CPU – проверьте процессы выше\n"
            if mem.percent > 85:
                result += "• 🔴 Мало свободной RAM – закройте приложения или добавьте swap\n"
            disk_usage = psutil.disk_usage('/')
            if disk_usage.percent > 85:
                result += "• 🔴 Мало места на диске – очистите временные файлы\n"

        return result

    except Exception as e:
        return f"❌ Ошибка при сборе диагностики: {escape_html(str(e))}"


# ==== ОСНОВНЫЕ ФУНКЦИИ ====
async def get_server_info():
    """Подробная информация о сервере"""
    try:
        compact_mode = get_setting('compact_mode', 'false') == 'true'

        cpu_info = {}
        try:
            with open('/proc/cpuinfo', 'r') as f:
                for line in f:
                    if 'model name' in line:
                        cpu_info['model'] = line.split(':')[1].strip()
                        break
        except Exception:
            cpu_info['model'] = platform.processor() or 'Неизвестно'

        cpu_freq = psutil.cpu_freq()
        cpu_count_phys = psutil.cpu_count(logical=False)
        cpu_count_log = psutil.cpu_count(logical=True)
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_bar = create_progress_bar(cpu_percent, 20)

        mem = psutil.virtual_memory()
        mem_bar = create_progress_bar(mem.percent, 20)
        swap = psutil.swap_memory()

        disks = []
        for part in psutil.disk_partitions():
            if part.fstype:
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    disks.append({
                        'device': part.device,
                        'mount': part.mountpoint,
                        'fstype': part.fstype,
                        'total': usage.total / (1024 ** 3),
                        'used': usage.used / (1024 ** 3),
                        'free': usage.free / (1024 ** 3),
                        'percent': usage.percent
                    })
                except Exception:
                    continue

        net = psutil.net_io_counters()
        net_connections = len(psutil.net_connections())

        boot_time = datetime.fromtimestamp(psutil.boot_time())
        uptime_seconds = (datetime.now() - boot_time).total_seconds()
        uptime_str = format_uptime(uptime_seconds)
        users = len(psutil.users())
        load_avg = psutil.getloadavg()

        if compact_mode:
            text = f"🖥️ <b>{escape_html(config.SERVER_NAME)}</b>\n"
            text += "━━━━━━━━━━━━━━━━━━━━\n\n"
            text += f"💻 CPU: {cpu_bar} {cpu_percent}%\n"
            text += f"💾 RAM: {mem_bar} {mem.percent}%\n"
            text += f"⏱️  Uptime: {uptime_str}\n"
            text += f"📊 Load: {load_avg[0]:.2f}, {load_avg[1]:.2f}, {load_avg[2]:.2f}\n"
            text += f"🌐 Сеть: ↑{net.bytes_sent / 1e9:.2f}GB ↓{net.bytes_recv / 1e9:.2f}GB\n"
            text += f"👥 Пользователей: {users}\n"
        else:
            text = f"🖥️ <b>🔍 ПОДРОБНАЯ ИНФОРМАЦИЯ О СЕРВЕРЕ 🔍</b>\n"
            text += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

            text += f"<b>💻 ПРОЦЕССОР:</b>\n"
            text += f"• Модель: {escape_html(cpu_info['model'][:60])}\n"
            text += f"• Ядер: {cpu_count_phys} физических, {cpu_count_log} логических\n"
            if cpu_freq:
                text += f"• Частота: {cpu_freq.current:.0f} МГц"
                if cpu_freq.min:
                    text += f" (мин: {cpu_freq.min:.0f}, макс: {cpu_freq.max:.0f})"
                text += f"\n"
            text += f"• Загрузка: {cpu_bar} {cpu_percent}%\n"
            text += f"• Load average: {load_avg[0]:.2f}, {load_avg[1]:.2f}, {load_avg[2]:.2f}\n\n"

            text += f"<b>💾 ПАМЯТЬ:</b>\n"
            text += f"• RAM: {mem_bar} {mem.percent}%\n"
            text += (
                f"  Всего: {format_size(mem.total)}, "
                f"Использовано: {format_size(mem.used)}, "
                f"Свободно: {format_size(mem.available)}\n"
            )
            if swap.total > 0:
                swap_bar = create_progress_bar(swap.percent, 20)
                text += f"• Swap: {swap_bar} {swap.percent}%\n"
                text += f"  Всего: {format_size(swap.total)}, Использовано: {format_size(swap.used)}\n"
            text += "\n"

            text += f"<b>💿 ДИСКИ:</b>\n"
            for disk in disks:
                disk_bar = create_progress_bar(disk['percent'], 20)
                text += f"• {disk['device']} ({disk['mount']}):\n"
                text += f"  {disk_bar} {disk['percent']}%\n"
                text += (
                    f"  Всего: {disk['total']:.1f}GB, "
                    f"Использовано: {disk['used']:.1f}GB, "
                    f"Свободно: {disk['free']:.1f}GB\n"
                )
                text += f"  ФС: {disk['fstype']}\n"

            text += f"\n<b>🌐 СЕТЬ:</b>\n"
            text += f"• Отправлено: {format_size(net.bytes_sent)}\n"
            text += f"• Получено: {format_size(net.bytes_recv)}\n"
            text += f"• Активных соединений: {net_connections}\n\n"

            text += f"<b>⚙️ СИСТЕМА:</b>\n"
            text += f"• Хост: {escape_html(platform.node())}\n"
            text += f"• ОС: {escape_html(platform.system())} {escape_html(platform.release())}\n"
            text += f"• Архитектура: {escape_html(platform.machine())}\n"
            text += f"• Uptime: {uptime_str}\n"
            text += f"• Пользователей онлайн: {users}\n"
            text += f"• Процессов: {len(psutil.pids())}\n"

        return text
    except Exception as e:
        return f"❌ Ошибка получения информации: {escape_html(str(e))}"


async def get_process_history_text(resource_type='cpu', limit=10):
    """Получает историю процессов"""
    history = get_high_resource_history(resource_type, limit)

    if not history:
        return f"📭 История процессов с высокой нагрузкой {resource_type.upper()} отсутствует."

    resource_names = {'cpu': 'CPU', 'ram': 'RAM'}
    resource_name = resource_names.get(resource_type, resource_type.upper())

    text = (
        f"📋 <b>ИСТОРИЯ ВЫСОКОЙ НАГРУЗКИ {resource_name} "
        f"(последние {limit} записей)</b>\n"
    )
    text += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    for i, entry in enumerate(reversed(history), 1):
        timestamp = datetime.fromisoformat(entry['timestamp']).strftime('%d.%m.%Y %H:%M:%S')
        text += f"<b>{i}. {timestamp}</b>\n"

        for proc in entry['processes'][:5]:
            text += (
                f"   • {escape_html(proc['name'][:30])} "
                f"(PID: {proc['pid']}) - "
            )
            if resource_type == 'cpu':
                text += f"CPU: {proc['cpu']}%, RAM: {proc.get('memory', 0)}%\n"
            else:
                text += f"RAM: {proc.get('memory', 0)}% ({proc.get('memory_mb', 0)} MB)\n"

        if len(entry['processes']) > 5:
            text += f"   <i>... и ещё {len(entry['processes']) - 5} процессов</i>\n"
        text += "\n"

    return text


async def get_status():
    """Быстрый статус сервера"""
    try:
        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        net = psutil.net_io_counters()
        uptime = datetime.now() - datetime.fromtimestamp(psutil.boot_time())
        uptime_str = format_uptime(uptime.total_seconds())

        cpu_bar = create_progress_bar(cpu, 15)
        mem_bar = create_progress_bar(mem.percent, 15)
        disk_bar = create_progress_bar(disk.percent, 15)

        return (
            f"🖥️ <b>{escape_html(config.SERVER_NAME)}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"⏱️  <b>Аптайм:</b> {uptime_str}\n\n"
            f"💻 <b>CPU:</b>\n{cpu_bar} {cpu}% ({psutil.cpu_count()} ядер)\n\n"
            f"💾 <b>RAM:</b>\n{mem_bar} {mem.percent}%\n"
            f"📊 {format_size(mem.used)} / {format_size(mem.total)}\n\n"
            f"💿 <b>Диск:</b>\n{disk_bar} {disk.percent}%\n"
            f"📊 {format_size(disk.used)} / {format_size(disk.total)}\n\n"
            f"🌐 <b>Сеть:</b>\n"
            f"📤 Отправлено: {format_size(net.bytes_sent)}\n"
            f"📥 Получено: {format_size(net.bytes_recv)}"
        )
    except Exception as e:
        return f"❌ Ошибка: {escape_html(str(e))}"


async def check_updates():
    """Проверка доступных обновлений системы"""
    await run_cmd("sudo apt update")
    out, _ = await run_cmd("sudo apt list --upgradable 2>/dev/null | grep -c upgradable")
    count = int(out.strip() or 0)
    packages = []
    if count > 0:
        pkg_out, _ = await run_cmd(
            "sudo apt list --upgradable 2>/dev/null | grep upgradable | head -5 | cut -d'/' -f1"
        )
        packages = pkg_out.strip().split('\n') if pkg_out else []
    return count, packages


async def generate_daily_report():
    """Генерирует ежедневный отчет"""
    try:
        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        net = psutil.net_io_counters()
        uptime = datetime.now() - datetime.fromtimestamp(psutil.boot_time())
        uptime_str = format_uptime(uptime.total_seconds())

        top_cpu = []
        top_ram = []
        for proc in sorted(
            psutil.process_iter(['pid', 'name', 'cpu_percent']),
            key=lambda p: p.info['cpu_percent'] or 0,
            reverse=True
        )[:5]:
            try:
                top_cpu.append(f"• {escape_html(proc.info['name'])}: {proc.info['cpu_percent']}%")
            except Exception:
                continue

        for proc in sorted(
            psutil.process_iter(['pid', 'name', 'memory_percent']),
            key=lambda p: p.info['memory_percent'] or 0,
            reverse=True
        )[:5]:
            try:
                top_ram.append(f"• {escape_html(proc.info['name'])}: {proc.info['memory_percent']}%")
            except Exception:
                continue

        alerts = db_execute(
            "SELECT COUNT(*) FROM process_alerts WHERE timestamp > datetime('now', '-1 day')",
            fetch=True
        )
        alert_count = alerts[0][0] if alerts else 0

        cpu_bar = create_progress_bar(cpu, 20)
        mem_bar = create_progress_bar(mem.percent, 20)
        disk_bar = create_progress_bar(disk.percent, 20)

        report_format = get_setting('report_format', 'detailed')

        if report_format == 'compact':
            report = (
                f"📊 <b>ЕЖЕДНЕВНЫЙ ОТЧЕТ</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📅 {datetime.now().strftime('%d.%m.%Y')}\n"
                f"⏱️ {uptime_str}\n\n"
                f"💻 CPU: {cpu_bar} {cpu}%\n"
                f"💾 RAM: {mem_bar} {mem.percent}%\n"
                f"💿 Диск: {disk_bar} {disk.percent}%\n"
                f"📈 Алертов: {alert_count}"
            )
        else:
            report = (
                f"📊 <b>📊 ЕЖЕДНЕВНЫЙ ОТЧЕТ 📊</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📅 <b>Дата:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
                f"🖥️ <b>Сервер:</b> {escape_html(config.SERVER_NAME)}\n"
                f"⏱️ <b>Аптайм:</b> {uptime_str}\n\n"
                f"<b>📊 ОБЩАЯ СТАТИСТИКА:</b>\n"
                f"💻 <b>CPU:</b>\n{cpu_bar} {cpu}%\n\n"
                f"💾 <b>RAM:</b>\n{mem_bar} {mem.percent}%\n"
                f"📊 Использовано: {format_size(mem.used)} из {format_size(mem.total)}\n\n"
                f"💿 <b>Диск:</b>\n{disk_bar} {disk.percent}%\n"
                f"📊 Использовано: {format_size(disk.used)} из {format_size(disk.total)}\n\n"
                f"🌐 <b>Сеть за все время:</b>\n"
                f"📤 Отправлено: {format_size(net.bytes_sent)}\n"
                f"📥 Получено: {format_size(net.bytes_recv)}\n\n"
                f"<b>🔥 ТОП-5 ПРОЦЕССОВ ПО CPU:</b>\n" +
                "\n".join(top_cpu) + "\n\n"
                f"<b>💾 ТОП-5 ПРОЦЕССОВ ПО RAM:</b>\n" +
                "\n".join(top_ram) + "\n\n"
                f"<b>📈 АКТИВНОСТЬ:</b>\n"
                f"• Алертов за 24 часа: {alert_count}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            )

        return report
    except Exception as e:
        return f"❌ Ошибка генерации отчета: {escape_html(str(e))}"


# ==== ОБРАБОТЧИКИ КОМАНД ====
async def start(update: Update, _):
    """Команда /start - главное меню"""
    if not is_admin(update):
        return

    await update.message.reply_text(
        f"👋 <b>Добро пожаловать, {escape_html(update.effective_user.first_name)}!</b>\n"
        f"🖥️ Сервер: {escape_html(config.SERVER_NAME)}\n\n"
        f"Выберите действие:",
        reply_markup=menu_keyboard(),
        parse_mode='HTML'
    )


async def status_cmd(update: Update, _):
    """Команда /status - быстрый статус сервера"""
    if not is_admin(update):
        return
    msg = await update.message.reply_text("⏳ Получаю статус сервера...")
    await msg.edit_text(await get_status(), reply_markup=back_btn('menu'), parse_mode='HTML')


async def update_cmd(update: Update, _):
    """Команда /update - проверка и установка обновлений"""
    if not is_admin(update):
        return
    msg = await update.message.reply_text("🔄 Проверяю доступные обновления...")
    count, pkgs = await check_updates()
    if count == 0:
        return await msg.edit_text(
            "✅ <b>Система актуальна!</b>\n\nДоступных обновлений не найдено.",
            reply_markup=back_btn('menu'),
            parse_mode='HTML'
        )

    text = f"📦 <b>Доступно обновлений: {count}</b>\n\n"
    if pkgs:
        text += "📋 <b>Некоторые пакеты:</b>\n"
        for pkg in pkgs[:3]:
            text += f"• <code>{escape_html(pkg)}</code>\n"
        if count > 3:
            text += f"• ... и ещё {count - 3}\n"
    text += "\n❓ Установить обновления?"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Да, установить", callback_data='do_update'),
         InlineKeyboardButton("❌ Нет", callback_data='menu')]
    ])
    await msg.edit_text(text, reply_markup=keyboard, parse_mode='HTML')


async def reboot_cmd(update: Update, _):
    """Команда /reboot - перезагрузка сервера"""
    if not is_admin(update):
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Да", callback_data='do_reboot'),
         InlineKeyboardButton("❌ Нет", callback_data='menu')]
    ])
    await update.message.reply_text(
        "⚠️ <b>ВНИМАНИЕ!</b>\n\n"
        "Вы действительно хотите перезагрузить сервер?\n\n"
        "📋 <b>Последствия:</b>\n"
        "• Все соединения будут разорваны\n"
        "• Сервер будет недоступен ~1-2 минуты\n"
        "• Все несохраненные данные будут потеряны\n\n"
        "💡 Рекомендуется сначала проверить статус сервера: /status",
        reply_markup=keyboard,
        parse_mode='HTML'
    )


async def ping_cmd(update: Update, context):
    """Команда /ping - тест ping"""
    if not is_admin(update):
        return

    if not context.args:
        hosts = [
            ("🌍 Google DNS", 'ping_8.8.8.8', "Основной DNS-сервер Google"),
            ("🌐 Cloudflare DNS", 'ping_1.1.1.1', "Быстрый DNS-сервер Cloudflare"),
            ("🏠 Локальный хост", 'ping_127.0.0.1', "Проверка локального сетевого стека"),
            ("🌍 Яндекс", 'ping_yandex.ru', "Проверка доступности российских сервисов"),
            ("📦 GitHub", 'ping_github.com', "Доступ к репозиториям")
        ]

        text = "🏓 <b>ТЕСТ PING</b>\n\n"
        text += "Выберите хост для проверки:\n\n"

        keyboard = []
        for name, cb, desc in hosts:
            keyboard.append([InlineKeyboardButton(name, callback_data=cb)])
            text += f"• {name}: {desc}\n"

        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data='menu')])

        return await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )

    msg = await update.message.reply_text(f"🏓 Пингую {escape_html(context.args[0])}...")
    out, err = await run_cmd(f"ping -c 4 {context.args[0]} 2>&1")

    if err and 'unknown host' in err.lower():
        result = f"❌ Хост <b>{escape_html(context.args[0])}</b> не найден!"
    elif out:
        lines = out.strip().split('\n')
        stats = lines[-1] if lines else ""

        result = f"🏓 <b>РЕЗУЛЬТАТЫ PING ДЛЯ {escape_html(context.args[0])}</b>\n"
        result += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

        for line in lines[:-1]:
            if "bytes from" in line:
                time_match = re.search(r'time=([0-9.]+)', line)
                if time_match:
                    time_val = float(time_match.group(1))
                    if time_val < 50:
                        emoji = "🟢"
                    elif time_val < 100:
                        emoji = "🟡"
                    else:
                        emoji = "🔴"
                    result += f"{emoji} {escape_html(line)}\n"
                else:
                    result += f"• {escape_html(line)}\n"
            else:
                result += f"{escape_html(line)}\n"

        if stats:
            result += f"\n📊 <b>Статистика:</b>\n{escape_html(stats)}\n"

        result += (
            "\n💡 <b>Интерпретация:</b>\n"
            "• 🟢 &lt; 50ms - Отличное соединение\n"
            "• 🟡 50-100ms - Нормальное соединение\n"
            "• 🔴 &gt; 100ms - Медленное соединение\n"
            "• ❌ Потеря пакетов - Проблемы с сетью"
        )
    else:
        result = "❌ Ошибка при выполнении ping"

    await msg.edit_text(result, reply_markup=back_btn('ping_menu'), parse_mode='HTML')


async def pass_cmd(update: Update, context):
    """Команда /password - генератор паролей"""
    if not is_admin(update):
        return

    if context.args:
        try:
            length = max(4, min(64, int(context.args[0])))
            alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
            pwd = ''.join(secrets.choice(alphabet) for _ in range(length))
            has_upper = any(c.isupper() for c in pwd)
            has_lower = any(c.islower() for c in pwd)
            has_digit = any(c.isdigit() for c in pwd)
            has_special = any(c in "!@#$%^&*" for c in pwd)

            score = 0
            if length >= 12:
                score += 2
            elif length >= 10:
                score += 1
            if has_upper:
                score += 1
            if has_lower:
                score += 1
            if has_digit:
                score += 1
            if has_special:
                score += 2

            if score >= 6:
                strength = "🛡️ ОЧЕНЬ СИЛЬНЫЙ"
                strength_desc = "Подходит для критических систем"
            elif score >= 4:
                strength = "💪 СИЛЬНЫЙ"
                strength_desc = "Подходит для большинства сервисов"
            elif score >= 2:
                strength = "⚠️ СРЕДНИЙ"
                strength_desc = "Можно улучшить"
            else:
                strength = "❌ СЛАБЫЙ"
                strength_desc = "НЕ ИСПОЛЬЗУЙТЕ!"

            result = (
                f"🔐 <b>ГЕНЕРАТОР ПАРОЛЕЙ</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📋 <b>Пароль ({length} символов):</b>\n"
                f"<code>{escape_html(pwd)}</code>\n\n"
                f"<b>📊 ХАРАКТЕРИСТИКИ:</b>\n"
                f"• Сложность: {strength}\n"
                f"• Оценка: {strength_desc}\n"
                f"• Длина: {length} символов\n"
                f"• Заглавные: {'✅' if has_upper else '❌'}\n"
                f"• Строчные: {'✅' if has_lower else '❌'}\n"
                f"• Цифры: {'✅' if has_digit else '❌'}\n"
                f"• Спецсимволы: {'✅' if has_special else '❌'}\n\n"
                f"💡 <b>Советы:</b>\n"
                f"• Используйте менеджер паролей\n"
                f"• Не используйте один пароль везде\n"
                f"• Меняйте пароли каждые 3 месяца"
            )

            await update.message.reply_text(
                result,
                reply_markup=back_btn('pass_menu'),
                parse_mode='HTML'
            )
        except Exception:
            await update.message.reply_text("❌ Пожалуйста, укажите число (например: /password 16)")
    else:
        btns = [["10", "12", "16"], ["20", "24", "32"]]
        keyboard = [
            [InlineKeyboardButton(b, callback_data=f'pass_{b}') for b in row]
            for row in btns
        ]
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data='menu')])

        text = (
            "🔐 <b>ГЕНЕРАТОР ПАРОЛЕЙ</b>\n\n"
            "Выберите длину пароля:\n\n"
            "📋 <b>Рекомендации:</b>\n"
            "• 10-12 символов - для обычных сервисов\n"
            "• 16+ символов - для критических систем\n"
            "• Используйте разные пароли для разных сервисов"
        )

        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )


async def vps_list_cmd(update: Update, _):
    """Команда /listvps - список VPS серверов"""
    if not is_admin(update):
        return
    vps_list = db_execute(
        "SELECT id, name, expiry_date FROM vps_rental ORDER BY expiry_date",
        fetch=True
    )

    if not vps_list:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Добавить VPS", callback_data='add_vps')],
            [InlineKeyboardButton("◀️ Назад", callback_data='menu')]
        ])
        return await update.message.reply_text(
            "📭 <b>СПИСОК VPS ПУСТ</b>\n\n"
            "Нажмите кнопку ниже, чтобы добавить сервер для отслеживания сроков аренды.\n\n"
            "💡 <b>Зачем это нужно?</b>\n"
            "• Бот будет напоминать об окончании аренды\n"
            "• Можно быстро продлить срок прямо из уведомления\n"
            "• Всегда знайте, когда нужно платить",
            reply_markup=kb,
            parse_mode='HTML'
        )

    keyboard = []
    today = datetime.now().date()

    text = "📋 <b>ВАШИ VPS СЕРВЕРЫ</b>\n\n"
    text += "Выберите сервер для управления:\n\n"

    for vid, name, exp in vps_list:
        days = (datetime.strptime(exp, '%Y-%m-%d').date() - today).days
        if days < 0:
            status_emoji = "❌"
        elif days <= 7:
            status_emoji = "⚠️"
        elif days <= 14:
            status_emoji = "🟡"
        else:
            status_emoji = "✅"

        keyboard.append([
            InlineKeyboardButton(
                f"{status_emoji} {escape_html(name)} (до {exp}, осталось {days} дн.)",
                callback_data=f'vps_{vid}'
            )
        ])
        text += f"• {status_emoji} <b>{escape_html(name)}</b>: {exp} (осталось {days} дней)\n"

    keyboard.append([InlineKeyboardButton("➕ Добавить VPS", callback_data='add_vps')])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data='menu')])

    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )


async def add_vps_cmd(update: Update, context):
    """Команда /addvps - добавление VPS сервера"""
    if not is_admin(update):
        return
    args = context.args
    if len(args) < 2:
        return await update.message.reply_text(
            "❌ <b>НЕВЕРНОЕ ИСПОЛЬЗОВАНИЕ</b>\n\n"
            "📝 <b>Формат:</b>\n"
            "<code>/addvps НАЗВАНИЕ ДАТА [ДНИ_УВЕДОМЛЕНИЙ]</code>\n\n"
            "📋 <b>Примеры:</b>\n"
            "<code>/addvps MainServer 2026-12-31</code>\n"
            "<code>/addvps BackupVPS 2025-06-15 30,14,7,3,1</code>\n\n"
            "📌 <b>Параметры:</b>\n"
            "• НАЗВАНИЕ - любое имя (без пробелов)\n"
            "• ДАТА - в формате ГГГГ-ММ-ДД\n"
            "• ДНИ_УВЕДОМЛЕНИЙ - (опционально) дни для напоминаний\n\n"
            "💡 По умолчанию уведомления за: 14,10,8,4,2,1 дней",
            parse_mode='HTML'
        )

    try:
        datetime.strptime(args[1], '%Y-%m-%d')
        notify = args[2] if len(args) > 2 else '14,10,8,4,2,1'
        db_execute(
            "INSERT INTO vps_rental (name, expiry_date, notify_days) VALUES (?, ?, ?)",
            (args[0], args[1], notify)
        )
        await update.message.reply_text(
            f"✅ <b>VPS ДОБАВЛЕН</b>\n\n"
            f"📋 <b>Информация:</b>\n"
            f"• Название: {escape_html(args[0])}\n"
            f"• Дата окончания: {args[1]}\n"
            f"• Уведомления за: {notify} дней\n\n"
            f"📌 Бот будет напоминать в указанные дни до окончания аренды.",
            reply_markup=back_btn('vps_menu'),
            parse_mode='HTML'
        )
    except Exception:
        await update.message.reply_text("❌ Неверный формат даты. Используйте ГГГГ-ММ-ДД")


# ==== ОБРАБОТЧИК ДЛЯ ДИАЛОГОВ ====
async def handle_message(update: Update, context):
    """Обработчик текстовых сообщений для диалогов"""
    if not is_admin(update):
        return

    user_data = context.user_data
    text = update.message.text.strip()

    if user_data.get('awaiting_setting'):
        setting = user_data['awaiting_setting']
        try:
            if setting in ['cpu_threshold', 'ram_threshold', 'disk_threshold']:
                value = int(text)
                if 1 <= value <= 100:
                    set_setting(setting, str(value))
                    await update.message.reply_text(
                        f"✅ Порог успешно установлен на {value}%",
                        reply_markup=back_btn('settings_menu'),
                        parse_mode='HTML'
                    )
                else:
                    await update.message.reply_text("❌ Введите число от 1 до 100")

            elif setting in ['net_sent_threshold', 'net_recv_threshold']:
                value = int(text)
                if 1 <= value <= 1000:
                    set_setting(setting, str(value))
                    await update.message.reply_text(
                        f"✅ Порог успешно установлен на {value} MB/s",
                        reply_markup=back_btn('settings_menu'),
                        parse_mode='HTML'
                    )
                else:
                    await update.message.reply_text("❌ Введите число от 1 до 1000")

            elif setting == 'monitor_interval':
                value = int(text)
                if 5 <= value <= 300:
                    set_setting(setting, str(value))
                    await update.message.reply_text(
                        f"✅ Интервал успешно установлен на {value} секунд",
                        reply_markup=back_btn('settings_menu'),
                        parse_mode='HTML'
                    )
                    if context.job_queue:
                        current_jobs = context.job_queue.get_jobs_by_name('resource_monitor')
                        for job in current_jobs:
                            job.schedule_removal()
                        context.job_queue.run_repeating(
                            monitor_high_resources,
                            interval=value,
                            first=10,
                            name='resource_monitor'
                        )
                else:
                    await update.message.reply_text("❌ Введите число от 5 до 300")

            elif setting == 'add_directory':
                parts = text.split()
                if len(parts) == 2:
                    path, threshold = parts
                    threshold = int(threshold)
                    if os.path.exists(path):
                        db_execute(
                            "INSERT INTO directory_monitor (path, threshold_mb) VALUES (?, ?)",
                            (path, threshold)
                        )
                        await update.message.reply_text(
                            f"✅ Папка {escape_html(path)} добавлена с порогом {threshold} MB",
                            reply_markup=back_btn('directory_monitor_menu'),
                            parse_mode='HTML'
                        )
                    else:
                        await update.message.reply_text("❌ Указанный путь не существует")
                else:
                    await update.message.reply_text(
                        "❌ Используйте формат: /путь/к/папке порог_в_MB"
                    )

        except ValueError:
            await update.message.reply_text("❌ Введите число")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {escape_html(str(e))}")
        finally:
            user_data['awaiting_setting'] = None

    else:
        await update.message.reply_text(
            "👋 Используйте /start для открытия главного меню",
            reply_markup=back_btn('menu'),
            parse_mode='HTML'
        )


# ==== CALLBACK ХЕНДЛЕР ====
async def button_handler(update: Update, context):
    """Обработчик нажатий на инлайн кнопки"""
    query = update.callback_query
    await query.answer()

    if str(query.from_user.id) != ADMIN_ID:
        return await query.edit_message_text("⛔ У вас нет прав.")

    data = query.data

    if data == 'menu':
        return await query.edit_message_text(
            f"👋 <b>Главное меню</b>\nСервер: {escape_html(config.SERVER_NAME)}",
            reply_markup=menu_keyboard(),
            parse_mode='HTML'
        )

    if data == 'info_menu':
        return await query.edit_message_text(
            "ℹ️ <b>ИНФОРМАЦИЯ</b>\n\n"
            "Выберите раздел:\n\n"
            "• 🖥️ О сервере - подробная информация о системе\n"
            "• 📊 Системная диагностика - диагностика всех компонентов\n"
            "• 🤖 О боте - информация о версии и обновлениях",
            reply_markup=info_menu_keyboard(),
            parse_mode='HTML'
        )

    if data == 'settings_menu':
        return await query.edit_message_text(
            "⚙️ <b>НАСТРОЙКИ БОТА</b>\n\n"
            "Выберите параметр для настройки:\n\n"
            "🔔 <b>Пороги уведомлений:</b>\n"
            "• CPU - загрузка процессора\n"
            "• RAM - использование памяти\n"
            "• Диск - заполнение диска\n"
            "• Трафик - скорость передачи данных\n\n"
            "📊 <b>Отчеты:</b>\n"
            "• Ежедневный отчет - автоматическая статистика\n"
            "• Компактный режим - краткое отображение",
            reply_markup=settings_menu_keyboard(),
            parse_mode='HTML'
        )

    if data == 'set_cpu_threshold':
        context.user_data['awaiting_setting'] = 'cpu_threshold'
        await query.edit_message_text(
            "⚙️ <b>НАСТРОЙКА ПОРОГА CPU</b>\n\n"
            "📝 Введите число от 1 до 100 (процент загрузки процессора)\n\n"
            f"📊 Текущее значение: {get_setting('cpu_threshold', '30')}%\n\n"
            "💡 <b>Рекомендации:</b>\n"
            "• 30-50% - для веб-серверов\n"
            "• 50-70% - для dev-серверов\n"
            "• 70-90% - для высоконагруженных систем",
            reply_markup=back_btn('settings_menu'),
            parse_mode='HTML'
        )
        return

    if data == 'set_ram_threshold':
        context.user_data['awaiting_setting'] = 'ram_threshold'
        await query.edit_message_text(
            "⚙️ <b>НАСТРОЙКА ПОРОГА RAM</b>\n\n"
            "📝 Введите число от 1 до 100 (процент использования памяти)\n\n"
            f"📊 Текущее значение: {get_setting('ram_threshold', '85')}%\n\n"
            "💡 <b>Рекомендации:</b>\n"
            "• 70-80% - норма для большинства серверов\n"
            "• 80-90% - требуется внимание\n"
            "• >90% - критично, возможны проблемы",
            reply_markup=back_btn('settings_menu'),
            parse_mode='HTML'
        )
        return

    if data == 'set_disk_threshold':
        context.user_data['awaiting_setting'] = 'disk_threshold'
        await query.edit_message_text(
            "⚙️ <b>НАСТРОЙКА ПОРОГА ДИСКА</b>\n\n"
            "📝 Введите число от 1 до 100 (процент заполнения диска)\n\n"
            f"📊 Текущее значение: {get_setting('disk_threshold', '85')}%\n\n"
            "💡 <b>Рекомендации:</b>\n"
            "• 70-80% - пора чистить\n"
            "• 80-90% - срочно чистить\n"
            "• >90% - возможны ошибки",
            reply_markup=back_btn('settings_menu'),
            parse_mode='HTML'
        )
        return

    if data == 'set_net_sent':
        context.user_data['awaiting_setting'] = 'net_sent_threshold'
        await query.edit_message_text(
            "⚙️ <b>НАСТРОЙКА ПОРОГА ИСХОДЯЩЕГО ТРАФИКА</b>\n\n"
            "📝 Введите число от 1 до 1000 (MB/s)\n\n"
            f"📊 Текущее значение: {get_setting('net_sent_threshold', '100')} MB/s\n\n"
            "💡 <b>Рекомендации:</b>\n"
            "• 10-50 MB/s - для обычных серверов\n"
            "• 50-200 MB/s - для файловых серверов\n"
            "• >200 MB/s - для высоконагруженных",
            reply_markup=back_btn('settings_menu'),
            parse_mode='HTML'
        )
        return

    if data == 'set_net_recv':
        context.user_data['awaiting_setting'] = 'net_recv_threshold'
        await query.edit_message_text(
            "⚙️ <b>НАСТРОЙКА ПОРОГА ВХОДЯЩЕГО ТРАФИКА</b>\n\n"
            "📝 Введите число от 1 до 1000 (MB/s)\n\n"
            f"📊 Текущее значение: {get_setting('net_recv_threshold', '100')} MB/s\n\n"
            "💡 <b>Рекомендации:</b>\n"
            "• 10-50 MB/s - для обычных серверов\n"
            "• 50-200 MB/s - для файловых серверов\n"
            "• >200 MB/s - для высоконагруженных",
            reply_markup=back_btn('settings_menu'),
            parse_mode='HTML'
        )
        return

    if data == 'set_interval':
        context.user_data['awaiting_setting'] = 'monitor_interval'
        await query.edit_message_text(
            "⚙️ <b>НАСТРОЙКА ИНТЕРВАЛА МОНИТОРИНГА</b>\n\n"
            "📝 Введите число от 5 до 300 (секунд)\n\n"
            f"📊 Текущее значение: {get_setting('monitor_interval', '30')} сек\n\n"
            "💡 <b>Рекомендации:</b>\n"
            "• 10-30 сек - для критичных систем\n"
            "• 30-60 сек - для обычных серверов\n"
            "• 60-300 сек - для экономии ресурсов",
            reply_markup=back_btn('settings_menu'),
            parse_mode='HTML'
        )
        return

    if data == 'toggle_daily_report':
        current = get_setting('enable_daily_report', 'false')
        new_value = 'false' if current == 'true' else 'true'
        set_setting('enable_daily_report', new_value)
        await query.edit_message_text(
            f"✅ Ежедневный отчет {'включен' if new_value == 'true' else 'выключен'}\n\n"
            f"{'📊 Теперь вы будете получать статистику каждый день' if new_value == 'true' else '📊 Ежедневные отчеты отключены'}",
            reply_markup=back_btn('settings_menu'),
            parse_mode='HTML'
        )
        return

    if data == 'toggle_compact_mode':
        current = get_setting('compact_mode', 'false')
        new_value = 'false' if current == 'true' else 'true'
        set_setting('compact_mode', new_value)
        await query.edit_message_text(
            f"✅ Компактный режим {'включен' if new_value == 'true' else 'выключен'}\n\n"
            f"{'📋 Теперь отчеты будут короче' if new_value == 'true' else '📋 Теперь отчеты будут подробными'}",
            reply_markup=back_btn('settings_menu'),
            parse_mode='HTML'
        )
        return

    if data == 'toggle_fail2ban':
        current = get_setting('enable_fail2ban_alerts', 'false')
        new_value = 'false' if current == 'true' else 'true'
        set_setting('enable_fail2ban_alerts', new_value)
        await query.edit_message_text(
            f"✅ Мониторинг Fail2ban {'включен' if new_value == 'true' else 'выключен'}\n\n"
            f"{'🚫 Теперь вы будете получать уведомления о блокировках IP' if new_value == 'true' else '🚫 Уведомления Fail2ban отключены'}",
            reply_markup=back_btn('settings_menu'),
            parse_mode='HTML'
        )
        return

    if data == 'directory_monitor_menu':
        await query.edit_message_text(
            "📁 <b>МОНИТОРИНГ ДИРЕКТОРИЙ</b>\n\n"
            "Здесь вы можете настроить отслеживание размера папок.\n"
            "При превышении порога бот пришлет уведомление и список самых больших файлов.\n\n"
            "💡 <b>Для чего это нужно?</b>\n"
            "• Следить за ростом логов\n"
            "• Контролировать заполнение диска\n"
            "• Вовремя чистить временные файлы",
            reply_markup=directory_monitor_keyboard(),
            parse_mode='HTML'
        )
        return

    if data == 'add_directory':
        context.user_data['awaiting_setting'] = 'add_directory'
        await query.edit_message_text(
            "📁 <b>ДОБАВЛЕНИЕ ДИРЕКТОРИИ</b>\n\n"
            "Введите путь к папке и порог в MB через пробел.\n\n"
            "📝 <b>Пример:</b>\n"
            "<code>/var/log 500</code>\n\n"
            "Это будет отслеживать папку /var/log и уведомлять, если её размер превысит 500 MB\n\n"
            "💡 <b>Популярные папки для мониторинга:</b>\n"
            "• /var/log - системные логи\n"
            "• /home - домашние директории\n"
            "• /tmp - временные файлы\n"
            "• /var/lib/docker - образы Docker",
            reply_markup=back_btn('directory_monitor_menu'),
            parse_mode='HTML'
        )
        return

    if data.startswith('edit_dir_'):
        dir_id = data.split('_')[2]
        dir_info = db_execute(
            "SELECT path, threshold_mb FROM directory_monitor WHERE id=?",
            (dir_id,),
            fetch=True
        )
        if dir_info:
            path, threshold = dir_info[0]
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑️ Удалить", callback_data=f'delete_dir_{dir_id}')],
                [InlineKeyboardButton("◀️ Назад", callback_data='directory_monitor_menu')]
            ])
            await query.edit_message_text(
                f"📁 <b>ИНФОРМАЦИЯ О ДИРЕКТОРИИ</b>\n\n"
                f"📂 <b>Путь:</b> <code>{escape_html(path)}</code>\n"
                f"⚠️ <b>Порог:</b> {threshold} MB\n\n"
                f"Для изменения порога удалите директорию и добавьте заново.",
                reply_markup=keyboard,
                parse_mode='HTML'
            )
        return

    if data.startswith('delete_dir_'):
        dir_id = data.split('_')[2]
        db_execute("DELETE FROM directory_monitor WHERE id=?", (dir_id,))
        await query.edit_message_text(
            "✅ Директория удалена из мониторинга",
            reply_markup=back_btn('directory_monitor_menu'),
            parse_mode='HTML'
        )
        return

    if data == 'docker_monitor_menu':
        await query.edit_message_text(
            "🐳 <b>МОНИТОРИНГ DOCKER КОНТЕЙНЕРОВ</b>\n\n"
            "Здесь вы можете настроить отслеживание ресурсов контейнеров.\n"
            "При превышении порогов бот пришлет уведомление с деталями.\n\n"
            "💡 <b>Что отслеживается?</b>\n"
            "• Загрузка CPU контейнера\n"
            "• Использование RAM\n"
            "• Статус и время работы\n"
            "• Политика перезапуска",
            reply_markup=docker_monitor_keyboard(),
            parse_mode='HTML'
        )
        return

    if data.startswith('add_docker_'):
        container = data.split('_')[2]
        db_execute(
            "INSERT INTO docker_monitor (container_name, cpu_threshold, memory_threshold) VALUES (?, ?, ?)",
            (container, 50, 80)
        )
        await query.edit_message_text(
            f"✅ Контейнер {escape_html(container)} добавлен в мониторинг\n\n"
            f"📊 Пороги по умолчанию:\n"
            f"• CPU: 50%\n"
            f"• RAM: 80%",
            reply_markup=back_btn('docker_monitor_menu'),
            parse_mode='HTML'
        )
        return

    if data.startswith('edit_docker_'):
        cont_id = data.split('_')[2]
        cont_info = db_execute(
            "SELECT container_name, cpu_threshold, memory_threshold, enabled FROM docker_monitor WHERE id=?",
            (cont_id,),
            fetch=True
        )
        if cont_info:
            name, cpu, mem, enabled = cont_info[0]
            status = "✅ Включен" if enabled else "❌ Выключен"
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Вкл/Выкл", callback_data=f'toggle_docker_{cont_id}'),
                 InlineKeyboardButton("🗑️ Удалить", callback_data=f'delete_docker_{cont_id}')],
                [InlineKeyboardButton("◀️ Назад", callback_data='docker_monitor_menu')]
            ])
            await query.edit_message_text(
                f"🐳 <b>КОНТЕЙНЕР {escape_html(name.upper())}</b>\n\n"
                f"📊 <b>Статус:</b> {status}\n"
                f"⚙️ <b>Порог CPU:</b> {cpu}%\n"
                f"⚙️ <b>Порог RAM:</b> {mem}%\n\n"
                f"Для изменения порогов удалите и добавьте заново.",
                reply_markup=keyboard,
                parse_mode='HTML'
            )
        return

    if data.startswith('toggle_docker_'):
        cont_id = data.split('_')[2]
        current = db_execute(
            "SELECT enabled FROM docker_monitor WHERE id=?",
            (cont_id,),
            fetch=True
        )[0][0]
        new_value = 0 if current else 1
        db_execute("UPDATE docker_monitor SET enabled=? WHERE id=?", (new_value, cont_id))
        await query.edit_message_text(
            f"✅ Мониторинг {'включен' if new_value else 'выключен'}",
            reply_markup=back_btn('docker_monitor_menu'),
            parse_mode='HTML'
        )
        return

    if data.startswith('delete_docker_'):
        cont_id = data.split('_')[2]
        db_execute("DELETE FROM docker_monitor WHERE id=?", (cont_id,))
        await query.edit_message_text(
            "✅ Контейнер удален из мониторинга",
            reply_markup=back_btn('docker_monitor_menu'),
            parse_mode='HTML'
        )
        return

    if data == 'about_bot':
        text = (
            f"🤖 <b>О БОТЕ</b>\n\n"
            f"📋 <b>Версия:</b> {BOT_VERSION}\n"
            f"👨‍💻 <b>Разработчик:</b> GigaBlyate\n"
            f"📦 <b>Репозиторий:</b> {GITHUB_REPO}\n\n"
            f"⚙️ <b>Функции:</b>\n"
            f"• Мониторинг CPU/RAM/Диска\n"
            f"• Уведомления о высокой нагрузке\n"
            f"• Отслеживание Docker контейнеров\n"
            f"• Мониторинг директорий\n"
            f"• Fail2ban интеграция\n"
            f"• Ежедневные отчеты\n\n"
            f"Используйте кнопку ниже для проверки обновлений."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Проверить обновления", callback_data='check_bot_updates')],
            [InlineKeyboardButton("◀️ Назад", callback_data='info_menu')]
        ])
        return await query.edit_message_text(text, reply_markup=keyboard, parse_mode='HTML')

    if data == 'check_bot_updates':
        await query.edit_message_text("🔄 Проверяю наличие обновлений...")
        remote_version, message = await check_bot_version()
        keyboard = back_btn('about_bot')
        if remote_version:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📦 Перейти к релизам", url=GITHUB_RELEASES_URL)],
                [InlineKeyboardButton("◀️ Назад", callback_data='about_bot')]
            ])
        await query.edit_message_text(message, reply_markup=keyboard, parse_mode='HTML')
        return

    if data == 'system_diagnostic':
        try:
            await query.edit_message_text(
                "🔍 Собираю системную диагностику...\nЭто может занять несколько секунд."
            )
            diagnostic_text = await get_system_diagnostic()
            await query.edit_message_text(
                diagnostic_text,
                reply_markup=back_btn('info_menu'),
                parse_mode='HTML'
            )
        except Exception as e:
            error_msg = f"❌ Ошибка при выполнении диагностики: {escape_html(str(e))}"
            await query.edit_message_text(
                error_msg,
                reply_markup=back_btn('info_menu'),
                parse_mode='HTML'
            )
        return

    if data == 'about_server':
        try:
            await query.edit_message_text("⏳ Получаю информацию о сервере...")
            info_text = await get_server_info()
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 История CPU", callback_data='process_history_cpu')],
                [InlineKeyboardButton("📋 История RAM", callback_data='process_history_ram')],
                [InlineKeyboardButton("◀️ Назад", callback_data='info_menu')]
            ])
            await query.edit_message_text(info_text, reply_markup=keyboard, parse_mode='HTML')
        except Exception as e:
            error_msg = f"❌ Ошибка получения информации: {escape_html(str(e))}"
            await query.edit_message_text(
                error_msg,
                reply_markup=back_btn('info_menu'),
                parse_mode='HTML'
            )
        return

    if data == 'process_history_cpu':
        history_text = await get_process_history_text('cpu', 15)
        return await query.edit_message_text(
            history_text,
            reply_markup=back_btn('about_server'),
            parse_mode='HTML'
        )

    if data == 'process_history_ram':
        history_text = await get_process_history_text('ram', 15)
        return await query.edit_message_text(
            history_text,
            reply_markup=back_btn('about_server'),
            parse_mode='HTML'
        )

    if data == 'status':
        try:
            await query.edit_message_text("⏳ Получаю статус...")
            await query.edit_message_text(
                await get_status(),
                reply_markup=back_btn('menu'),
                parse_mode='HTML'
            )
        except Exception as e:
            error_msg = f"❌ Ошибка получения статуса: {escape_html(str(e))}"
            await query.edit_message_text(
                error_msg,
                reply_markup=back_btn('menu'),
                parse_mode='HTML'
            )
        return

    if data == 'updates':
        await query.edit_message_text("🔄 Проверяю доступные обновления...")
        count, pkgs = await check_updates()
        if count == 0:
            return await query.edit_message_text(
                "✅ <b>Система актуальна!</b>\n\nДоступных обновлений не найдено.",
                reply_markup=back_btn('menu'),
                parse_mode='HTML'
            )

        text = f"📦 <b>Доступно обновлений: {count}</b>\n\n"
        if pkgs:
            text += "📋 <b>Некоторые пакеты:</b>\n"
            for pkg in pkgs[:3]:
                text += f"• <code>{escape_html(pkg)}</code>\n"
            if count > 3:
                text += f"• ... и ещё {count - 3}\n"
        text += "\n❓ Установить обновления?"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Да, установить", callback_data='do_update'),
             InlineKeyboardButton("❌ Нет", callback_data='menu')]
        ])
        return await query.edit_message_text(text, reply_markup=kb, parse_mode='HTML')

    if data == 'do_update':
        await query.edit_message_text("🔄 Начинаю обновление сервера...\nЭто может занять несколько минут.")
        cmds = [
            "sudo apt update",
            "sudo apt upgrade -y",
            "sudo apt autoremove -y",
            "sudo apt autoclean"
        ]
        results = []
        for cmd in cmds:
            out, err = await run_cmd(cmd)
            results.append(f"✅ {cmd}" if not err else f"❌ {cmd}")

        reboot, _ = await run_cmd("[ -f /var/run/reboot-required ] && echo 'yes' || echo 'no'")
        result_text = "✅ <b>Обновление завершено!</b>\n\n" + "\n".join(results)
        if 'yes' in reboot:
            result_text += "\n\n⚠️ <b>Требуется перезагрузка!</b>"
        return await query.edit_message_text(
            result_text,
            reply_markup=back_btn('menu'),
            parse_mode='HTML'
        )

    if data == 'reboot':
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Да", callback_data='do_reboot'),
             InlineKeyboardButton("❌ Нет", callback_data='menu')]
        ])
        return await query.edit_message_text(
            "⚠️ <b>Подтвердите перезагрузку</b>",
            reply_markup=kb,
            parse_mode='HTML'
        )

    if data == 'do_reboot':
        await query.edit_message_text("🔄 Перезагрузка сервера началась...\nСервер будет недоступен около минуты.")
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🔄 <b>{escape_html(config.SERVER_NAME)}</b>: Сервер перезагружается...",
            parse_mode='HTML'
        )
        await run_cmd("sudo reboot")

    if data == 'ping_menu':
        hosts = [
            ("🌍 Google (8.8.8.8)", 'ping_8.8.8.8'),
            ("🌐 Cloudflare (1.1.1.1)", 'ping_1.1.1.1'),
            ("🏠 Локальный (127.0.0.1)", 'ping_127.0.0.1'),
            ("🌍 Яндекс", 'ping_yandex.ru'),
            ("📦 GitHub", 'ping_github.com')
        ]
        kb = [[InlineKeyboardButton(name, callback_data=cb)] for name, cb in hosts]
        kb.append([InlineKeyboardButton("◀️ Назад", callback_data='menu')])
        return await query.edit_message_text(
            "🏓 <b>ТЕСТ PING</b>\n\nВыберите хост для проверки:",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode='HTML'
        )

    if data.startswith('ping_'):
        host = data.split('_')[1]
        await query.edit_message_text(f"🏓 Пингую {host}...")
        out, err = await run_cmd(f"ping -c 4 {host} 2>&1")

        if err and 'unknown host' in err.lower():
            res = f"❌ Хост <b>{host}</b> не найден!"
        elif out:
            lines = out.strip().split('\n')
            stats = lines[-1] if lines else ""

            res = f"🏓 <b>РЕЗУЛЬТАТЫ PING ДЛЯ {host}</b>\n"
            res += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

            for line in lines[:-1]:
                if "bytes from" in line:
                    time_match = re.search(r'time=([0-9.]+)', line)
                    if time_match:
                        time_val = float(time_match.group(1))
                        if time_val < 50:
                            emoji = "🟢"
                        elif time_val < 100:
                            emoji = "🟡"
                        else:
                            emoji = "🔴"
                        res += f"{emoji} {escape_html(line)}\n"
                    else:
                        res += f"• {escape_html(line)}\n"
                else:
                    res += f"{escape_html(line)}\n"

            if stats:
                res += f"\n📊 <b>Статистика:</b>\n{escape_html(stats)}\n"

            res += (
                "\n💡 <b>Интерпретация:</b>\n"
                "• 🟢 &lt; 50ms - Отличное соединение\n"
                "• 🟡 50-100ms - Нормальное соединение\n"
                "• 🔴 &gt; 100ms - Медленное соединение"
            )
        else:
            res = "❌ Ошибка при выполнении ping"

        return await query.edit_message_text(
            res,
            reply_markup=back_btn('ping_menu'),
            parse_mode='HTML'
        )

    if data == 'pass_menu':
        btns = [["10", "12", "16"], ["20", "24", "32"]]
        kb = [
            [InlineKeyboardButton(b, callback_data=f'pass_{b}') for b in row]
            for row in btns
        ]
        kb.append([InlineKeyboardButton("◀️ Назад", callback_data='menu')])
        return await query.edit_message_text(
            "🔐 <b>ГЕНЕРАТОР ПАРОЛЕЙ</b>\n\n"
            "Выберите длину пароля:\n\n"
            "📋 <b>Рекомендации:</b>\n"
            "• 10-12 символов - для обычных сервисов\n"
            "• 16+ символов - для критических систем",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode='HTML'
        )

    if data.startswith('pass_'):
        try:
            length = int(data.split('_')[1])
            alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
            pwd = ''.join(secrets.choice(alphabet) for _ in range(length))
            has_upper = any(c.isupper() for c in pwd)
            has_lower = any(c.islower() for c in pwd)
            has_digit = any(c.isdigit() for c in pwd)
            has_special = any(c in "!@#$%^&*" for c in pwd)

            score = 0
            if length >= 12:
                score += 2
            elif length >= 10:
                score += 1
            if has_upper:
                score += 1
            if has_lower:
                score += 1
            if has_digit:
                score += 1
            if has_special:
                score += 2

            if score >= 6:
                strength = "🛡️ ОЧЕНЬ СИЛЬНЫЙ"
            elif score >= 4:
                strength = "💪 СИЛЬНЫЙ"
            elif score >= 2:
                strength = "⚠️ СРЕДНИЙ"
            else:
                strength = "❌ СЛАБЫЙ"

            result = (
                f"🔐 <b>ГЕНЕРАТОР ПАРОЛЕЙ</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📋 <b>Пароль ({length} символов):</b>\n"
                f"<code>{escape_html(pwd)}</code>\n\n"
                f"<b>📊 ХАРАКТЕРИСТИКИ:</b>\n"
                f"• Сложность: {strength}\n"
                f"• Заглавные: {'✅' if has_upper else '❌'}\n"
                f"• Строчные: {'✅' if has_lower else '❌'}\n"
                f"• Цифры: {'✅' if has_digit else '❌'}\n"
                f"• Спецсимволы: {'✅' if has_special else '❌'}"
            )
            return await query.edit_message_text(
                result,
                reply_markup=back_btn('pass_menu'),
                parse_mode='HTML'
            )
        except ValueError:
            return await query.edit_message_text(
                "❌ Ошибка: неверный формат длины пароля",
                reply_markup=back_btn('pass_menu')
            )

    if data == 'vps_menu':
        vps_list = db_execute(
            "SELECT id, name, expiry_date FROM vps_rental ORDER BY expiry_date",
            fetch=True
        )
        if not vps_list:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Добавить VPS", callback_data='add_vps')],
                [InlineKeyboardButton("◀️ Назад", callback_data='menu')]
            ])
            return await query.edit_message_text(
                "📭 <b>СПИСОК VPS ПУСТ</b>\n\n"
                "Нажмите кнопку ниже, чтобы добавить сервер для отслеживания сроков аренды.",
                reply_markup=kb,
                parse_mode='HTML'
            )

        today = datetime.now().date()
        kb = []
        for vid, name, exp in vps_list:
            days = (datetime.strptime(exp, '%Y-%m-%d').date() - today).days
            status = "❌" if days < 0 else "⚠️" if days <= 7 else "🟡" if days <= 14 else "✅"
            kb.append([
                InlineKeyboardButton(
                    f"{status} {escape_html(name)} (до {exp}, осталось {days} дн.)",
                    callback_data=f'vps_{vid}'
                )
            ])

        kb.append([InlineKeyboardButton("➕ Добавить VPS", callback_data='add_vps')])
        kb.append([InlineKeyboardButton("◀️ Назад", callback_data='menu')])
        return await query.edit_message_text(
            "📋 <b>ВАШИ VPS СЕРВЕРЫ</b>\n\nВыберите сервер для управления:",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode='HTML'
        )

    if data == 'add_vps':
        return await query.edit_message_text(
            "📝 <b>КАК ДОБАВИТЬ VPS СЕРВЕР</b>\n\n"
            "Для добавления сервера используйте команду:\n\n"
            "<code>/addvps НАЗВАНИЕ ДАТА [ДНИ_УВЕДОМЛЕНИЙ]</code>\n\n"
            "📋 <b>Примеры:</b>\n"
            "<code>/addvps MainServer 2026-12-31</code>\n"
            "<code>/addvps BackupVPS 2025-06-15 30,14,7,3,1</code>\n\n"
            "💡 По умолчанию уведомления за: 14,10,8,4,2,1 дней",
            reply_markup=back_btn('vps_menu'),
            parse_mode='HTML'
        )

    if data.startswith('vps_'):
        vid = data.split('_')[1]
        vps = db_execute(
            "SELECT name, expiry_date, notify_days FROM vps_rental WHERE id=?",
            (vid,),
            fetch=True
        )
        if not vps:
            return await query.edit_message_text("❌ VPS не найден")

        name, exp, notify = vps[0]
        days = (datetime.strptime(exp, '%Y-%m-%d').date() - datetime.now().date()).days
        details = (
            f"📊 <b>ИНФОРМАЦИЯ О VPS</b>\n\n"
            f"📋 <b>Имя:</b> {escape_html(name)}\n"
            f"🆔 <b>ID:</b> {vid}\n"
            f"📅 <b>Дата окончания:</b> {exp}\n"
            f"⏱️ <b>Осталось дней:</b> {days}\n"
            f"🔔 <b>Уведомления за:</b> {notify} дн."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Продлено", callback_data=f'renew_{vid}'),
             InlineKeyboardButton("❌ Удалить", callback_data=f'del_{vid}')],
            [InlineKeyboardButton("◀️ Назад к списку", callback_data='vps_menu')],
            [InlineKeyboardButton("🏠 Главное меню", callback_data='menu')]
        ])
        return await query.edit_message_text(details, reply_markup=kb, parse_mode='HTML')

    if data.startswith('renew_'):
        vid = data.split('_')[1]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("1 месяц", callback_data=f'period_{vid}_1'),
             InlineKeyboardButton("3 месяца", callback_data=f'period_{vid}_3')],
            [InlineKeyboardButton("6 месяцев", callback_data=f'period_{vid}_6'),
             InlineKeyboardButton("12 месяцев", callback_data=f'period_{vid}_12')],
            [InlineKeyboardButton("◀️ Назад", callback_data=f'vps_{vid}')]
        ])
        return await query.edit_message_text(
            "📅 <b>ВЫБЕРИТЕ СРОК ПРОДЛЕНИЯ</b>",
            reply_markup=kb,
            parse_mode='HTML'
        )

    if data.startswith('period_'):
        _, vid, months = data.split('_')
        months = int(months)
        days_map = {1: 30, 3: 90, 6: 180, 12: 365}
        new_date = (datetime.now() + timedelta(days=days_map[months])).strftime('%Y-%m-%d')
        db_execute(
            "UPDATE vps_rental SET expiry_date=?, last_notify=NULL WHERE id=?",
            (new_date, vid)
        )
        name = db_execute("SELECT name FROM vps_rental WHERE id=?", (vid,), fetch=True)[0][0]
        month_word = "месяц" if months == 1 else "месяца" if months in [2, 3, 4] else "месяцев"
        return await query.edit_message_text(
            f"✅ <b>СРОК АРЕНДЫ ПРОДЛЁН!</b>\n\n"
            f"📋 <b>Сервер:</b> {escape_html(name)}\n"
            f"📅 <b>Новая дата окончания:</b> {new_date}\n"
            f"⏱️ <b>Срок:</b> {months} {month_word}",
            reply_markup=back_btn('vps_menu'),
            parse_mode='HTML'
        )

    if data.startswith('del_'):
        vid = data.split('_')[1]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Да, удалить", callback_data=f'confirm_del_{vid}'),
             InlineKeyboardButton("❌ Нет", callback_data=f'vps_{vid}')]
        ])
        return await query.edit_message_text(
            f"⚠️ Вы уверены, что хотите удалить VPS #{vid}?",
            reply_markup=kb,
            parse_mode='HTML'
        )

    if data.startswith('confirm_del_'):
        vid = data.split('_')[2]
        db_execute("DELETE FROM vps_rental WHERE id=?", (vid,))
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 К списку VPS", callback_data='vps_menu')],
            [InlineKeyboardButton("🏠 Главное меню", callback_data='menu')]
        ])
        return await query.edit_message_text(
            f"✅ VPS #{vid} удалён из списка отслеживания",
            reply_markup=kb,
            parse_mode='HTML'
        )

    if data == 'help':
        help_text = (
            "🤖 <b>ПОМОЩЬ ПО БОТУ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "<b>📊 ОСНОВНЫЕ РАЗДЕЛЫ:</b>\n\n"
            "• <b>Статус</b> - быстрая информация о сервере\n"
            "  Показывает CPU, RAM, диск, аптайм\n\n"
            "• <b>Обновить</b> - проверка и установка обновлений\n"
            "  Автоматически обновляет все пакеты\n\n"
            "• <b>Перезагрузка</b> - перезагрузка сервера\n"
            "  Требуется подтверждение\n\n"
            "• <b>Ping</b> - проверка доступности хостов\n"
            "  Цветовая индикация времени ответа\n\n"
            "• <b>Пароль</b> - генератор надежных паролей\n"
            "  Оценка сложности и рекомендации\n\n"
            "• <b>VPS</b> - управление сроками аренды\n"
            "  Напоминания об оплате\n\n"
            "• <b>Информация</b> - детальная информация\n"
            "  О сервере, диагностика, о боте\n\n"
            "• <b>Настройки</b> - настройка порогов\n"
            "  CPU, RAM, диск, трафик, отчеты\n\n"
            "<b>📌 ИНТЕРПРЕТАЦИЯ ЦВЕТОВ:</b>\n"
            "🟢 &lt; 50% - отлично\n"
            "🟡 50-80% - нормально\n"
            "🔴 &gt; 80% - требуется внимание\n\n"
            "<b>💡 СОВЕТЫ:</b>\n"
            "• Настройте пороги под свой сервер\n"
            "• Включите ежедневные отчеты\n"
            "• Добавьте VPS для отслеживания\n"
            "• Используйте компактный режим для быстрого просмотра"
        )
        return await query.edit_message_text(
            help_text,
            reply_markup=back_btn('menu'),
            parse_mode='HTML'
        )


# ==== УВЕДОМЛЕНИЯ ====
async def check_expiry(context):
    """Проверка сроков аренды VPS"""
    today = datetime.now().date().strftime('%Y-%m-%d')
    for vid, name, exp, notify, last in db_execute("SELECT * FROM vps_rental", fetch=True):
        days = (datetime.strptime(exp, '%Y-%m-%d').date() - datetime.now().date()).days
        if days <= 0:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"⚠️ <b>⚠️ СРОК АРЕНДЫ ИСТЁК ⚠️</b>\n\n"
                    f"🖥️ <b>Сервер:</b> {escape_html(name)}\n"
                    f"📅 <b>Дата окончания:</b> {exp}\n"
                    f"⏱️ <b>Просрочено:</b> {abs(days)} дней\n\n"
                    f"💡 <b>Что делать?</b>\n"
                    f"1. Срочно продлите аренду в панели управления\n"
                    f"2. Сделайте бэкап важных данных\n"
                    f"3. После продления нажмите кнопку ниже"
                ),
                parse_mode='HTML'
            )
        elif str(days) in notify.split(',') and last != today:
            days_word = "день" if days == 1 else "дня" if days in [2, 3, 4] else "дней"
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Продлено", callback_data=f'renew_{vid}')]
            ])
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"🔔 <b>НАПОМИНАНИЕ ОБ ОПЛАТЕ VPS</b>\n\n"
                    f"🖥️ <b>Сервер:</b> {escape_html(name)}\n"
                    f"⏱️ <b>Осталось:</b> {days} {days_word}\n"
                    f"📅 <b>Дата окончания:</b> {exp}\n\n"
                    f"💡 После продления нажмите кнопку ниже, "
                    f"чтобы обновить дату в боте."
                ),
                reply_markup=kb,
                parse_mode='HTML'
            )
            db_execute("UPDATE vps_rental SET last_notify=? WHERE id=?", (today, vid))


async def daily_report(context):
    """Отправка ежедневного отчета"""
    if get_setting('enable_daily_report', 'false') == 'true':
        report = await generate_daily_report()
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=report,
            parse_mode='HTML'
        )


async def daily_bot_version_check(context):
    """Проверка версии бота на GitHub"""
    remote_version, message = await check_bot_version()
    if remote_version:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🔔 <b>Ежедневная проверка обновлений</b>\n\n{message}",
            parse_mode='HTML'
        )


# ==== MAIN ====
def main():
    """Главная функция запуска бота"""
    init_db()

    app = Application.builder().token(config.TOKEN).build()

    handlers = [
        CommandHandler("start", start),
        CommandHandler("status", status_cmd),
        CommandHandler("update", update_cmd),
        CommandHandler("reboot", reboot_cmd),
        CommandHandler("ping", ping_cmd),
        CommandHandler("password", pass_cmd),
        CommandHandler("listvps", vps_list_cmd),
        CommandHandler("addvps", add_vps_cmd),
        CommandHandler(
            "help",
            lambda u, c: u.message.reply_text(
                "🤖 <b>Доступные команды:</b>\n\n"
                "/start - Главное меню\n"
                "/status - Статус сервера\n"
                "/update - Проверка и установка обновлений\n"
                "/reboot - Перезагрузка сервера\n"
                "/ping [хост] - Тест ping\n"
                "/password [длина] - Генератор паролей\n"
                "/addvps - Добавить VPS для отслеживания\n"
                "/listvps - Список VPS\n"
                "/help - Эта справка",
                parse_mode='HTML'
            ) if is_admin(u) else None
        )
    ]

    for handler in handlers:
        app.add_handler(handler)

    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    if app.job_queue:
        app.job_queue.run_daily(check_expiry, time=time(10, 0))

        report_time_str = get_setting('report_time', '09:00')
        report_hour, report_minute = map(int, report_time_str.split(':'))
        app.job_queue.run_daily(daily_report, time=time(report_hour, report_minute))

        interval = int(get_setting('monitor_interval', '30'))
        app.job_queue.run_repeating(
            monitor_high_resources,
            interval=interval,
            first=10,
            name='resource_monitor'
        )

        app.job_queue.run_repeating(monitor_disk_and_network, interval=60, first=20)

        fail2ban_interval = int(get_setting('fail2ban_check_interval', '60'))
        app.job_queue.run_repeating(monitor_fail2ban, interval=fail2ban_interval, first=30)

        app.job_queue.run_repeating(monitor_directories, interval=300, first=40)

        docker_interval = int(get_setting('docker_stats_interval', '60'))
        app.job_queue.run_repeating(monitor_docker_containers, interval=docker_interval, first=50)

        app.job_queue.run_daily(daily_bot_version_check, time=time(12, 0))

        print("✅ Планировщики задач запущены")
    else:
        print("⚠️ JobQueue не доступен, уведомления работать не будут")

    settings = get_all_settings()
    print(f"✅ Бот {config.SERVER_NAME} запущен")
    print(f"📁 JSON логи процессов: {os.path.dirname(__file__)}")
    print(f"📋 Версия бота: {BOT_VERSION}")
    print(f"📋 GitHub: {GITHUB_REPO}")
    print(f"🔔 Пороги: CPU={settings.get('cpu_threshold')}%, RAM={settings.get('ram_threshold')}%, Диск={settings.get('disk_threshold')}%")
    print(f"⏱️ Интервал мониторинга: {settings.get('monitor_interval')} сек")
    print(f"📊 Ежедневный отчет: {'включен' if settings.get('enable_daily_report') == 'true' else 'выключен'}")
    print(f"📝 Компактный режим: {'включен' if settings.get('compact_mode') == 'true' else 'выключен'}")
    print(f"🚫 Fail2ban: {'включен' if settings.get('enable_fail2ban_alerts') == 'true' else 'выключен'}")

    app.run_polling()


if __name__ == '__main__':
    main()