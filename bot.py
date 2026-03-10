#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import subprocess
import psutil
import platform
import secrets
import string
import sqlite3
import datetime
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import config

# Инициализация базы данных
def init_db():
    db_path = os.path.join(os.path.dirname(__file__), 'vps_data.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vps_rental (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            expiry_date DATE NOT NULL,
            notify_days TEXT DEFAULT '14,10,8,4,2,1',
            last_notify TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

# Добавление/обновление VPS
def add_vps(name, expiry_date, notify_days='14,10,8,4,2,1'):
    db_path = os.path.join(os.path.dirname(__file__), 'vps_data.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO vps_rental (name, expiry_date, notify_days) VALUES (?, ?, ?)",
        (name, expiry_date, notify_days)
    )
    conn.commit()
    conn.close()

# Получение списка VPS
def get_vps_list():
    db_path = os.path.join(os.path.dirname(__file__), 'vps_data.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, expiry_date, notify_days, last_notify FROM vps_rental ORDER BY expiry_date")
    data = cursor.fetchall()
    conn.close()
    return data

# Удаление VPS
def delete_vps(vps_id):
    db_path = os.path.join(os.path.dirname(__file__), 'vps_data.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM vps_rental WHERE id = ?", (vps_id,))
    conn.commit()
    conn.close()

# Обновление даты VPS
def update_vps_date(vps_id, new_date):
    db_path = os.path.join(os.path.dirname(__file__), 'vps_data.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE vps_rental SET expiry_date = ?, last_notify = NULL WHERE id = ?",
        (new_date, vps_id)
    )
    conn.commit()
    conn.close()

# Проверка и отправка уведомлений
async def check_rental_expiry(context):
    db_path = os.path.join(os.path.dirname(__file__), 'vps_data.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    today = datetime.now().date()
    vps_list = get_vps_list()
    
    for vps_id, name, expiry_date, notify_days, last_notify in vps_list:
        expiry = datetime.strptime(expiry_date, '%Y-%m-%d').date()
        days_left = (expiry - today).days
        
        if days_left <= 0:
            await context.bot.send_message(
                chat_id=config.ADMIN_CHAT_ID,
                text=f"⚠️ <b>ВНИМАНИЕ! Срок аренды истёк!</b>\n\n"
                     f"VPS: {name}\n"
                     f"Дата окончания: {expiry_date}\n"
                     f"Просрочено на {abs(days_left)} дней",
                parse_mode='HTML'
            )
        else:
            notify_list = [int(d) for d in notify_days.split(',')]
            for notify_day in notify_list:
                if days_left == notify_day:
                    today_str = today.strftime('%Y-%m-%d')
                    if last_notify != today_str:
                        # Создаем клавиатуру с кнопкой "Продлено"
                        keyboard = [[InlineKeyboardButton("✅ Продлено", callback_data=f'renew_vps_{vps_id}')]]
                        
                        await context.bot.send_message(
                            chat_id=config.ADMIN_CHAT_ID,
                            text=f"🔔 <b>Напоминание об оплате VPS</b>\n\n"
                                 f"Сервер: {name}\n"
                                 f"Осталось дней: {days_left}\n"
                                 f"Дата окончания: {expiry_date}\n\n"
                                 f"Нажмите кнопку ниже после продления:",
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode='HTML'
                        )
                        cursor.execute(
                            "UPDATE vps_rental SET last_notify = ? WHERE id = ?",
                            (today_str, vps_id)
                        )
                        conn.commit()
                    break
    
    conn.close()

# Проверка прав администратора
async def check_admin(update: Update) -> bool:
    user_id = str(update.effective_user.id)
    admin_id = str(config.ADMIN_CHAT_ID)
    
    if user_id != admin_id:
        await update.message.reply_text("⛔ У вас нет прав на использование этого бота.")
        return False
    return True

# Функция для выполнения команд
async def run_command(command):
    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            shell=True,
            executable='/bin/bash'
        )
        stdout, stderr = await process.communicate()
        return stdout.decode('utf-8', errors='ignore'), stderr.decode('utf-8', errors='ignore')
    except Exception as e:
        return None, str(e)

# Получение статуса сервера
async def get_server_status():
    try:
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count()
        memory = psutil.virtual_memory()
        ram_total = memory.total / (1024**3)
        ram_used = memory.used / (1024**3)
        ram_percent = memory.percent
        disk = psutil.disk_usage('/')
        disk_total = disk.total / (1024**3)
        disk_used = disk.used / (1024**3)
        disk_percent = disk.percent
        boot_time = datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.now() - boot_time
        days = uptime.days
        hours = uptime.seconds // 3600
        minutes = (uptime.seconds % 3600) // 60
        hostname = platform.node()
        
        return f"""🖥️ <b>{config.SERVER_NAME}</b>
━━━━━━━━━━━━━━━━━━━━━
📊 <b>СТАТУС СЕРВЕРА:</b>
• Хост: {hostname}
• Аптайм: {days}д {hours}ч {minutes}м

💻 <b>ПРОЦЕССОР:</b>
• Загрузка: {cpu_percent}%
• Ядер: {cpu_count}

💾 <b>ПАМЯТЬ:</b>
• RAM: {ram_used:.1f}GB / {ram_total:.1f}GB ({ram_percent}%)

💿 <b>ДИСК:</b>
• /: {disk_used:.1f}GB / {disk_total:.1f}GB ({disk_percent}%)"""
    except Exception as e:
        return f"❌ Ошибка получения статуса: {e}"

# Проверка доступных обновлений
async def check_updates():
    stdout, stderr = await run_command("sudo apt update 2>&1")
    upgrade_check, _ = await run_command("sudo apt list --upgradable 2>/dev/null | grep -c upgradable")
    try:
        update_count = int(upgrade_check.strip())
    except:
        update_count = 0
    if update_count > 0:
        packages, _ = await run_command("sudo apt list --upgradable 2>/dev/null | grep upgradable | head -10 | cut -d'/' -f1")
        package_list = packages.strip().split('\n') if packages else []
    else:
        package_list = []
    return update_count, package_list

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update):
        return
    keyboard = [
        [InlineKeyboardButton("📊 Статус", callback_data='status'), InlineKeyboardButton("🔄 Обновить", callback_data='check_updates')],
        [InlineKeyboardButton("🔄 Перезагрузка", callback_data='reboot'), InlineKeyboardButton("🏓 Ping", callback_data='ping_menu')],
        [InlineKeyboardButton("🔐 Пароль", callback_data='pass_menu'), InlineKeyboardButton("📋 VPS", callback_data='listvps_menu')],
        [InlineKeyboardButton("❓ Помощь", callback_data='help')]
    ]
    await update.message.reply_text(
        f"👋 <b>Добро пожаловать, {update.effective_user.first_name}!</b>\nСервер: <b>{config.SERVER_NAME}</b>\n\nВыберите действие:",
        reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

# Команда /status
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update):
        return
    message = await update.message.reply_text("⏳ Получаю статус сервера...")
    status_text = await get_server_status()
    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data='back_to_menu')]]
    await message.edit_text(status_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

# Команда /update
async def update_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update):
        return
    await check_updates_and_ask(update, context)

async def check_updates_and_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = await update.message.reply_text("🔄 Проверяю доступные обновления...")
    update_count, package_list = await check_updates()
    if update_count == 0:
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data='back_to_menu')]]
        await message.edit_text("✅ <b>Система актуальна!</b>\n\nДоступных обновлений не найдено.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        return
    updates_text = f"📦 <b>Доступно обновлений: {update_count}</b>\n\n"
    if package_list:
        updates_text += "📋 <b>Некоторые пакеты:</b>\n"
        for pkg in package_list[:5]:
            updates_text += f"• <code>{pkg}</code>\n"
        if update_count > 5:
            updates_text += f"• ... и ещё {update_count - 5}\n"
    updates_text += "\n❓ Установить обновления?"
    keyboard = [[InlineKeyboardButton("✅ Да, установить", callback_data='confirm_update'), InlineKeyboardButton("❌ Нет", callback_data='back_to_menu')]]
    await message.edit_text(updates_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

# Команда /reboot
async def reboot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update):
        return
    keyboard = [[InlineKeyboardButton("✅ Да", callback_data='confirm_reboot'), InlineKeyboardButton("❌ Нет", callback_data='back_to_menu')]]
    await update.message.reply_text(
        "⚠️ <b>ВНИМАНИЕ!</b>\nВы действительно хотите перезагрузить сервер?\n\n• Все соединения будут разорваны\n• Сервер будет недоступен ~1 минуту",
        reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

# Команда /ping
async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update):
        return
    args = context.args
    if not args:
        keyboard = [
            [InlineKeyboardButton("🌍 Google (8.8.8.8)", callback_data='ping_google')],
            [InlineKeyboardButton("🌐 Cloudflare (1.1.1.1)", callback_data='ping_cloudflare')],
            [InlineKeyboardButton("🏠 Локальный (127.0.0.1)", callback_data='ping_local')],
            [InlineKeyboardButton("📦 Свой хост", callback_data='ping_custom')],
            [InlineKeyboardButton("◀️ Назад", callback_data='back_to_menu')]
        ]
        await update.message.reply_text("🏓 <b>Тест Ping</b>\n\nВыберите хост:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        return
    await ping_host(update, context, args[0])

async def ping_host(update: Update, context: ContextTypes.DEFAULT_TYPE, host: str, message=None):
    msg = message or await update.message.reply_text(f"🏓 Пингую {host}...")
    stdout, stderr = await run_command(f"ping -c 4 {host} 2>&1")
    if stderr and "unknown host" in stderr.lower():
        result = f"❌ Хост <b>{host}</b> не найден!"
    elif stdout:
        lines = stdout.split('\n')
        summary = [line for line in lines if 'bytes from' in line or 'statistics' in line or 'packet loss' in line]
        result = f"🏓 <b>Результаты пинга {host}:</b>\n━━━━━━━━━━━━━━━━━━━━━\n<pre>{chr(10).join(summary)}</pre>" if summary else f"<pre>{stdout}</pre>"
    else:
        result = f"❌ Ошибка при пинге {host}"
    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data='ping_menu')]]
    await msg.edit_text(result, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

# Команда /password
async def password_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update):
        return
    args = context.args
    if not args:
        keyboard = [
            [InlineKeyboardButton("8", callback_data='pass_8'), InlineKeyboardButton("12", callback_data='pass_12'), InlineKeyboardButton("16", callback_data='pass_16')],
            [InlineKeyboardButton("20", callback_data='pass_20'), InlineKeyboardButton("24", callback_data='pass_24'), InlineKeyboardButton("32", callback_data='pass_32')],
            [InlineKeyboardButton("🎲 Случайная", callback_data='pass_random'), InlineKeyboardButton("⚙️ Своя", callback_data='pass_custom')],
            [InlineKeyboardButton("◀️ Назад", callback_data='back_to_menu')]
        ]
        await update.message.reply_text("🔐 <b>Генератор паролей</b>\n\nВыберите длину пароля:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    else:
        try:
            length = int(args[0])
            if length < 4: length = 4
            if length > 64: length = 64
            alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
            password = ''.join(secrets.choice(alphabet) for _ in range(length))
            strength = "💪 Слабый"
            if length >= 12 and any(c in "!@#$%^&*" for c in password) and any(c.isupper() for c in password) and any(c.islower() for c in password):
                strength = "🛡️ Сильный"
            result = f"🔐 <b>Пароль ({length} символов):</b>\n━━━━━━━━━━━━━━━━━━━━━\n<code>{password}</code>\n\nСложность: {strength}\nСимволов: {len(password)}"
            keyboard_back = [[InlineKeyboardButton("◀️ Назад", callback_data='pass_menu')]]
            await update.message.reply_text(result, reply_markup=InlineKeyboardMarkup(keyboard_back), parse_mode='HTML')
        except ValueError:
            await update.message.reply_text("❌ Пожалуйста, укажите число (например: /password 16)")

# Команда /addvps
async def add_vps_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update):
        return
    
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "❌ Использование: /addvps <название> <дата ГГГГ-ММ-ДД> [дни для уведомлений]\n\n"
            "Пример: /addvps MyVPS 2026-12-31\n"
            "По умолчанию уведомления за: 14,10,8,4,2,1 дней"
        )
        return
    
    name = args[0]
    try:
        expiry_date = args[1]
        datetime.strptime(expiry_date, '%Y-%m-%d')
        notify_days = args[2] if len(args) > 2 else '14,10,8,4,2,1'
        add_vps(name, expiry_date, notify_days)
        await update.message.reply_text(
            f"✅ VPS <b>{name}</b> добавлен\n"
            f"Дата окончания: {expiry_date}\n"
            f"Уведомления за: {notify_days} дней",
            parse_mode='HTML'
        )
    except ValueError:
        await update.message.reply_text("❌ Неверный формат даты. Используйте ГГГГ-ММ-ДД")

# Команда /listvps
async def list_vps_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update):
        return
    
    vps_list = get_vps_list()
    
    if not vps_list:
        await update.message.reply_text("📭 Список VPS пуст. Добавьте командой /addvps")
        return
    
    keyboard = []
    for vps_id, name, expiry_date, notify_days, last_notify in vps_list:
        expiry = datetime.strptime(expiry_date, '%Y-%m-%d').date()
        days_left = (expiry - datetime.now().date()).days
        status = "❌" if days_left < 0 else "⚠️" if days_left <= 14 else "✅"
        keyboard.append([InlineKeyboardButton(
            f"{status} {name} (до {expiry_date}, осталось {days_left} дн.)",
            callback_data=f'vps_details_{vps_id}'
        )])
    
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data='back_to_menu')])
    
    await update.message.reply_text(
        "📋 <b>Ваши VPS серверы:</b>\n\nВыберите для управления:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )

# Команда /test
async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update):
        return
    await update.message.reply_text("🔄 Тестирую выполнение команд...")
    stdout, stderr = await run_command("whoami")
    await update.message.reply_text(f"👤 Текущий пользователь: {stdout.strip()}")
    stdout, stderr = await run_command("sudo -n true 2>&1")
    await update.message.reply_text("✅ Sudo работает без пароля" if not stderr else f"❌ Ошибка sudo: {stderr}")

# Команда /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update):
        return
    help_text = """🤖 <b>Доступные команды:</b>

/start - Главное меню
/status - Статус сервера
/update - Проверка и установка обновлений
/reboot - Перезагрузка сервера
/ping [хост] - Тест ping
/password [длина] - Генератор паролей
/test - Проверка работы команд

<b>Управление VPS:</b>
/addvps - Добавить VPS для отслеживания
/listvps - Список VPS
/help - Эта справка"""
    await update.message.reply_text(help_text, parse_mode='HTML')

# Обработчик кнопок
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if str(query.from_user.id) != config.ADMIN_CHAT_ID:
        await query.edit_message_text("⛔ У вас нет прав.")
        return
    
    # Статус
    if query.data == 'status':
        await query.edit_message_text("⏳ Получаю статус...")
        status_text = await get_server_status()
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data='back_to_menu')]]
        await query.edit_message_text(status_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    # Проверка обновлений
    elif query.data == 'check_updates':
        await query.edit_message_text("🔄 Проверяю доступные обновления...")
        update_count, package_list = await check_updates()
        if update_count == 0:
            keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data='back_to_menu')]]
            await query.edit_message_text("✅ <b>Система актуальна!</b>\n\nДоступных обновлений не найдено.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
            return
        updates_text = f"📦 <b>Доступно обновлений: {update_count}</b>\n\n"
        if package_list:
            updates_text += "📋 <b>Некоторые пакеты:</b>\n"
            for pkg in package_list[:5]:
                updates_text += f"• <code>{pkg}</code>\n"
            if update_count > 5:
                updates_text += f"• ... и ещё {update_count - 5}\n"
        updates_text += "\n❓ Установить обновления?"
        keyboard = [[InlineKeyboardButton("✅ Да, установить", callback_data='confirm_update'), InlineKeyboardButton("❌ Нет", callback_data='back_to_menu')]]
        await query.edit_message_text(updates_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    # Подтверждение установки обновлений
    elif query.data == 'confirm_update':
        await query.edit_message_text("🔄 Начинаю обновление сервера...\nЭто может занять несколько минут.")
        commands = ["sudo apt update", "sudo apt upgrade -y", "sudo apt autoremove -y", "sudo apt autoclean"]
        results = []
        for cmd in commands:
            stdout, stderr = await run_command(cmd)
            results.append(f"✅ {cmd}" if not stderr else f"❌ {cmd}")
        reboot_needed, _ = await run_command("[ -f /var/run/reboot-required ] && echo 'yes' || echo 'no'")
        result_text = "✅ <b>Обновление завершено!</b>\n\n" + "\n".join(results)
        if 'yes' in reboot_needed:
            result_text += "\n\n⚠️ <b>Требуется перезагрузка!</b>"
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data='back_to_menu')]]
        await query.edit_message_text(result_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    # Перезагрузка
    elif query.data == 'reboot':
        keyboard = [[InlineKeyboardButton("✅ Да", callback_data='confirm_reboot'), InlineKeyboardButton("❌ Нет", callback_data='back_to_menu')]]
        await query.edit_message_text("⚠️ <b>Подтвердите перезагрузку</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    elif query.data == 'confirm_reboot':
        await query.edit_message_text("🔄 Перезагрузка сервера началась...\nСервер будет недоступен около минуты.")
        await context.bot.send_message(chat_id=config.ADMIN_CHAT_ID, text=f"🔄 <b>{config.SERVER_NAME}</b>: Сервер перезагружается...", parse_mode='HTML')
        await asyncio.sleep(2)
        await run_command("sudo /sbin/reboot")
    
    # Ping меню
    elif query.data == 'ping_menu':
        keyboard = [
            [InlineKeyboardButton("🌍 Google (8.8.8.8)", callback_data='ping_google')],
            [InlineKeyboardButton("🌐 Cloudflare (1.1.1.1)", callback_data='ping_cloudflare')],
            [InlineKeyboardButton("🏠 Локальный (127.0.0.1)", callback_data='ping_local')],
            [InlineKeyboardButton("📦 Свой хост", callback_data='ping_custom')],
            [InlineKeyboardButton("◀️ Назад", callback_data='back_to_menu')]
        ]
        await query.edit_message_text("🏓 <b>Тест Ping</b>\n\nВыберите хост:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    elif query.data in ['ping_google', 'ping_cloudflare', 'ping_local']:
        hosts = {'ping_google': '8.8.8.8', 'ping_cloudflare': '1.1.1.1', 'ping_local': '127.0.0.1'}
        host = hosts[query.data]
        await query.edit_message_text(f"🏓 Пингую {host}...")
        await ping_host(update, context, host, query.message)
    
    elif query.data == 'ping_custom':
        await query.edit_message_text(
            "🏓 <b>Свой хост</b>\n\nОтправьте команду:\n<code>/ping &lt;адрес&gt;</code>\n\nНапример:\n• <code>/ping yandex.ru</code>\n• <code>/ping github.com</code>",
            parse_mode='HTML')
    
    # Пароль меню
    elif query.data == 'pass_menu':
        keyboard = [
            [InlineKeyboardButton("8", callback_data='pass_8'), InlineKeyboardButton("12", callback_data='pass_12'), InlineKeyboardButton("16", callback_data='pass_16')],
            [InlineKeyboardButton("20", callback_data='pass_20'), InlineKeyboardButton("24", callback_data='pass_24'), InlineKeyboardButton("32", callback_data='pass_32')],
            [InlineKeyboardButton("🎲 Случайная", callback_data='pass_random'), InlineKeyboardButton("⚙️ Своя", callback_data='pass_custom')],
            [InlineKeyboardButton("◀️ Назад", callback_data='back_to_menu')]
        ]
        await query.edit_message_text("🔐 <b>Генератор паролей</b>\n\nВыберите длину:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    elif query.data.startswith('pass_'):
        length = {'pass_8':8, 'pass_12':12, 'pass_16':16, 'pass_20':20, 'pass_24':24, 'pass_32':32, 'pass_random': secrets.choice([8,12,16,20,24,32])}.get(query.data)
        if not length:
            if query.data == 'pass_custom':
                await query.edit_message_text("🔐 Отправьте /password <число>", parse_mode='HTML')
            return
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        password = ''.join(secrets.choice(alphabet) for _ in range(length))
        strength = "💪 Слабый"
        if length >= 12 and any(c in "!@#$%^&*" for c in password) and any(c.isupper() for c in password) and any(c.islower() for c in password):
            strength = "🛡️ Сильный"
        result = f"🔐 <b>Пароль ({length} символов):</b>\n━━━━━━━━━━━━━━━━━━━━━\n<code>{password}</code>\n\nСложность: {strength}\nСимволов: {len(password)}"
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data='pass_menu')]]
        await query.edit_message_text(result, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    # VPS меню
    elif query.data == 'listvps_menu':
        vps_list = get_vps_list()
        if not vps_list:
            await query.edit_message_text("📭 Список VPS пуст. Добавьте командой /addvps")
            return
        keyboard = []
        for vps_id, name, expiry_date, notify_days, last_notify in vps_list:
            expiry = datetime.strptime(expiry_date, '%Y-%m-%d').date()
            days_left = (expiry - datetime.now().date()).days
            status = "❌" if days_left < 0 else "⚠️" if days_left <= 14 else "✅"
            keyboard.append([InlineKeyboardButton(
                f"{status} {name} (до {expiry_date}, осталось {days_left} дн.)",
                callback_data=f'vps_details_{vps_id}'
            )])
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data='back_to_menu')])
        await query.edit_message_text(
            "📋 <b>Ваши VPS серверы:</b>\n\nВыберите для управления:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data.startswith('vps_details_'):
        vps_id = query.data.split('_')[2]
        vps_list = get_vps_list()
        vps = next((v for v in vps_list if str(v[0]) == vps_id), None)
        if not vps:
            await query.edit_message_text("❌ VPS не найден")
            return
        vps_id, name, expiry_date, notify_days, last_notify = vps
        expiry = datetime.strptime(expiry_date, '%Y-%m-%d').date()
        days_left = (expiry - datetime.now().date()).days
        details = f"📊 <b>Информация о VPS</b>\n\n"
        details += f"Имя: {name}\n"
        details += f"ID: {vps_id}\n"
        details += f"Дата окончания: {expiry_date}\n"
        details += f"Осталось дней: {days_left}\n"
        details += f"Уведомления за: {notify_days} дн.\n"
        keyboard = [
            [InlineKeyboardButton("✅ Продлено", callback_data=f'renew_vps_{vps_id}')],
            [InlineKeyboardButton("❌ Удалить", callback_data=f'delete_vps_{vps_id}')],
            [InlineKeyboardButton("◀️ Назад", callback_data='listvps_menu')]
        ]
        await query.edit_message_text(details, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    elif query.data.startswith('renew_vps_'):
        vps_id = query.data.split('_')[2]
        keyboard = [
            [InlineKeyboardButton("1 месяц", callback_data=f'renew_period_{vps_id}_1'),
             InlineKeyboardButton("3 месяца", callback_data=f'renew_period_{vps_id}_3')],
            [InlineKeyboardButton("6 месяцев", callback_data=f'renew_period_{vps_id}_6'),
             InlineKeyboardButton("12 месяцев", callback_data=f'renew_period_{vps_id}_12')],
            [InlineKeyboardButton("◀️ Назад", callback_data=f'vps_details_{vps_id}')]
        ]
        await query.edit_message_text(
            f"📅 Выберите срок продления:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data.startswith('renew_period_'):
        parts = query.data.split('_')
        vps_id = parts[2]
        months = int(parts[3])
        today = datetime.now().date()
        if months == 1:
            new_date = today + timedelta(days=30)
        elif months == 3:
            new_date = today + timedelta(days=90)
        elif months == 6:
            new_date = today + timedelta(days=180)
        elif months == 12:
            new_date = today + timedelta(days=365)
        new_date_str = new_date.strftime('%Y-%m-%d')
        update_vps_date(vps_id, new_date_str)
        vps_list = get_vps_list()
        vps_name = next((v[1] for v in vps_list if str(v[0]) == vps_id), f"VPS #{vps_id}")
        month_word = "месяц" if months == 1 else "месяца" if months in [2,3,4] else "месяцев"
        await query.edit_message_text(
            f"✅ <b>Срок аренды продлён!</b>\n\n"
            f"Сервер: {vps_name}\n"
            f"Новая дата окончания: {new_date_str}\n"
            f"Срок: {months} {month_word}\n\n"
            f"Напоминания будут приходить за:\n"
            f"14, 10, 8, 4, 2, 1 день до новой даты.",
            parse_mode='HTML'
        )
    
    elif query.data.startswith('delete_vps_'):
        vps_id = query.data.split('_')[2]
        keyboard = [
            [InlineKeyboardButton("✅ Да, удалить", callback_data=f'confirm_delete_{vps_id}'),
             InlineKeyboardButton("❌ Нет", callback_data=f'vps_details_{vps_id}')]
        ]
        await query.edit_message_text(
            f"⚠️ Вы уверены, что хотите удалить VPS #{vps_id}?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data.startswith('confirm_delete_'):
        vps_id = query.data.split('_')[2]
        delete_vps(vps_id)
        await query.edit_message_text(f"✅ VPS #{vps_id} удалён из списка отслеживания", parse_mode='HTML')
    
    # Помощь
    elif query.data == 'help':
        help_text = "🤖 <b>Помощь</b>\n\n• 📊 Статус - информация о сервере\n• 🔄 Обновить - проверка и установка обновлений\n• 🔄 Перезагрузка - перезагрузка сервера\n• 🏓 Ping - проверка связи\n• 🔐 Пароль - генератор паролей\n• 📋 VPS - управление сроками аренды"
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data='back_to_menu')]]
        await query.edit_message_text(help_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    # Назад в меню
    elif query.data == 'back_to_menu':
        keyboard = [
            [InlineKeyboardButton("📊 Статус", callback_data='status'), InlineKeyboardButton("🔄 Обновить", callback_data='check_updates')],
            [InlineKeyboardButton("🔄 Перезагрузка", callback_data='reboot'), InlineKeyboardButton("🏓 Ping", callback_data='ping_menu')],
            [InlineKeyboardButton("🔐 Пароль", callback_data='pass_menu'), InlineKeyboardButton("📋 VPS", callback_data='listvps_menu')],
            [InlineKeyboardButton("❓ Помощь", callback_data='help')]
        ]
        await query.edit_message_text(f"👋 <b>Главное меню</b>\nСервер: {config.SERVER_NAME}", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

def main():
    # Инициализация базы данных
    init_db()
    
    # Создаем приложение
    application = Application.builder().token(config.TOKEN).build()
    
    # Добавляем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("update", update_command))
    application.add_handler(CommandHandler("reboot", reboot_command))
    application.add_handler(CommandHandler("ping", ping_command))
    application.add_handler(CommandHandler("password", password_command))
    application.add_handler(CommandHandler("test", test_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("addvps", add_vps_command))
    application.add_handler(CommandHandler("listvps", list_vps_command))
    
    # Обработчик кнопок
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Запуск периодической проверки сроков аренды (каждый день в 10:00)
    try:
        job_queue = application.job_queue
        if job_queue is not None:
            job_queue.run_daily(check_rental_expiry, time=datetime.time(hour=10, minute=0))
            print("✅ Планировщик задач для VPS запущен")
        else:
            print("⚠️ JobQueue не доступен, уведомления о VPS работать не будут")
    except Exception as e:
        print(f"⚠️ Ошибка при настройке планировщика: {e}")
    
    print(f"✅ Бот {config.SERVER_NAME} запущен")
    print(f"📋 Доступные команды: /start, /status, /update, /reboot, /ping, /password, /test, /help, /addvps, /listvps")
    
    # Запускаем бота
    application.run_polling()

if __name__ == '__main__':
    main()
