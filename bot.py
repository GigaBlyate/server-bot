#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import subprocess
import psutil
import platform
import secrets
import string
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import config

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
        
        stdout_str = stdout.decode('utf-8', errors='ignore') if stdout else ""
        stderr_str = stderr.decode('utf-8', errors='ignore') if stderr else ""
        
        return stdout_str, stderr_str
    except Exception as e:
        print(f"ERROR in run_command: {e}")
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
        
        status = f"""🖥️ <b>{config.SERVER_NAME}</b>
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
        return status
    except Exception as e:
        return f"❌ Ошибка получения статуса: {e}"

# Проверка доступных обновлений
async def check_updates():
    stdout, stderr = await run_command("sudo apt update 2>&1")
    
    # Проверяем, есть ли пакеты для обновления
    upgrade_check, _ = await run_command("sudo apt list --upgradable 2>/dev/null | grep -c upgradable")
    
    try:
        update_count = int(upgrade_check.strip())
    except:
        update_count = 0
    
    # Получаем список обновлений (первые 10 для отображения)
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
        [
            InlineKeyboardButton("📊 Статус", callback_data='status'),
            InlineKeyboardButton("🔄 Обновить", callback_data='check_updates')
        ],
        [
            InlineKeyboardButton("🔄 Перезагрузка", callback_data='reboot'),
            InlineKeyboardButton("🏓 Ping", callback_data='ping_menu')
        ],
        [
            InlineKeyboardButton("🔐 Пароль", callback_data='pass_menu'),
            InlineKeyboardButton("❓ Помощь", callback_data='help')
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"👋 <b>Добро пожаловать, {update.effective_user.first_name}!</b>\n"
        f"Сервер: <b>{config.SERVER_NAME}</b>\n\n"
        f"Выберите действие:",
        reply_markup=reply_markup,
        parse_mode='HTML'
    )

# Команда /status
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update):
        return
    
    message = await update.message.reply_text("⏳ Получаю статус сервера...")
    status_text = await get_server_status()
    
    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data='back_to_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await message.edit_text(status_text, reply_markup=reply_markup, parse_mode='HTML')

# Команда /update
async def update_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update):
        return
    
    await check_updates_and_ask(update, context)

async def check_updates_and_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет обновления и спрашивает, устанавливать ли"""
    message = await update.message.reply_text("🔄 Проверяю доступные обновления...")
    
    update_count, package_list = await check_updates()
    
    if update_count == 0:
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data='back_to_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await message.edit_text(
            "✅ <b>Система актуальна!</b>\n\n"
            "Доступных обновлений не найдено.",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        return
    
    # Формируем сообщение со списком обновлений
    updates_text = f"📦 <b>Доступно обновлений: {update_count}</b>\n\n"
    
    if package_list:
        updates_text += "📋 <b>Некоторые пакеты:</b>\n"
        for pkg in package_list[:5]:
            updates_text += f"• <code>{pkg}</code>\n"
        if update_count > 5:
            updates_text += f"• ... и ещё {update_count - 5}\n"
    
    updates_text += "\n❓ Установить обновления?"
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Да, установить", callback_data='confirm_update'),
            InlineKeyboardButton("❌ Нет", callback_data='back_to_menu')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await message.edit_text(updates_text, reply_markup=reply_markup, parse_mode='HTML')

# Команда /reboot
async def reboot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update):
        return
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Да", callback_data='confirm_reboot'),
            InlineKeyboardButton("❌ Нет", callback_data='back_to_menu')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "⚠️ <b>ВНИМАНИЕ!</b>\n"
        "Вы действительно хотите перезагрузить сервер?\n\n"
        "• Все соединения будут разорваны\n"
        "• Сервер будет недоступен ~1 минуту",
        reply_markup=reply_markup,
        parse_mode='HTML'
    )

# Функция для пинга
async def ping_host(update: Update, context: ContextTypes.DEFAULT_TYPE, host: str, message=None):
    """Функция для выполнения пинга"""
    if message:
        msg = message
    else:
        msg = await update.message.reply_text(f"🏓 Пингую {host}...")
    
    stdout, stderr = await run_command(f"ping -c 4 {host} 2>&1")
    
    if stderr and "Operation not permitted" in stderr:
        stdout, stderr = await run_command(f"sudo ping -c 4 {host} 2>&1")
    
    if stderr and ("unknown host" in stderr.lower() or "not known" in stderr.lower() or "Name or service not known" in stderr):
        result = f"❌ Хост <b>{host}</b> не найден!"
    elif stdout:
        lines = stdout.split('\n')
        summary = []
        for line in lines:
            if 'bytes from' in line or 'statistics' in line or 'packet loss' in line or 'min/avg/max' in line or 'rtt' in line:
                summary.append(line)
        
        if summary:
            result = f"🏓 <b>Результаты пинга {host}:</b>\n"
            result += "━━━━━━━━━━━━━━━━━━━━━\n"
            result += f"<pre>{chr(10).join(summary)}</pre>"
        else:
            result = f"🏓 <b>Результаты пинга {host}:</b>\n"
            result += "━━━━━━━━━━━━━━━━━━━━━\n"
            result += f"<pre>{stdout}</pre>"
    else:
        result = f"❌ Ошибка при пинге {host}"
    
    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data='ping_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await msg.edit_text(result, reply_markup=reply_markup, parse_mode='HTML')

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
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "🏓 <b>Тест Ping</b>\n\n"
            "Выберите хост для проверки связи:",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        return
    
    host = args[0]
    await ping_host(update, context, host)

# Команда /password
async def password_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update):
        return
    
    args = context.args
    
    keyboard = [
        [
            InlineKeyboardButton("8", callback_data='pass_8'),
            InlineKeyboardButton("12", callback_data='pass_12'),
            InlineKeyboardButton("16", callback_data='pass_16')
        ],
        [
            InlineKeyboardButton("20", callback_data='pass_20'),
            InlineKeyboardButton("24", callback_data='pass_24'),
            InlineKeyboardButton("32", callback_data='pass_32')
        ],
        [
            InlineKeyboardButton("🎲 Случайная", callback_data='pass_random'),
            InlineKeyboardButton("⚙️ Своя", callback_data='pass_custom')
        ],
        [InlineKeyboardButton("◀️ Назад", callback_data='back_to_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if not args:
        await update.message.reply_text(
            "🔐 <b>Генератор паролей</b>\n\n"
            "Выберите длину пароля:",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
    else:
        try:
            length = int(args[0])
            if length < 4:
                length = 4
            elif length > 64:
                length = 64
            
            alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
            password = ''.join(secrets.choice(alphabet) for _ in range(length))
            
            strength = "💪 Слабый"
            if length >= 12:
                if any(c in "!@#$%^&*" for c in password):
                    if any(c.isupper() for c in password) and any(c.islower() for c in password):
                        strength = "🛡️ Сильный"
                    else:
                        strength = "👍 Средний"
                else:
                    strength = "👍 Средний"
            
            result = f"🔐 <b>Пароль ({length} символов):</b>\n"
            result += "━━━━━━━━━━━━━━━━━━━━━\n"
            result += f"<code>{password}</code>\n\n"
            result += f"Сложность: {strength}\n"
            result += f"Символов: {len(password)}"
            
            keyboard_back = [[InlineKeyboardButton("◀️ Назад", callback_data='pass_menu')]]
            await update.message.reply_text(result, reply_markup=InlineKeyboardMarkup(keyboard_back), parse_mode='HTML')
            
        except ValueError:
            await update.message.reply_text("❌ Пожалуйста, укажите число (например: /password 16)")

# Команда /test
async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update):
        return
    
    await update.message.reply_text("🔄 Тестирую выполнение команд...")
    
    stdout, stderr = await run_command("whoami")
    await update.message.reply_text(f"👤 Текущий пользователь: {stdout.strip()}")
    
    stdout, stderr = await run_command("sudo -n true 2>&1")
    if not stderr:
        await update.message.reply_text("✅ Sudo работает без пароля")
    else:
        await update.message.reply_text(f"❌ Ошибка sudo: {stderr}")

# Команда /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update):
        return
    
    help_text = """🤖 <b>Доступные команды:</b>

/start - Главное меню
/status - Статус сервера
/update - Проверка и установка обновлений
/reboot - Перезагрузка сервера
/ping [хост] - Тест ping (например: /ping google.com)
/password [длина] - Генерация пароля (например: /password 16)
/test - Проверка работы команд
/help - Эта справка

<b>Функции:</b>
• 📊 Статус - информация о сервере
• 🔄 Обновить - проверка и установка обновлений
• 🏓 Ping - проверка доступности хостов
• 🔐 Пароль - генерация безопасных паролей"""
    
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
            await query.edit_message_text(
                "✅ <b>Система актуальна!</b>\n\nДоступных обновлений не найдено.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )
            return
        
        updates_text = f"📦 <b>Доступно обновлений: {update_count}</b>\n\n"
        
        if package_list:
            updates_text += "📋 <b>Некоторые пакеты:</b>\n"
            for pkg in package_list[:5]:
                updates_text += f"• <code>{pkg}</code>\n"
            if update_count > 5:
                updates_text += f"• ... и ещё {update_count - 5}\n"
        
        updates_text += "\n❓ Установить обновления?"
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Да, установить", callback_data='confirm_update'),
                InlineKeyboardButton("❌ Нет", callback_data='back_to_menu')
            ]
        ]
        await query.edit_message_text(updates_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    # Подтверждение установки обновлений
    elif query.data == 'confirm_update':
        await query.edit_message_text("🔄 Начинаю обновление сервера...\nЭто может занять несколько минут.")
        
        commands = [
            "sudo apt update",
            "sudo apt upgrade -y",
            "sudo apt autoremove -y",
            "sudo apt autoclean"
        ]
        
        results = []
        for cmd in commands:
            stdout, stderr = await run_command(cmd)
            if stderr and "error" in stderr.lower():
                results.append(f"❌ {cmd}")
            else:
                results.append(f"✅ {cmd}")
        
        stdout, stderr = await run_command("[ -f /var/run/reboot-required ] && echo 'yes' || echo 'no'")
        reboot_needed = stdout.strip() if stdout else "no"
        
        result_text = "✅ <b>Обновление завершено!</b>\n\n"
        result_text += "\n".join(results)
        
        if 'yes' in reboot_needed:
            result_text += "\n\n⚠️ <b>Требуется перезагрузка!</b>"
        
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data='back_to_menu')]]
        await query.edit_message_text(result_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    # Перезагрузка
    elif query.data == 'reboot':
        keyboard = [
            [InlineKeyboardButton("✅ Да", callback_data='confirm_reboot'),
             InlineKeyboardButton("❌ Нет", callback_data='back_to_menu')]
        ]
        await query.edit_message_text(
            "⚠️ <b>Подтвердите перезагрузку</b>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data == 'confirm_reboot':
        await query.edit_message_text("🔄 Перезагрузка сервера началась...\nСервер будет недоступен около минуты.")
        
        await context.bot.send_message(
            chat_id=config.ADMIN_CHAT_ID,
            text=f"🔄 <b>{config.SERVER_NAME}</b>: Сервер перезагружается...",
            parse_mode='HTML'
        )
        
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
        await query.edit_message_text(
            "🏓 <b>Тест Ping</b>\n\nВыберите хост:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data == 'ping_google':
        await query.edit_message_text("🏓 Пингую Google (8.8.8.8)...")
        await ping_host(update, context, "8.8.8.8", query.message)
    
    elif query.data == 'ping_cloudflare':
        await query.edit_message_text("🏓 Пингую Cloudflare (1.1.1.1)...")
        await ping_host(update, context, "1.1.1.1", query.message)
    
    elif query.data == 'ping_local':
        await query.edit_message_text("🏓 Пингую локальный хост...")
        await ping_host(update, context, "127.0.0.1", query.message)
    
    elif query.data == 'ping_custom':
        await query.edit_message_text(
            "🏓 <b>Свой хост</b>\n\n"
            "Отправьте команду:\n"
            "<code>/ping &lt;адрес&gt;</code>\n\n"
            "Например:\n"
            "• <code>/ping yandex.ru</code>\n"
            "• <code>/ping github.com</code>\n"
            "• <code>/ping 192.168.1.1</code>",
            parse_mode='HTML'
        )
    
    # Пароль меню
    elif query.data == 'pass_menu':
        keyboard = [
            [InlineKeyboardButton("8", callback_data='pass_8'),
             InlineKeyboardButton("12", callback_data='pass_12'),
             InlineKeyboardButton("16", callback_data='pass_16')],
            [InlineKeyboardButton("20", callback_data='pass_20'),
             InlineKeyboardButton("24", callback_data='pass_24'),
             InlineKeyboardButton("32", callback_data='pass_32')],
            [InlineKeyboardButton("🎲 Случайная", callback_data='pass_random'),
             InlineKeyboardButton("⚙️ Своя", callback_data='pass_custom')],
            [InlineKeyboardButton("◀️ Назад", callback_data='back_to_menu')]
        ]
        await query.edit_message_text(
            "🔐 <b>Генератор паролей</b>\n\nВыберите длину:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    
    elif query.data.startswith('pass_'):
        if query.data == 'pass_8':
            length = 8
        elif query.data == 'pass_12':
            length = 12
        elif query.data == 'pass_16':
            length = 16
        elif query.data == 'pass_20':
            length = 20
        elif query.data == 'pass_24':
            length = 24
        elif query.data == 'pass_32':
            length = 32
        elif query.data == 'pass_random':
            length = secrets.choice([8, 12, 16, 20, 24, 32])
        elif query.data == 'pass_custom':
            await query.edit_message_text(
                "🔐 <b>Свой вариант</b>\n\n"
                "Отправьте команду:\n"
                "<code>/password &lt;число&gt;</code>\n\n"
                "Например:\n"
                "• <code>/password 15</code>\n"
                "• <code>/password 28</code>\n"
                "• <code>/password 40</code>",
                parse_mode='HTML'
            )
            return
        else:
            return
        
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        password = ''.join(secrets.choice(alphabet) for _ in range(length))
        
        strength = "💪 Слабый"
        if length >= 12:
            if any(c in "!@#$%^&*" for c in password):
                if any(c.isupper() for c in password) and any(c.islower() for c in password):
                    strength = "🛡️ Сильный"
                else:
                    strength = "👍 Средний"
            else:
                strength = "👍 Средний"
        
        result = f"🔐 <b>Пароль ({length} символов):</b>\n"
        result += "━━━━━━━━━━━━━━━━━━━━━\n"
        result += f"<code>{password}</code>\n\n"
        result += f"Сложность: {strength}\n"
        result += f"Символов: {len(password)}"
        
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data='pass_menu')]]
        await query.edit_message_text(result, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    # Помощь
    elif query.data == 'help':
        help_text = "🤖 <b>Помощь</b>\n\n• 📊 Статус - информация о сервере\n• 🔄 Обновить - проверка и установка обновлений\n• 🔄 Перезагрузка - перезагрузка сервера\n• 🏓 Ping - проверка связи\n• 🔐 Пароль - генератор паролей"
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data='back_to_menu')]]
        await query.edit_message_text(help_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    
    # Назад в меню
    elif query.data == 'back_to_menu':
        keyboard = [
            [
                InlineKeyboardButton("📊 Статус", callback_data='status'),
                InlineKeyboardButton("🔄 Обновить", callback_data='check_updates')
            ],
            [
                InlineKeyboardButton("🔄 Перезагрузка", callback_data='reboot'),
                InlineKeyboardButton("🏓 Ping", callback_data='ping_menu')
            ],
            [
                InlineKeyboardButton("🔐 Пароль", callback_data='pass_menu'),
                InlineKeyboardButton("❓ Помощь", callback_data='help')
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"👋 <b>Главное меню</b>\nСервер: {config.SERVER_NAME}",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )

def main():
    application = Application.builder().token(config.TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("update", update_command))
    application.add_handler(CommandHandler("reboot", reboot_command))
    application.add_handler(CommandHandler("ping", ping_command))
    application.add_handler(CommandHandler("password", password_command))
    application.add_handler(CommandHandler("test", test_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    print(f"✅ Бот {config.SERVER_NAME} запущен")
    print(f"📋 Доступные команды: /start, /status, /update, /reboot, /ping, /password, /test, /help")
    application.run_polling()

if __name__ == '__main__':
    main()
