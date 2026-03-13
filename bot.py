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
from datetime import datetime, timedelta, time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import config

# Константы
DB_PATH = os.path.join(os.path.dirname(__file__), 'vps_data.db')
PROCESS_LOG_PATH = os.path.join(os.path.dirname(__file__), 'high_cpu_processes.json')
ADMIN_ID = str(config.ADMIN_CHAT_ID)

# Версия бота и ссылка на GitHub
BOT_VERSION = "1.0.1"
GITHUB_REPO = "GigaBlyate/server-bot"  # замените на ваш репозиторий
GITHUB_RAW_VERSION_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/version.txt"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"


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


def db_execute(query, params=(), fetch=False):
    """Выполнение SQL запросов"""
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(query, params)
        return cur.fetchall() if fetch else None


# ==== РАБОТА С JSON ЛОГАМИ ====
def save_high_cpu_processes(processes):
    """Сохраняет информацию о процессах с высоким CPU в JSON"""
    data = {
        'timestamp': datetime.now().isoformat(),
        'processes': processes
    }

    history = []
    if os.path.exists(PROCESS_LOG_PATH):
        try:
            with open(PROCESS_LOG_PATH, 'r', encoding='utf-8') as f:
                history = json.load(f)
                if not isinstance(history, list):
                    history = []
        except:
            history = []

    history.append(data)
    if len(history) > 100:
        history = history[-100:]

    with open(PROCESS_LOG_PATH, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def get_high_cpu_history(limit=10):
    """Получает историю процессов с высоким CPU"""
    if not os.path.exists(PROCESS_LOG_PATH):
        return []

    try:
        with open(PROCESS_LOG_PATH, 'r', encoding='utf-8') as f:
            history = json.load(f)
            return history[-limit:] if history else []
    except:
        return []


# ==== МОНИТОРИНГ ПРОЦЕССОВ ====
async def monitor_high_cpu(context):
    """Мониторит процессы с высоким потреблением CPU"""
    try:
        high_cpu_processes = []
        threshold = 30  # Порог CPU в процентах

        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'create_time']):
            try:
                cpu_percent = proc.info['cpu_percent'] or 0
                create_time = proc.info['create_time']
                if create_time:
                    process_age = datetime.now().timestamp() - create_time
                    if process_age < 30:  # Пропускаем процессы младше 30 секунд
                        continue

                if cpu_percent > threshold:
                    memory_percent = proc.info['memory_percent'] or 0
                    high_cpu_processes.append({
                        'pid': proc.info['pid'],
                        'name': proc.info['name'],
                        'cpu': round(cpu_percent, 1),
                        'memory': round(memory_percent, 1),
                        'age': round(process_age, 0) if create_time else 0
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if high_cpu_processes:
            high_cpu_processes.sort(key=lambda x: x['cpu'], reverse=True)
            save_high_cpu_processes(high_cpu_processes)

            for proc in high_cpu_processes[:5]:
                db_execute(
                    "INSERT INTO process_alerts (process_name, pid, cpu_percent, memory_percent, status) VALUES (?, ?, ?, ?, ?)",
                    (proc['name'], proc['pid'], proc['cpu'], proc['memory'], 'high_cpu')
                )

            message = f"⚠️ <b>Обнаружена высокая нагрузка CPU!</b>\n\n"
            message += f"📊 <b>Процессы с CPU > {threshold}%:</b>\n"
            message += "━━━━━━━━━━━━━━━━━━━━━\n"

            for i, proc in enumerate(high_cpu_processes[:5], 1):
                message += f"{i}. <b>{proc['name']}</b>\n"
                message += f"   • PID: {proc['pid']}\n"
                message += f"   • CPU: {proc['cpu']}%\n"
                message += f"   • RAM: {proc['memory']}%\n"
                if proc['age'] > 0:
                    minutes = int(proc['age'] // 60)
                    seconds = int(proc['age'] % 60)
                    message += f"   • Время работы: {minutes}м {seconds}с\n"
                message += "\n"

            if len(high_cpu_processes) > 5:
                message += f"<i>... и ещё {len(high_cpu_processes) - 5} процессов</i>\n\n"

            message += f"📝 Полная история доступна в разделе 'О сервере'"

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 Подробнее о сервере", callback_data='about_server')],
                [InlineKeyboardButton("📋 История процессов", callback_data='process_history')]
            ])

            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=message,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
    except Exception as e:
        print(f"Ошибка мониторинга CPU: {e}")


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
         InlineKeyboardButton("❓ Помощь", callback_data='help')]
    ])


def info_menu_keyboard():
    """Подменю информации: о сервере и о боте"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🖥️ О сервере", callback_data='about_server'),
         InlineKeyboardButton("🤖 О боте", callback_data='about_bot')],
        [InlineKeyboardButton("◀️ Назад", callback_data='menu')]
    ])


def back_btn(callback='menu'):
    """Кнопка назад с указанным callback"""
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data=callback)]])


# ==== ПРОВЕРКА ОБНОВЛЕНИЙ БОТА С GITHUB ====
async def check_bot_version():
    """Проверяет последнюю версию бота на GitHub и сравнивает с текущей"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(GITHUB_RAW_VERSION_URL, timeout=5) as resp:
                if resp.status == 200:
                    remote_version = (await resp.text()).strip()
                    # Сравниваем версии (просто как строки, но можно использовать packaging.version для более точного)
                    if remote_version != BOT_VERSION:
                        return remote_version, f"🔔 <b>Доступно обновление!</b>\n\nТекущая версия: {BOT_VERSION}\nНовая версия: {remote_version}\n\nСкачать: {GITHUB_RELEASES_URL}"
                    else:
                        return None, f"✅ <b>У вас актуальная версия</b> {BOT_VERSION}"
                else:
                    return None, f"❌ Не удалось проверить обновления (код {resp.status})"
    except aiohttp.ClientError as e:
        return None, f"❌ Ошибка соединения с GitHub: {e}"
    except Exception as e:
        return None, f"❌ Ошибка при проверке обновлений: {e}"


# ==== ОСНОВНЫЕ ФУНКЦИИ ====
async def get_server_info():
    """Подробная информация о сервере"""
    try:
        # Информация о CPU
        cpu_info = {}
        try:
            with open('/proc/cpuinfo', 'r') as f:
                for line in f:
                    if 'model name' in line:
                        cpu_info['model'] = line.split(':')[1].strip()
                        break
        except:
            cpu_info['model'] = platform.processor() or 'Неизвестно'

        cpu_freq = psutil.cpu_freq()
        cpu_count_phys = psutil.cpu_count(logical=False)
        cpu_count_log = psutil.cpu_count(logical=True)
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_percent_per_core = psutil.cpu_percent(interval=1, percpu=True)

        # Информация о памяти
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()

        # Информация о дисках
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
                except:
                    continue

        # Сетевая информация
        net = psutil.net_io_counters()
        net_connections = len(psutil.net_connections())

        # Системная информация
        boot_time = datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.now() - boot_time
        users = len(psutil.users())
        load_avg = psutil.getloadavg()

        # Формируем сообщение
        text = f"🖥️ <b>ПОДРОБНАЯ ИНФОРМАЦИЯ О СЕРВЕРЕ</b>\n"
        text += f"━━━━━━━━━━━━━━━━━━━━━\n\n"

        text += f"<b>💻 ПРОЦЕССОР:</b>\n"
        text += f"• Модель: {cpu_info['model'][:60]}\n"
        text += f"• Физических ядер: {cpu_count_phys}\n"
        text += f"• Логических ядер: {cpu_count_log}\n"
        if cpu_freq:
            text += f"• Частота: {cpu_freq.current:.0f} МГц"
            if cpu_freq.min:
                text += f" (мин: {cpu_freq.min:.0f}, макс: {cpu_freq.max:.0f})"
            text += f"\n"
        text += f"• Загрузка: {cpu_percent}%\n"
        text += f"• Загрузка по ядрам: {', '.join([f'{p}%' for p in cpu_percent_per_core])}\n"
        text += f"• Load average: {load_avg[0]:.2f}, {load_avg[1]:.2f}, {load_avg[2]:.2f}\n\n"

        text += f"<b>💾 ПАМЯТЬ:</b>\n"
        text += f"• RAM: всего {mem.total / 1e9:.1f}GB, используется: {mem.used / 1e9:.1f}GB ({mem.percent}%)\n"
        text += f"• RAM доступно: {mem.available / 1e9:.1f}GB\n"
        text += f"• Swap: всего {swap.total / 1e9:.1f}GB, используется: {swap.used / 1e9:.1f}GB ({swap.percent}%)\n\n"

        text += f"<b>💿 ДИСКИ:</b>\n"
        for disk in disks:
            text += f"• {disk['device']} ({disk['mount']}):\n"
            text += f"  Всего: {disk['total']:.1f}GB, Использовано: {disk['used']:.1f}GB ({disk['percent']}%)\n"
            text += f"  Свободно: {disk['free']:.1f}GB, ФС: {disk['fstype']}\n"

        text += f"\n<b>🌐 СЕТЬ:</b>\n"
        text += f"• Отправлено: {net.bytes_sent / 1e9:.2f}GB\n"
        text += f"• Получено: {net.bytes_recv / 1e9:.2f}GB\n"
        text += f"• Активных соединений: {net_connections}\n\n"

        text += f"<b>⚙️ СИСТЕМА:</b>\n"
        text += f"• Хост: {platform.node()}\n"
        text += f"• Система: {platform.system()} {platform.release()}\n"
        text += f"• Архитектура: {platform.machine()}\n"
        text += f"• Uptime: {uptime.days}д {uptime.seconds // 3600}ч {(uptime.seconds % 3600) // 60}м\n"
        text += f"• Пользователей онлайн: {users}\n"
        text += f"• Процессов: {len(psutil.pids())}\n"

        return text
    except Exception as e:
        return f"❌ Ошибка получения информации: {e}"


async def get_process_history_text(limit=10):
    """Получает историю процессов с высоким CPU в текстовом формате"""
    history = get_high_cpu_history(limit)

    if not history:
        return "📭 История процессов с высокой нагрузкой отсутствует."

    text = f"📋 <b>ИСТОРИЯ ВЫСОКОЙ НАГРУЗКИ (последние {limit} записей)</b>\n"
    text += f"━━━━━━━━━━━━━━━━━━━━━\n\n"

    for i, entry in enumerate(reversed(history), 1):
        timestamp = datetime.fromisoformat(entry['timestamp']).strftime('%d.%m.%Y %H:%M:%S')
        text += f"<b>{i}. {timestamp}</b>\n"

        for proc in entry['processes'][:3]:
            text += f"   • {proc['name']} (PID: {proc['pid']}) - CPU: {proc['cpu']}%, RAM: {proc['memory']}%\n"

        if len(entry['processes']) > 3:
            text += f"   <i>... и ещё {len(entry['processes']) - 3} процессов</i>\n"
        text += "\n"

    return text


async def get_status():
    """Быстрый статус сервера"""
    try:
        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        uptime = datetime.now() - datetime.fromtimestamp(psutil.boot_time())
        return (f"🖥️ <b>{config.SERVER_NAME}</b>\n━━━━━━━━━━━━━━━━\n"
                f"📊 Аптайм: {uptime.days}д {uptime.seconds // 3600}ч\n"
                f"💻 CPU: {cpu}% ({psutil.cpu_count()} ядер)\n"
                f"💾 RAM: {mem.used / 1e9:.1f}/{mem.total / 1e9:.1f}GB ({mem.percent}%)\n"
                f"💿 Диск: {disk.used / 1e9:.1f}/{disk.total / 1e9:.1f}GB ({disk.percent}%)")
    except Exception as e:
        return f"❌ Ошибка: {e}"


async def check_updates():
    """Проверка доступных обновлений системы"""
    await run_cmd("sudo apt update")
    out, _ = await run_cmd("sudo apt list --upgradable 2>/dev/null | grep -c upgradable")
    count = int(out.strip() or 0)
    packages = []
    if count > 0:
        pkg_out, _ = await run_cmd("sudo apt list --upgradable 2>/dev/null | grep upgradable | head -5 | cut -d'/' -f1")
        packages = pkg_out.strip().split('\n') if pkg_out else []
    return count, packages


# ==== ОБРАБОТЧИКИ КОМАНД ====
async def start(update: Update, _):
    """Команда /start - главное меню"""
    if not is_admin(update): return
    await update.message.reply_text(
        f"👋 <b>Добро пожаловать, {update.effective_user.first_name}!</b>\nСервер: {config.SERVER_NAME}\n\nВыберите действие:",
        reply_markup=menu_keyboard(), parse_mode='HTML')


async def status_cmd(update: Update, _):
    """Команда /status - быстрый статус сервера"""
    if not is_admin(update): return
    msg = await update.message.reply_text("⏳ Получаю статус сервера...")
    await msg.edit_text(await get_status(), reply_markup=back_btn('menu'), parse_mode='HTML')


async def update_cmd(update: Update, _):
    """Команда /update - проверка и установка обновлений"""
    if not is_admin(update): return
    msg = await update.message.reply_text("🔄 Проверяю доступные обновления...")
    count, pkgs = await check_updates()
    if count == 0:
        return await msg.edit_text("✅ <b>Система актуальна!</b>\n\nДоступных обновлений не найдено.",
                                   reply_markup=back_btn('menu'), parse_mode='HTML')

    text = f"📦 <b>Доступно обновлений: {count}</b>\n\n"
    if pkgs:
        text += "📋 <b>Некоторые пакеты:</b>\n"
        for pkg in pkgs[:3]:
            text += f"• <code>{pkg}</code>\n"
        if count > 3:
            text += f"• ... и ещё {count - 3}\n"
    text += "\n❓ Установить обновления?"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Да, установить", callback_data='do_update'),
                                      InlineKeyboardButton("❌ Нет", callback_data='menu')]])
    await msg.edit_text(text, reply_markup=keyboard, parse_mode='HTML')


async def reboot_cmd(update: Update, _):
    """Команда /reboot - перезагрузка сервера"""
    if not is_admin(update): return
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Да", callback_data='do_reboot'),
                                      InlineKeyboardButton("❌ Нет", callback_data='menu')]])
    await update.message.reply_text(
        "⚠️ <b>ВНИМАНИЕ!</b>\nВы действительно хотите перезагрузить сервер?\n\n• Все соединения будут разорваны\n• Сервер будет недоступен ~1 минуту",
        reply_markup=keyboard, parse_mode='HTML')


async def ping_cmd(update: Update, context):
    """Команда /ping - тест ping"""
    if not is_admin(update): return
    if not context.args:
        hosts = [("🌍 Google (8.8.8.8)", 'ping_8.8.8.8'), ("🌐 Cloudflare (1.1.1.1)", 'ping_1.1.1.1'),
                 ("🏠 Локальный (127.0.0.1)", 'ping_127.0.0.1')]
        keyboard = [[InlineKeyboardButton(name, callback_data=data)] for name, data in hosts]
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data='menu')])
        return await update.message.reply_text("🏓 <b>Тест Ping</b>\n\nВыберите хост:",
                                               reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

    msg = await update.message.reply_text(f"🏓 Пингую {context.args[0]}...")
    out, err = await run_cmd(f"ping -c 4 {context.args[0]} 2>&1")
    res = f"❌ Хост <b>{context.args[0]}</b> не найден!" if err and 'unknown host' in err.lower() else f"<pre>{out}</pre>" if out else "❌ Ошибка"
    await msg.edit_text(res, reply_markup=back_btn('ping_menu'), parse_mode='HTML')


async def pass_cmd(update: Update, context):
    """Команда /password - генератор паролей"""
    if not is_admin(update): return
    if context.args:
        try:
            length = max(4, min(64, int(context.args[0])))
            alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
            pwd = ''.join(secrets.choice(alphabet) for _ in range(length))
            strength = "🛡️ Сильный" if length >= 12 and any(c in "!@#$%^&*" for c in pwd) and any(
                c.isupper() for c in pwd) and any(c.islower() for c in pwd) else "💪 Слабый"
            result = f"🔐 <b>Пароль ({length} символов):</b>\n━━━━━━━━━━━━━━━━━━━━━\n<code>{pwd}</code>\n\nСложность: {strength}\nСимволов: {len(pwd)}"
            await update.message.reply_text(result, reply_markup=back_btn('pass_menu'), parse_mode='HTML')
        except:
            await update.message.reply_text("❌ Пожалуйста, укажите число (например: /password 16)")
    else:
        btns = [["8", "12", "16"], ["20", "24", "32"], ["🎲 Случайная", "⚙️ Своя"]]
        keyboard = [[InlineKeyboardButton(b, callback_data=f'pass_{b}') for b in row] for row in btns]
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data='menu')])
        await update.message.reply_text("🔐 <b>Генератор паролей</b>\n\nВыберите длину:",
                                        reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')


async def vps_list_cmd(update: Update, _):
    """Команда /listvps - список VPS серверов"""
    if not is_admin(update): return
    vps_list = db_execute("SELECT id, name, expiry_date FROM vps_rental ORDER BY expiry_date", fetch=True)

    if not vps_list:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Добавить VPS", callback_data='add_vps')],
            [InlineKeyboardButton("◀️ Назад", callback_data='menu')]
        ])
        return await update.message.reply_text("📭 Список VPS пуст.\n\nНажмите кнопку ниже, чтобы добавить сервер:",
                                               reply_markup=kb, parse_mode='HTML')

    keyboard = []
    today = datetime.now().date()
    for vid, name, exp in vps_list:
        days = (datetime.strptime(exp, '%Y-%m-%d').date() - today).days
        status = "❌" if days < 0 else "⚠️" if days <= 14 else "✅"
        keyboard.append(
            [InlineKeyboardButton(f"{status} {name} (до {exp}, осталось {days} дн.)", callback_data=f'vps_{vid}')])

    keyboard.append([InlineKeyboardButton("➕ Добавить VPS", callback_data='add_vps')])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data='menu')])
    await update.message.reply_text("📋 <b>Ваши VPS серверы:</b>\n\nВыберите для управления:",
                                    reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')


async def add_vps_cmd(update: Update, context):
    """Команда /addvps - добавление VPS сервера"""
    if not is_admin(update): return
    args = context.args
    if len(args) < 2:
        return await update.message.reply_text(
            "❌ Использование: /addvps <название> <дата ГГГГ-ММ-ДД> [дни для уведомлений]\n\n"
            "Пример: /addvps MyVPS 2026-12-31\n"
            "По умолчанию уведомления за: 14,10,8,4,2,1 дней", parse_mode='HTML')

    try:
        datetime.strptime(args[1], '%Y-%m-%d')
        notify = args[2] if len(args) > 2 else '14,10,8,4,2,1'
        db_execute("INSERT INTO vps_rental (name, expiry_date, notify_days) VALUES (?, ?, ?)",
                   (args[0], args[1], notify))
        await update.message.reply_text(
            f"✅ VPS <b>{args[0]}</b> добавлен\nДата окончания: {args[1]}\nУведомления за: {notify} дней",
            reply_markup=back_btn('vps_menu'), parse_mode='HTML')
    except:
        await update.message.reply_text("❌ Неверный формат даты. Используйте ГГГГ-ММ-ДД")


# ==== CALLBACK ХЕНДЛЕР ====
async def button_handler(update: Update, context):
    """Обработчик нажатий на инлайн кнопки"""
    query = update.callback_query
    await query.answer()

    if str(query.from_user.id) != ADMIN_ID:
        return await query.edit_message_text("⛔ У вас нет прав.")

    data = query.data

    # Главное меню
    if data == 'menu':
        return await query.edit_message_text(
            f"👋 <b>Главное меню</b>\nСервер: {config.SERVER_NAME}",
            reply_markup=menu_keyboard(),
            parse_mode='HTML'
        )

    # Информационное меню (О сервере / О боте)
    if data == 'info_menu':
        return await query.edit_message_text(
            "ℹ️ <b>Информация</b>\n\nВыберите раздел:",
            reply_markup=info_menu_keyboard(),
            parse_mode='HTML'
        )

    # О боте
    if data == 'about_bot':
        text = (f"🤖 <b>О боте</b>\n\n"
                f"Версия: {BOT_VERSION}\n"
                f"Разработчик: [GigaBlyate]\n"
                f"Репозиторий: {GITHUB_REPO}\n\n"
                f"Используйте кнопку ниже для проверки обновлений.")
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Проверить обновления", callback_data='check_bot_updates')],
            [InlineKeyboardButton("◀️ Назад", callback_data='info_menu')]
        ])
        return await query.edit_message_text(text, reply_markup=keyboard, parse_mode='HTML')

    # Проверка обновлений бота
    if data == 'check_bot_updates':
        await query.edit_message_text("🔄 Проверяю наличие обновлений...")
        remote_version, message = await check_bot_version()
        # Если есть новая версия, добавим кнопку для перехода к релизам
        keyboard = back_btn('about_bot')
        if remote_version:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📦 Перейти к релизам", url=GITHUB_RELEASES_URL)],
                [InlineKeyboardButton("◀️ Назад", callback_data='about_bot')]
            ])
        await query.edit_message_text(message, reply_markup=keyboard, parse_mode='HTML')
        return

    # О сервере (было ранее)
    if data == 'about_server':
        await query.edit_message_text("⏳ Получаю информацию о сервере...")
        info_text = await get_server_info()
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 История процессов", callback_data='process_history')],
            [InlineKeyboardButton("◀️ Назад", callback_data='info_menu')]
        ])
        return await query.edit_message_text(info_text, reply_markup=keyboard, parse_mode='HTML')

    # История процессов
    if data == 'process_history':
        history_text = await get_process_history_text(15)
        return await query.edit_message_text(history_text, reply_markup=back_btn('about_server'), parse_mode='HTML')

    # Статус
    if data == 'status':
        await query.edit_message_text("⏳ Получаю статус...")
        return await query.edit_message_text(await get_status(), reply_markup=back_btn('menu'), parse_mode='HTML')

    # Обновления системы
    if data == 'updates':
        await query.edit_message_text("🔄 Проверяю доступные обновления...")
        count, pkgs = await check_updates()
        if count == 0:
            return await query.edit_message_text("✅ <b>Система актуальна!</b>\n\nДоступных обновлений не найдено.",
                                                 reply_markup=back_btn('menu'), parse_mode='HTML')

        text = f"📦 <b>Доступно обновлений: {count}</b>\n\n"
        if pkgs:
            text += "📋 <b>Некоторые пакеты:</b>\n"
            for pkg in pkgs[:3]:
                text += f"• <code>{pkg}</code>\n"
            if count > 3:
                text += f"• ... и ещё {count - 3}\n"
        text += "\n❓ Установить обновления?"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Да, установить", callback_data='do_update'),
                                    InlineKeyboardButton("❌ Нет", callback_data='menu')]])
        return await query.edit_message_text(text, reply_markup=kb, parse_mode='HTML')

    if data == 'do_update':
        await query.edit_message_text("🔄 Начинаю обновление сервера...\nЭто может занять несколько минут.")
        cmds = ["sudo apt update", "sudo apt upgrade -y", "sudo apt autoremove -y", "sudo apt autoclean"]
        results = [f"✅ {cmd}" if not (await run_cmd(cmd))[1] else f"❌ {cmd}" for cmd in cmds]
        reboot, _ = await run_cmd("[ -f /var/run/reboot-required ] && echo 'yes' || echo 'no'")
        result_text = "✅ <b>Обновление завершено!</b>\n\n" + "\n".join(results)
        if 'yes' in reboot:
            result_text += "\n\n⚠️ <b>Требуется перезагрузка!</b>"
        return await query.edit_message_text(result_text, reply_markup=back_btn('menu'), parse_mode='HTML')

    # Перезагрузка сервера
    if data == 'reboot':
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Да", callback_data='do_reboot'),
                                    InlineKeyboardButton("❌ Нет", callback_data='menu')]])
        return await query.edit_message_text("⚠️ <b>Подтвердите перезагрузку</b>", reply_markup=kb, parse_mode='HTML')

    if data == 'do_reboot':
        await query.edit_message_text("🔄 Перезагрузка сервера началась...\nСервер будет недоступен около минуты.")
        await context.bot.send_message(chat_id=ADMIN_ID,
                                       text=f"🔄 <b>{config.SERVER_NAME}</b>: Сервер перезагружается...",
                                       parse_mode='HTML')
        await run_cmd("sudo reboot")

    # Ping
    if data == 'ping_menu':
        hosts = [("🌍 Google (8.8.8.8)", 'ping_8.8.8.8'), ("🌐 Cloudflare (1.1.1.1)", 'ping_1.1.1.1'),
                 ("🏠 Локальный (127.0.0.1)", 'ping_127.0.0.1')]
        kb = [[InlineKeyboardButton(name, callback_data=cb)] for name, cb in hosts]
        kb.append([InlineKeyboardButton("◀️ Назад", callback_data='menu')])
        return await query.edit_message_text("🏓 <b>Тест Ping</b>\n\nВыберите хост:",
                                             reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

    if data.startswith('ping_'):
        host = data.split('_')[1]
        await query.edit_message_text(f"🏓 Пингую {host}...")
        out, err = await run_cmd(f"ping -c 4 {host} 2>&1")
        res = f"❌ Хост <b>{host}</b> не найден!" if err and 'unknown host' in err.lower() else f"<pre>{out}</pre>" if out else "❌ Ошибка"
        return await query.edit_message_text(res, reply_markup=back_btn('ping_menu'), parse_mode='HTML')

    # Пароль
    if data == 'pass_menu':
        btns = [["8", "12", "16"], ["20", "24", "32"], ["🎲 Случайная", "⚙️ Своя"]]
        kb = [[InlineKeyboardButton(b, callback_data=f'pass_{b}') for b in row] for row in btns]
        kb.append([InlineKeyboardButton("◀️ Назад", callback_data='menu')])
        return await query.edit_message_text("🔐 <b>Генератор паролей</b>\n\nВыберите длину:",
                                             reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

    if data.startswith('pass_'):
        val = data.split('_')[1]
        if val == "Своя":
            return await query.edit_message_text("🔐 Отправьте /password <число>", parse_mode='HTML')

        length = secrets.choice([8, 12, 16, 20, 24, 32]) if val == "Случайная" else int(val)
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        pwd = ''.join(secrets.choice(alphabet) for _ in range(length))
        strength = "🛡️ Сильный" if length >= 12 and any(c in "!@#$%^&*" for c in pwd) and any(
            c.isupper() for c in pwd) and any(c.islower() for c in pwd) else "💪 Слабый"
        result = f"🔐 <b>Пароль ({length} символов):</b>\n━━━━━━━━━━━━━━━━━━━━━\n<code>{pwd}</code>\n\nСложность: {strength}\nСимволов: {len(pwd)}"
        return await query.edit_message_text(result, reply_markup=back_btn('pass_menu'), parse_mode='HTML')

    # VPS
    if data == 'vps_menu':
        vps_list = db_execute("SELECT id, name, expiry_date FROM vps_rental ORDER BY expiry_date", fetch=True)
        if not vps_list:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Добавить VPS", callback_data='add_vps')],
                [InlineKeyboardButton("◀️ Назад", callback_data='menu')]
            ])
            return await query.edit_message_text("📭 Список VPS пуст.\n\nНажмите кнопку ниже, чтобы добавить сервер:",
                                                 reply_markup=kb, parse_mode='HTML')

        today = datetime.now().date()
        kb = []
        for vid, name, exp in vps_list:
            days = (datetime.strptime(exp, '%Y-%m-%d').date() - today).days
            status = "❌" if days < 0 else "⚠️" if days <= 14 else "✅"
            kb.append(
                [InlineKeyboardButton(f"{status} {name} (до {exp}, осталось {days} дн.)", callback_data=f'vps_{vid}')])

        kb.append([InlineKeyboardButton("➕ Добавить VPS", callback_data='add_vps')])
        kb.append([InlineKeyboardButton("◀️ Назад", callback_data='menu')])
        return await query.edit_message_text("📋 <b>Ваши VPS серверы:</b>\n\nВыберите для управления:",
                                             reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

    if data == 'add_vps':
        return await query.edit_message_text(
            "📝 <b>Как добавить VPS сервер:</b>\n\n"
            "Для добавления сервера используйте команду:\n\n"
            "<code>/addvps НАЗВАНИЕ ДАТА [ДНИ_УВЕДОМЛЕНИЙ]</code>\n\n"
            "<b>Параметры:</b>\n"
            "• <b>НАЗВАНИЕ</b> - любое удобное имя (без пробелов)\n"
            "• <b>ДАТА</b> - в формате ГГГГ-ММ-ДД\n"
            "• <b>ДНИ_УВЕДОМЛЕНИЙ</b> - (необязательно) дни для напоминаний через запятую\n\n"
            "<b>Примеры:</b>\n"
            "<code>/addvps MainServer 2026-12-31</code>\n"
            "<code>/addvps BackupVPS 2025-06-15 30,14,7,3,1</code>\n\n"
            "<i>По умолчанию уведомления приходят за: 14, 10, 8, 4, 2, 1 день</i>",
            reply_markup=back_btn('vps_menu'), parse_mode='HTML')

    if data.startswith('vps_'):
        vid = data.split('_')[1]
        vps = db_execute("SELECT name, expiry_date, notify_days FROM vps_rental WHERE id=?", (vid,), fetch=True)
        if not vps: return await query.edit_message_text("❌ VPS не найден")

        name, exp, notify = vps[0]
        days = (datetime.strptime(exp, '%Y-%m-%d').date() - datetime.now().date()).days
        details = f"📊 <b>Информация о VPS</b>\n\n"
        details += f"Имя: {name}\n"
        details += f"ID: {vid}\n"
        details += f"Дата окончания: {exp}\n"
        details += f"Осталось дней: {days}\n"
        details += f"Уведомления за: {notify} дн."
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
        return await query.edit_message_text("📅 Выберите срок продления:", reply_markup=kb, parse_mode='HTML')

    if data.startswith('period_'):
        _, vid, months = data.split('_')
        months = int(months)
        days_map = {1: 30, 3: 90, 6: 180, 12: 365}
        new_date = (datetime.now() + timedelta(days=days_map[months])).strftime('%Y-%m-%d')
        db_execute("UPDATE vps_rental SET expiry_date=?, last_notify=NULL WHERE id=?", (new_date, vid))
        name = db_execute("SELECT name FROM vps_rental WHERE id=?", (vid,), fetch=True)[0][0]
        month_word = "месяц" if months == 1 else "месяца" if months in [2, 3, 4] else "месяцев"
        return await query.edit_message_text(
            f"✅ <b>Срок аренды продлён!</b>\n\n"
            f"Сервер: {name}\n"
            f"Новая дата окончания: {new_date}\n"
            f"Срок: {months} {month_word}",
            reply_markup=back_btn('vps_menu'), parse_mode='HTML')

    if data.startswith('del_'):
        vid = data.split('_')[1]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Да, удалить", callback_data=f'confirm_del_{vid}'),
             InlineKeyboardButton("❌ Нет", callback_data=f'vps_{vid}')]
        ])
        return await query.edit_message_text(f"⚠️ Вы уверены, что хотите удалить VPS #{vid}?", reply_markup=kb,
                                             parse_mode='HTML')

    if data.startswith('confirm_del_'):
        vid = data.split('_')[2]
        db_execute("DELETE FROM vps_rental WHERE id=?", (vid,))
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 К списку VPS", callback_data='vps_menu')],
            [InlineKeyboardButton("🏠 Главное меню", callback_data='menu')]
        ])
        return await query.edit_message_text(f"✅ VPS #{vid} удалён из списка отслеживания", reply_markup=kb,
                                             parse_mode='HTML')

    # Помощь
    if data == 'help':
        help_text = "🤖 <b>Помощь</b>\n\n• 📊 Статус - информация о сервере\n• 🔄 Обновить - проверка и установка обновлений\n• 🔄 Перезагрузка - перезагрузка сервера\n• 🏓 Ping - проверка связи\n• 🔐 Пароль - генератор паролей\n• 📋 VPS - управление сроками аренды\n• ℹ️ Информация - о сервере и о боте"
        return await query.edit_message_text(help_text, reply_markup=back_btn('menu'), parse_mode='HTML')


# ==== УВЕДОМЛЕНИЯ ====
async def check_expiry(context):
    """Проверка сроков аренды VPS и отправка уведомлений"""
    today = datetime.now().date().strftime('%Y-%m-%d')
    for vid, name, exp, notify, last in db_execute("SELECT * FROM vps_rental", fetch=True):
        days = (datetime.strptime(exp, '%Y-%m-%d').date() - datetime.now().date()).days
        if days <= 0:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"⚠️ <b>ВНИМАНИЕ! Срок аренды истёк!</b>\n\nVPS: {name}\nДата окончания: {exp}\nПросрочено на {abs(days)} дней",
                parse_mode='HTML'
            )
        elif str(days) in notify.split(',') and last != today:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Продлено", callback_data=f'renew_{vid}')]])
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"🔔 <b>Напоминание об оплате VPS</b>\n\nСервер: {name}\nОсталось дней: {days}\nДата окончания: {exp}\n\nНажмите кнопку ниже после продления:",
                reply_markup=kb,
                parse_mode='HTML'
            )
            db_execute("UPDATE vps_rental SET last_notify=? WHERE id=?", (today, vid))


# ==== ЕЖЕДНЕВНАЯ ПРОВЕРКА ОБНОВЛЕНИЙ БОТА ====
async def daily_bot_version_check(context):
    """Проверяет версию бота на GitHub и уведомляет админа, если есть обновление"""
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
    # Инициализация базы данных
    init_db()

    # Создаем приложение
    app = Application.builder().token(config.TOKEN).build()

    # Добавляем обработчики команд
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
            "/update - Проверка и установка обновлений\n"
            "/reboot - Перезагрузка сервера\n"
            "/ping [хост] - Тест ping\n"
            "/password [длина] - Генератор паролей\n"
            "/addvps - Добавить VPS для отслеживания\n"
            "/listvps - Список VPS\n"
            "/help - Эта справка",
            parse_mode='HTML') if is_admin(u) else None)
    ]

    for handler in handlers:
        app.add_handler(handler)

    # Обработчик кнопок
    app.add_handler(CallbackQueryHandler(button_handler))

    # Планировщики задач
    if app.job_queue:
        # Проверка окончания аренды VPS (каждый день в 10:00)
        app.job_queue.run_daily(check_expiry, time=time(10, 0))

        # Мониторинг высокой нагрузки CPU (каждые 30 секунд)
        app.job_queue.run_repeating(monitor_high_cpu, interval=30, first=10)

        # Ежедневная проверка версии бота (каждый день в 12:00)
        app.job_queue.run_daily(daily_bot_version_check, time=time(12, 0))

        print("✅ Планировщики задач запущены")
    else:
        print("⚠️ JobQueue не доступен, уведомления работать не будут")

    print(f"✅ Бот {config.SERVER_NAME} запущен")
    print(f"📁 JSON лог процессов: {PROCESS_LOG_PATH}")
    print(f"📋 Версия бота: {BOT_VERSION}")
    print(f"📋 GitHub: {GITHUB_REPO}")

    # Запускаем бота
    app.run_polling()


if __name__ == '__main__':
    main()
