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
from dateutil.relativedelta import relativedelta
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
BOT_VERSION = "2.2.0"
GITHUB_REPO = "GigaBlyate/server-bot"
GITHUB_RAW_VERSION_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/version.txt"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"
CHANGELOG_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/CHANGELOG.md"

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
            'compact_mode': 'false',
            'auto_update': 'false'
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


# ==== ПРОВЕРКА ОБНОВЛЕНИЙ ====
async def check_bot_version():
    """Проверяет последнюю версию бота на GitHub"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(GITHUB_RAW_VERSION_URL, timeout=5) as resp:
                if resp.status == 200:
                    remote_version = (await resp.text()).strip()
                    if remote_version != BOT_VERSION:
                        # Получаем changelog
                        changelog = await get_changelog()
                        return remote_version, changelog
                    else:
                        return None, None
                else:
                    return None, None
    except Exception:
        return None, None


async def get_changelog():
    """Получает список изменений из CHANGELOG.md"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(CHANGELOG_URL, timeout=5) as resp:
                if resp.status == 200:
                    content = await resp.text()
                    # Берем последний блок изменений
                    lines = content.split('\n')
                    changelog_lines = []
                    found = False
                    for line in lines:
                        if line.startswith('## ['):
                            if found:
                                break
                            found = True
                            changelog_lines.append(line)
                        elif found:
                            changelog_lines.append(line)
                    return '\n'.join(changelog_lines[:30])  # Ограничиваем
                else:
                    return "📝 Список изменений временно недоступен"
    except Exception:
        return "📝 Список изменений временно недоступен"


async def auto_update_bot(context, chat_id):
    """Автоматическое обновление бота"""
    try:
        commands = [
            "cd ~/server-bot",
            "git reset --hard HEAD",
            "git clean -fd",
            "git pull origin main",
            "source venv/bin/activate",
            "pip install -r requirements.txt --upgrade",
            "sudo systemctl restart server-bot"
        ]

        for cmd in commands:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await proc.communicate()

        await context.bot.send_message(
            chat_id=chat_id,
            text="✅ <b>Бот успешно обновлен!</b>\n\n🔄 Бот перезапущен.",
            parse_mode='HTML'
        )
        return True
    except Exception as e:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ <b>Ошибка при обновлении:</b>\n<code>{e}</code>",
            parse_mode='HTML'
        )
        return False


async def daily_bot_version_check(context):
    """Ежедневная проверка версии бота"""
    remote_version, changelog = await check_bot_version()

    if remote_version:
        message = (
            f"🔔 <b>ДОСТУПНО ОБНОВЛЕНИЕ!</b>\n\n"
            f"📋 <b>Текущая версия:</b> {BOT_VERSION}\n"
            f"📋 <b>Новая версия:</b> {remote_version}\n\n"
            f"📝 <b>Что нового:</b>\n{changelog}\n\n"
            f"📦 <b>Скачать:</b> {GITHUB_RELEASES_URL}"
        )

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=message,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Обновить сейчас", callback_data='update_bot_now')],
                [InlineKeyboardButton("📝 Подробнее", callback_data='show_changelog')]
            ])
        )

        # Автообновление если включено
        if get_setting('auto_update', 'false') == 'true':
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text="🔄 Автообновление включено. Начинаю обновление..."
            )
            await auto_update_bot(context, ADMIN_ID)


# ==== МОНИТОРИНГ ПРОЦЕССОВ ====
async def monitor_high_resources(context):
    """Мониторит процессы с высоким потреблением ресурсов"""
    try:
        cpu_threshold = float(get_setting('cpu_threshold', '30'))
        ram_threshold = float(get_setting('ram_threshold', '85'))

        high_cpu_processes = []
        high_ram_processes = []

        total_ram = psutil.virtual_memory().total

        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info', 'create_time']):
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

            await send_alert(context, message, 'ram')

    except Exception as e:
        print(f"Ошибка мониторинга ресурсов: {e}")


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
    compact_mode = settings.get('compact_mode', 'false')
    auto_update = settings.get('auto_update', 'false')

    report_status = "✅ Вкл" if daily_report == 'true' else "❌ Выкл"
    compact_status = "✅ Вкл" if compact_mode == 'true' else "❌ Выкл"
    auto_update_status = "✅ Вкл" if auto_update == 'true' else "❌ Выкл"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔔 CPU порог (сейчас {cpu}%)", callback_data='set_cpu_threshold')],
        [InlineKeyboardButton(f"💾 RAM порог (сейчас {ram}%)", callback_data='set_ram_threshold')],
        [InlineKeyboardButton(f"💿 Диск порог (сейчас {disk}%)", callback_data='set_disk_threshold')],
        [InlineKeyboardButton(f"📤 Исх. трафик (сейчас {net_sent} MB/s)", callback_data='set_net_sent')],
        [InlineKeyboardButton(f"📥 Вх. трафик (сейчас {net_recv} MB/s)", callback_data='set_net_recv')],
        [InlineKeyboardButton(f"⏱️ Интервал (сейчас {interval}с)", callback_data='set_interval')],
        [InlineKeyboardButton(f"📊 Ежедневный отчет ({report_status})", callback_data='toggle_daily_report')],
        [InlineKeyboardButton(f"📝 Компактный режим ({compact_status})", callback_data='toggle_compact_mode')],
        [InlineKeyboardButton(f"🔄 Автообновление ({auto_update_status})", callback_data='toggle_auto_update')],
        [InlineKeyboardButton("🔄 Обновить сейчас", callback_data='update_bot_now')],
        [InlineKeyboardButton("📝 История изменений", callback_data='show_changelog')],
        [InlineKeyboardButton("◀️ Назад", callback_data='menu')]
    ])


def back_btn(callback='menu'):
    """Кнопка назад"""
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data=callback)]])


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

        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_bar = create_progress_bar(cpu_percent, 20)

        mem = psutil.virtual_memory()
        mem_bar = create_progress_bar(mem.percent, 20)

        boot_time = datetime.fromtimestamp(psutil.boot_time())
        uptime_seconds = (datetime.now() - boot_time).total_seconds()
        uptime_str = format_uptime(uptime_seconds)
        load_avg = psutil.getloadavg()

        if compact_mode:
            text = f"🖥️ <b>{escape_html(config.SERVER_NAME)}</b>\n"
            text += "━━━━━━━━━━━━━━━━━━━━\n\n"
            text += f"💻 CPU: {cpu_bar} {cpu_percent}%\n"
            text += f"💾 RAM: {mem_bar} {mem.percent}%\n"
            text += f"⏱️  Uptime: {uptime_str}\n"
            text += f"📊 Load: {load_avg[0]:.2f}, {load_avg[1]:.2f}, {load_avg[2]:.2f}\n"
        else:
            text = f"🖥️ <b>🔍 ПОДРОБНАЯ ИНФОРМАЦИЯ О СЕРВЕРЕ 🔍</b>\n"
            text += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            text += f"<b>💻 ПРОЦЕССОР:</b>\n"
            text += f"• Модель: {escape_html(cpu_info['model'][:60])}\n"
            text += f"• Загрузка: {cpu_bar} {cpu_percent}%\n"
            text += f"• Load average: {load_avg[0]:.2f}, {load_avg[1]:.2f}, {load_avg[2]:.2f}\n\n"
            text += f"<b>💾 ПАМЯТЬ:</b>\n"
            text += f"• RAM: {mem_bar} {mem.percent}%\n"
            text += f"  Всего: {format_size(mem.total)}, Использовано: {format_size(mem.used)}\n\n"
            text += f"<b>⚙️ СИСТЕМА:</b>\n"
            text += f"• Uptime: {uptime_str}\n"

        return text
    except Exception as e:
        return f"❌ Ошибка получения информации: {escape_html(str(e))}"


async def get_status():
    """Быстрый статус сервера"""
    try:
        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        uptime = datetime.now() - datetime.fromtimestamp(psutil.boot_time())
        uptime_str = format_uptime(uptime.total_seconds())

        cpu_bar = create_progress_bar(cpu, 15)
        mem_bar = create_progress_bar(mem.percent, 15)
        disk_bar = create_progress_bar(disk.percent, 15)

        return (
            f"🖥️ <b>{escape_html(config.SERVER_NAME)}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"⏱️  <b>Аптайм:</b> {uptime_str}\n\n"
            f"💻 <b>CPU:</b>\n{cpu_bar} {cpu}%\n\n"
            f"💾 <b>RAM:</b>\n{mem_bar} {mem.percent}%\n"
            f"📊 {format_size(mem.used)} / {format_size(mem.total)}\n\n"
            f"💿 <b>Диск:</b>\n{disk_bar} {disk.percent}%\n"
            f"📊 {format_size(disk.used)} / {format_size(disk.total)}"
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
        uptime = datetime.now() - datetime.fromtimestamp(psutil.boot_time())
        uptime_str = format_uptime(uptime.total_seconds())

        cpu_bar = create_progress_bar(cpu, 20)
        mem_bar = create_progress_bar(mem.percent, 20)
        disk_bar = create_progress_bar(disk.percent, 20)

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
        "Вы действительно хотите перезагрузить сервер?",
        reply_markup=keyboard,
        parse_mode='HTML'
    )


async def ping_cmd(update: Update, context):
    """Команда /ping - тест ping"""
    if not is_admin(update):
        return

    if not context.args:
        hosts = [
            ("🌍 Google DNS", 'ping_8.8.8.8'),
            ("🌐 Cloudflare DNS", 'ping_1.1.1.1'),
            ("🏠 Локальный хост", 'ping_127.0.0.1'),
        ]

        keyboard = []
        for name, cb in hosts:
            keyboard.append([InlineKeyboardButton(name, callback_data=cb)])
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data='menu')])

        return await update.message.reply_text(
            "🏓 <b>ТЕСТ PING</b>\n\nВыберите хост для проверки:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )

    msg = await update.message.reply_text(f"🏓 Пингую {escape_html(context.args[0])}...")
    out, err = await run_cmd(f"ping -c 4 {context.args[0]} 2>&1")

    if err and 'unknown host' in err.lower():
        result = f"❌ Хост <b>{escape_html(context.args[0])}</b> не найден!"
    elif out:
        lines = out.strip().split('\n')
        result = f"🏓 <b>РЕЗУЛЬТАТЫ PING ДЛЯ {escape_html(context.args[0])}</b>\n"
        result += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        for line in lines:
            result += f"{escape_html(line)}\n"
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

            result = (
                f"🔐 <b>ГЕНЕРАТОР ПАРОЛЕЙ</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📋 <b>Пароль ({length} символов):</b>\n"
                f"<code>{escape_html(pwd)}</code>"
            )
            await update.message.reply_text(result, reply_markup=back_btn('pass_menu'), parse_mode='HTML')
        except Exception:
            await update.message.reply_text("❌ Пожалуйста, укажите число (например: /password 16)")
    else:
        btns = [["10", "12", "16"], ["20", "24", "32"]]
        keyboard = [
            [InlineKeyboardButton(b, callback_data=f'pass_{b}') for b in row]
            for row in btns
        ]
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data='menu')])
        await update.message.reply_text(
            "🔐 <b>ГЕНЕРАТОР ПАРОЛЕЙ</b>\n\nВыберите длину пароля:",
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
            "📭 <b>СПИСОК VPS ПУСТ</b>\n\nНажмите кнопку ниже, чтобы добавить сервер.",
            reply_markup=kb,
            parse_mode='HTML'
        )

    keyboard = []
    today = datetime.now().date()

    for vid, name, exp in vps_list:
        days = (datetime.strptime(exp, '%Y-%m-%d').date() - today).days
        if days < 0:
            status_emoji = "❌"
        elif days <= 7:
            status_emoji = "⚠️"
        else:
            status_emoji = "✅"

        keyboard.append([
            InlineKeyboardButton(
                f"{status_emoji} {escape_html(name)} (до {exp}, осталось {days} дн.)",
                callback_data=f'vps_{vid}'
            )
        ])

    keyboard.append([InlineKeyboardButton("➕ Добавить VPS", callback_data='add_vps')])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data='menu')])

    await update.message.reply_text(
        "📋 <b>ВАШИ VPS СЕРВЕРЫ</b>\n\nВыберите сервер для управления:",
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
            "<code>/addvps MainServer 2026-12-31</code>",
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
            f"• Дата окончания: {args[1]}",
            reply_markup=back_btn('vps_menu'),
            parse_mode='HTML'
        )
    except Exception:
        await update.message.reply_text("❌ Неверный формат даты. Используйте ГГГГ-ММ-ДД")


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

            elif setting == 'monitor_interval':
                value = int(text)
                if 5 <= value <= 300:
                    set_setting(setting, str(value))
                    await update.message.reply_text(
                        f"✅ Интервал успешно установлен на {value} секунд",
                        reply_markup=back_btn('settings_menu'),
                        parse_mode='HTML'
                    )
                else:
                    await update.message.reply_text("❌ Введите число от 5 до 300")

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
            "ℹ️ <b>ИНФОРМАЦИЯ</b>\n\nВыберите раздел:",
            reply_markup=info_menu_keyboard(),
            parse_mode='HTML'
        )

    if data == 'settings_menu':
        return await query.edit_message_text(
            "⚙️ <b>НАСТРОЙКИ БОТА</b>\n\nВыберите параметр для настройки:",
            reply_markup=settings_menu_keyboard(),
            parse_mode='HTML'
        )

    if data == 'set_cpu_threshold':
        context.user_data['awaiting_setting'] = 'cpu_threshold'
        await query.edit_message_text(
            f"⚙️ <b>НАСТРОЙКА ПОРОГА CPU</b>\n\n"
            f"📝 Введите число от 1 до 100\n"
            f"📊 Текущее значение: {get_setting('cpu_threshold', '30')}%",
            reply_markup=back_btn('settings_menu'),
            parse_mode='HTML'
        )
        return

    if data == 'set_ram_threshold':
        context.user_data['awaiting_setting'] = 'ram_threshold'
        await query.edit_message_text(
            f"⚙️ <b>НАСТРОЙКА ПОРОГА RAM</b>\n\n"
            f"📝 Введите число от 1 до 100\n"
            f"📊 Текущее значение: {get_setting('ram_threshold', '85')}%",
            reply_markup=back_btn('settings_menu'),
            parse_mode='HTML'
        )
        return

    if data == 'set_disk_threshold':
        context.user_data['awaiting_setting'] = 'disk_threshold'
        await query.edit_message_text(
            f"⚙️ <b>НАСТРОЙКА ПОРОГА ДИСКА</b>\n\n"
            f"📝 Введите число от 1 до 100\n"
            f"📊 Текущее значение: {get_setting('disk_threshold', '85')}%",
            reply_markup=back_btn('settings_menu'),
            parse_mode='HTML'
        )
        return

    if data == 'set_net_sent':
        context.user_data['awaiting_setting'] = 'net_sent_threshold'
        await query.edit_message_text(
            f"⚙️ <b>НАСТРОЙКА ПОРОГА ИСХОДЯЩЕГО ТРАФИКА</b>\n\n"
            f"📝 Введите число от 1 до 1000\n"
            f"📊 Текущее значение: {get_setting('net_sent_threshold', '100')} MB/s",
            reply_markup=back_btn('settings_menu'),
            parse_mode='HTML'
        )
        return

    if data == 'set_net_recv':
        context.user_data['awaiting_setting'] = 'net_recv_threshold'
        await query.edit_message_text(
            f"⚙️ <b>НАСТРОЙКА ПОРОГА ВХОДЯЩЕГО ТРАФИКА</b>\n\n"
            f"📝 Введите число от 1 до 1000\n"
            f"📊 Текущее значение: {get_setting('net_recv_threshold', '100')} MB/s",
            reply_markup=back_btn('settings_menu'),
            parse_mode='HTML'
        )
        return

    if data == 'set_interval':
        context.user_data['awaiting_setting'] = 'monitor_interval'
        await query.edit_message_text(
            f"⚙️ <b>НАСТРОЙКА ИНТЕРВАЛА МОНИТОРИНГА</b>\n\n"
            f"📝 Введите число от 5 до 300 секунд\n"
            f"📊 Текущее значение: {get_setting('monitor_interval', '30')} сек",
            reply_markup=back_btn('settings_menu'),
            parse_mode='HTML'
        )
        return

    if data == 'toggle_daily_report':
        current = get_setting('enable_daily_report', 'false')
        new_value = 'false' if current == 'true' else 'true'
        set_setting('enable_daily_report', new_value)
        await query.edit_message_text(
            f"✅ Ежедневный отчет {'включен' if new_value == 'true' else 'выключен'}",
            reply_markup=back_btn('settings_menu'),
            parse_mode='HTML'
        )
        return

    if data == 'toggle_compact_mode':
        current = get_setting('compact_mode', 'false')
        new_value = 'false' if current == 'true' else 'true'
        set_setting('compact_mode', new_value)
        await query.edit_message_text(
            f"✅ Компактный режим {'включен' if new_value == 'true' else 'выключен'}",
            reply_markup=back_btn('settings_menu'),
            parse_mode='HTML'
        )
        return

    if data == 'toggle_auto_update':
        current = get_setting('auto_update', 'false')
        new_value = 'false' if current == 'true' else 'true'
        set_setting('auto_update', new_value)
        await query.edit_message_text(
            f"✅ Автообновление {'включено' if new_value == 'true' else 'выключено'}\n\n"
            f"{'Теперь бот будет автоматически обновляться' if new_value == 'true' else 'Автоматические обновления отключены'}",
            reply_markup=back_btn('settings_menu'),
            parse_mode='HTML'
        )
        return

    if data == 'show_changelog':
        changelog = await get_changelog()
        await query.edit_message_text(
            f"📝 <b>ИСТОРИЯ ИЗМЕНЕНИЙ</b>\n\n{changelog}",
            reply_markup=back_btn('about_bot'),
            parse_mode='HTML'
        )
        return

    if data == 'update_bot_now':
        await query.edit_message_text("🔄 Начинаю обновление бота...")
        await auto_update_bot(context, ADMIN_ID)
        return

    if data == 'about_bot':
        text = (
            f"🤖 <b>О БОТЕ</b>\n\n"
            f"📋 <b>Версия:</b> {BOT_VERSION}\n"
            f"👨‍💻 <b>Разработчик:</b> GigaBlyate\n"
            f"📦 <b>Репозиторий:</b> {GITHUB_REPO}\n\n"
            f"⚙️ <b>Функции:</b>\n"
            f"• Мониторинг CPU/RAM/Диска\n"
            f"• Отслеживание VPS аренды\n"
            f"• Генератор паролей\n"
            f"• Ежедневные отчеты\n"
            f"• Автоматическое обновление"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Проверить обновления", callback_data='check_bot_updates')],
            [InlineKeyboardButton("📝 История изменений", callback_data='show_changelog')],
            [InlineKeyboardButton("◀️ Назад", callback_data='info_menu')]
        ])
        return await query.edit_message_text(text, reply_markup=keyboard, parse_mode='HTML')

    if data == 'check_bot_updates':
        await query.edit_message_text("🔄 Проверяю наличие обновлений...")
        remote_version, changelog = await check_bot_version()
        if remote_version:
            message = (
                f"🔔 <b>Доступно обновление!</b>\n\n"
                f"Текущая версия: {BOT_VERSION}\n"
                f"Новая версия: {remote_version}\n\n"
                f"{changelog}\n\n"
                f"Скачать: {GITHUB_RELEASES_URL}"
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Обновить сейчас", callback_data='update_bot_now')],
                [InlineKeyboardButton("◀️ Назад", callback_data='about_bot')]
            ])
        else:
            message = f"✅ <b>У вас актуальная версия</b> {BOT_VERSION}"
            keyboard = back_btn('about_bot')
        await query.edit_message_text(message, reply_markup=keyboard, parse_mode='HTML')
        return

    if data == 'system_diagnostic':
        try:
            await query.edit_message_text("🔍 Собираю системную диагностику...")
            diagnostic_text = await get_server_info()
            await query.edit_message_text(diagnostic_text, reply_markup=back_btn('info_menu'), parse_mode='HTML')
        except Exception as e:
            await query.edit_message_text(f"❌ Ошибка: {escape_html(str(e))}", reply_markup=back_btn('info_menu'))
        return

    if data == 'about_server':
        try:
            await query.edit_message_text("⏳ Получаю информацию о сервере...")
            info_text = await get_server_info()
            await query.edit_message_text(info_text, reply_markup=back_btn('info_menu'), parse_mode='HTML')
        except Exception as e:
            await query.edit_message_text(f"❌ Ошибка: {escape_html(str(e))}", reply_markup=back_btn('info_menu'))
        return

    if data == 'status':
        try:
            await query.edit_message_text("⏳ Получаю статус...")
            await query.edit_message_text(await get_status(), reply_markup=back_btn('menu'), parse_mode='HTML')
        except Exception as e:
            await query.edit_message_text(f"❌ Ошибка: {escape_html(str(e))}", reply_markup=back_btn('menu'))
        return

    if data == 'updates':
        await query.edit_message_text("🔄 Проверяю доступные обновления...")
        count, pkgs = await check_updates()
        if count == 0:
            return await query.edit_message_text(
                "✅ <b>Система актуальна!</b>",
                reply_markup=back_btn('menu'),
                parse_mode='HTML'
            )

        text = f"📦 <b>Доступно обновлений: {count}</b>\n\n"
        if pkgs:
            text += "📋 <b>Некоторые пакеты:</b>\n"
            for pkg in pkgs[:3]:
                text += f"• <code>{escape_html(pkg)}</code>\n"
        text += "\n❓ Установить обновления?"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Да, установить", callback_data='do_update'),
             InlineKeyboardButton("❌ Нет", callback_data='menu')]
        ])
        return await query.edit_message_text(text, reply_markup=kb, parse_mode='HTML')

    if data == 'do_update':
        await query.edit_message_text("🔄 Начинаю обновление сервера...")
        cmds = [
            "sudo apt update",
            "sudo apt upgrade -y",
            "sudo apt autoremove -y"
        ]
        for cmd in cmds:
            await run_cmd(cmd)
        await query.edit_message_text("✅ Обновление завершено!", reply_markup=back_btn('menu'), parse_mode='HTML')

    if data == 'reboot':
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Да", callback_data='do_reboot'),
             InlineKeyboardButton("❌ Нет", callback_data='menu')]
        ])
        return await query.edit_message_text("⚠️ <b>Подтвердите перезагрузку</b>", reply_markup=kb, parse_mode='HTML')

    if data == 'do_reboot':
        await query.edit_message_text("🔄 Перезагрузка сервера началась...")
        await run_cmd("sudo reboot")

    if data == 'ping_menu':
        hosts = [
            ("🌍 Google (8.8.8.8)", 'ping_8.8.8.8'),
            ("🌐 Cloudflare (1.1.1.1)", 'ping_1.1.1.1'),
            ("🏠 Локальный (127.0.0.1)", 'ping_127.0.0.1')
        ]
        kb = [[InlineKeyboardButton(name, callback_data=cb)] for name, cb in hosts]
        kb.append([InlineKeyboardButton("◀️ Назад", callback_data='menu')])
        return await query.edit_message_text(
            "🏓 <b>ТЕСТ PING</b>\n\nВыберите хост:",
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
            res = f"🏓 <b>РЕЗУЛЬТАТЫ PING ДЛЯ {host}</b>\n\n{escape_html(out)}"
        else:
            res = "❌ Ошибка при выполнении ping"

        return await query.edit_message_text(res, reply_markup=back_btn('ping_menu'), parse_mode='HTML')

    if data == 'pass_menu':
        btns = [["10", "12", "16"], ["20", "24", "32"]]
        kb = [[InlineKeyboardButton(b, callback_data=f'pass_{b}') for b in row] for row in btns]
        kb.append([InlineKeyboardButton("◀️ Назад", callback_data='menu')])
        return await query.edit_message_text(
            "🔐 <b>ГЕНЕРАТОР ПАРОЛЕЙ</b>\n\nВыберите длину:",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode='HTML'
        )

    if data.startswith('pass_'):
        try:
            length = int(data.split('_')[1])
            alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
            pwd = ''.join(secrets.choice(alphabet) for _ in range(length))
            result = f"🔐 <b>Пароль ({length} символов):</b>\n<code>{escape_html(pwd)}</code>"
            return await query.edit_message_text(result, reply_markup=back_btn('pass_menu'), parse_mode='HTML')
        except ValueError:
            return await query.edit_message_text("❌ Ошибка", reply_markup=back_btn('pass_menu'))

    if data == 'vps_menu':
        vps_list = db_execute("SELECT id, name, expiry_date FROM vps_rental ORDER BY expiry_date", fetch=True)
        if not vps_list:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Добавить VPS", callback_data='add_vps')],
                [InlineKeyboardButton("◀️ Назад", callback_data='menu')]
            ])
            return await query.edit_message_text("📭 <b>СПИСОК VPS ПУСТ</b>", reply_markup=kb, parse_mode='HTML')

        today = datetime.now().date()
        kb = []
        for vid, name, exp in vps_list:
            days = (datetime.strptime(exp, '%Y-%m-%d').date() - today).days
            status = "❌" if days < 0 else "⚠️" if days <= 7 else "✅"
            kb.append([InlineKeyboardButton(f"{status} {escape_html(name)} (до {exp})", callback_data=f'vps_{vid}')])

        kb.append([InlineKeyboardButton("➕ Добавить VPS", callback_data='add_vps')])
        kb.append([InlineKeyboardButton("◀️ Назад", callback_data='menu')])
        return await query.edit_message_text("📋 <b>ВАШИ VPS СЕРВЕРЫ</b>", reply_markup=InlineKeyboardMarkup(kb),
                                             parse_mode='HTML')

    if data == 'add_vps':
        return await query.edit_message_text(
            "📝 <b>КАК ДОБАВИТЬ VPS СЕРВЕР</b>\n\n"
            "<code>/addvps НАЗВАНИЕ ДАТА</code>\n\n"
            "Пример: <code>/addvps MainServer 2026-12-31</code>",
            reply_markup=back_btn('vps_menu'),
            parse_mode='HTML'
        )

    if data.startswith('vps_'):
        vid = data.split('_')[1]
        vps = db_execute("SELECT name, expiry_date, notify_days FROM vps_rental WHERE id=?", (vid,), fetch=True)
        if not vps:
            return await query.edit_message_text("❌ VPS не найден")

        name, exp, notify = vps[0]
        days = (datetime.strptime(exp, '%Y-%m-%d').date() - datetime.now().date()).days
        details = (
            f"📊 <b>ИНФОРМАЦИЯ О VPS</b>\n\n"
            f"📋 <b>Имя:</b> {escape_html(name)}\n"
            f"📅 <b>Дата окончания:</b> {exp}\n"
            f"⏱️ <b>Осталось дней:</b> {days}\n"
            f"🔔 <b>Уведомления за:</b> {notify} дн."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Продлено", callback_data=f'renew_{vid}'),
             InlineKeyboardButton("❌ Удалить", callback_data=f'del_{vid}')],
            [InlineKeyboardButton("◀️ Назад к списку", callback_data='vps_menu')]
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
        return await query.edit_message_text("📅 <b>ВЫБЕРИТЕ СРОК ПРОДЛЕНИЯ</b>", reply_markup=kb, parse_mode='HTML')

    if data.startswith('period_'):
        _, vid, months = data.split('_')
        months = int(months)

        # Получаем текущую дату окончания
        current_expiry = db_execute(
            "SELECT expiry_date FROM vps_rental WHERE id=?",
            (vid,),
            fetch=True
        )[0][0]

        # Прибавляем календарные месяцы к текущей дате окончания
        current_date = datetime.strptime(current_expiry, '%Y-%m-%d').date()
        today = datetime.now().date()

        # Если срок уже истек, считаем от сегодня
        if current_date < today:
            current_date = today

        # Прибавляем ровно столько месяцев, сколько выбрано
        new_date = (current_date + relativedelta(months=months)).strftime('%Y-%m-%d')

        db_execute(
            "UPDATE vps_rental SET expiry_date=?, last_notify=NULL WHERE id=?",
            (new_date, vid)
        )

        name = db_execute("SELECT name FROM vps_rental WHERE id=?", (vid,), fetch=True)[0][0]
        month_word = "месяц" if months == 1 else "месяца" if months in [2, 3, 4] else "месяцев"

        return await query.edit_message_text(
            f"✅ <b>СРОК АРЕНДЫ ПРОДЛЁН!</b>\n\n"
            f"📋 <b>Сервер:</b> {escape_html(name)}\n"
            f"📅 <b>Старая дата:</b> {current_expiry}\n"
            f"📅 <b>Новая дата окончания:</b> {new_date}\n"
            f"⏱️ <b>Продлено на:</b> {months} {month_word}",
            reply_markup=back_btn('vps_menu'),
            parse_mode='HTML'
        )

    if data.startswith('del_'):
        vid = data.split('_')[1]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Да, удалить", callback_data=f'confirm_del_{vid}'),
             InlineKeyboardButton("❌ Нет", callback_data=f'vps_{vid}')]
        ])
        return await query.edit_message_text(f"⚠️ Вы уверены, что хотите удалить VPS?", reply_markup=kb,
                                             parse_mode='HTML')

    if data.startswith('confirm_del_'):
        vid = data.split('_')[2]
        db_execute("DELETE FROM vps_rental WHERE id=?", (vid,))
        return await query.edit_message_text(f"✅ VPS удалён", reply_markup=back_btn('vps_menu'), parse_mode='HTML')

    if data == 'help':
        help_text = (
            "🤖 <b>ПОМОЩЬ ПО БОТУ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "<b>📊 ОСНОВНЫЕ РАЗДЕЛЫ:</b>\n\n"
            "• <b>Статус</b> - быстрая информация о сервере\n"
            "• <b>Обновить</b> - проверка обновлений системы\n"
            "• <b>Перезагрузка</b> - перезагрузка сервера\n"
            "• <b>Ping</b> - проверка доступности хостов\n"
            "• <b>Пароль</b> - генератор надежных паролей\n"
            "• <b>VPS</b> - управление сроками аренды\n"
            "• <b>Настройки</b> - настройка порогов и автообновления"
        )
        return await query.edit_message_text(help_text, reply_markup=back_btn('menu'), parse_mode='HTML')


# ==== УВЕДОМЛЕНИЯ ====
async def check_expiry(context):
    """Проверка сроков аренды VPS"""
    today = datetime.now().date().strftime('%Y-%m-%d')
    for vid, name, exp, notify, last in db_execute("SELECT * FROM vps_rental", fetch=True):
        days = (datetime.strptime(exp, '%Y-%m-%d').date() - datetime.now().date()).days
        if days <= 0:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"⚠️ <b>⚠️ СРОК АРЕНДЫ ИСТЁК ⚠️</b>\n\n🖥️ <b>Сервер:</b> {escape_html(name)}",
                parse_mode='HTML'
            )
        elif str(days) in notify.split(',') and last != today:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"🔔 <b>НАПОМИНАНИЕ ОБ ОПЛАТЕ VPS</b>\n\n🖥️ <b>Сервер:</b> {escape_html(name)}\n⏱️ <b>Осталось:</b> {days} дней",
                parse_mode='HTML'
            )
            db_execute("UPDATE vps_rental SET last_notify=? WHERE id=?", (today, vid))


async def daily_report(context):
    """Отправка ежедневного отчета"""
    if get_setting('enable_daily_report', 'false') == 'true':
        report = await generate_daily_report()
        await context.bot.send_message(chat_id=ADMIN_ID, text=report, parse_mode='HTML')


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
        CommandHandler("help", lambda u, c: u.message.reply_text(
            "🤖 <b>Доступные команды:</b>\n\n"
            "/start - Главное меню\n"
            "/status - Статус сервера\n"
            "/update - Проверка обновлений\n"
            "/reboot - Перезагрузка\n"
            "/ping - Тест ping\n"
            "/password - Генератор паролей\n"
            "/addvps - Добавить VPS\n"
            "/listvps - Список VPS\n"
            "/help - Справка",
            parse_mode='HTML'
        ) if is_admin(u) else None)
    ]

    for handler in handlers:
        app.add_handler(handler)

    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    if app.job_queue:
        app.job_queue.run_daily(check_expiry, time=time(10, 0))
        app.job_queue.run_daily(daily_report, time=time(9, 0))
        app.job_queue.run_daily(daily_bot_version_check, time=time(12, 0))

        interval = int(get_setting('monitor_interval', '30'))
        app.job_queue.run_repeating(monitor_high_resources, interval=interval, first=10, name='resource_monitor')

        print("✅ Планировщики задач запущены")
    else:
        print("⚠️ JobQueue не доступен")

    settings = get_all_settings()
    print(f"✅ Бот {config.SERVER_NAME} запущен")
    print(f"📋 Версия бота: {BOT_VERSION}")
    print(f"📋 GitHub: {GITHUB_REPO}")
    print(f"🔔 Пороги: CPU={settings.get('cpu_threshold')}%, RAM={settings.get('ram_threshold')}%")
    print(f"🔄 Автообновление: {'включено' if settings.get('auto_update') == 'true' else 'выключено'}")

    app.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()
