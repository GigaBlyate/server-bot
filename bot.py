#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import re
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
from core.auth import ensure_admin_access
from core.db import init_db
from core.errors import error_handler
from core.scheduler import setup_jobs
from handlers.backup import show_backup_menu
from handlers.callbacks import callback_router
from handlers.dashboard import send_dashboard_to_chat, start_command, status_command
from handlers.ping import show_ping_menu
from handlers.system import clear_reboot_marker, read_reboot_marker, reboot_command, update_system_command
from handlers.text_input import text_router
from handlers.vps import show_vps_menu
from security import rate_limit

LOG_PATH = Path(config.LOG_DIR)
LOG_PATH.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_PATH / 'bot.log'),
        logging.StreamHandler(),
    ],
)


class SecretRedactionFilter(logging.Filter):
    _patterns = [
        re.compile(r'(https://api\.telegram\.org/bot)([^/\s"]+)', re.IGNORECASE),
        re.compile(r"(BOT_TOKEN[=:\s]+)([^\s\"']+)", re.IGNORECASE),
        re.compile(r"(Authorization[=:\s]+Bearer\s+)([^\s\"']+)", re.IGNORECASE),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        redacted = message
        for pattern in self._patterns:
            redacted = pattern.sub(r'\1<redacted>', redacted)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


for _handler in logging.getLogger().handlers:
    _handler.addFilter(SecretRedactionFilter())

logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


@rate_limit
async def start_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_admin_access(update):
        return
    await start_command(update, context)


@rate_limit
async def status_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_admin_access(update):
        return
    await status_command(update, context)


@rate_limit
async def update_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_admin_access(update):
        return
    await update_system_command(update, context)


@rate_limit
async def reboot_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_admin_access(update):
        return
    await reboot_command(update, context)


@rate_limit
async def ping_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_admin_access(update):
        return
    await show_ping_menu(update, context)


@rate_limit
async def backup_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_admin_access(update):
        return
    await show_backup_menu(update, context)


@rate_limit
async def vps_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_admin_access(update):
        return
    await show_vps_menu(update, context)


@rate_limit
async def password_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_admin_access(update):
        return
    from ui.keyboards import password_keyboard

    await update.message.reply_text(
        '🔐 Выберите длину пароля.',
        reply_markup=password_keyboard(),
    )


@rate_limit
async def add_vps_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_admin_access(update):
        return
    context.user_data['awaiting'] = 'vps_name'
    await update.message.reply_text('✍️ Введите название VPS одним сообщением.')


@rate_limit
async def list_vps_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_admin_access(update):
        return
    await show_vps_menu(update, context)



@rate_limit
async def help_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_admin_access(update):
        return
    await update.message.reply_text(
        'Главные команды:\n'
        '/start — главное меню\n'
        '/status — та же главная сводка\n'
        '/update — проверка обновлений системы\n'
        '/backup — меню бэкапов\n'
        '/reboot — перезагрузка\n\n'
        'Основная работа вынесена в главное меню кнопками.',
    )


async def _send_post_reboot_notification(context: ContextTypes.DEFAULT_TYPE) -> None:
    marker = read_reboot_marker()
    if not marker:
        return
    chat_id = int(marker.get('admin_id') or 0)
    first_name = marker.get('first_name') or 'Администратор'
    action = str(marker.get('action') or 'reboot')
    clear_reboot_marker()
    if chat_id <= 0:
        return

    if action == 'bot_restart_after_update':
        await context.bot.send_message(
            chat_id=chat_id,
            text='✅ Обновление завершено. Бот успешно перезапущен. Открываю главное меню...',
        )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text='✅ Сервер успешно перезагружен. Поднимаю главное меню...',
        )

    if context.job_queue is not None:
        context.job_queue.run_once(
            _send_dashboard_after_reboot,
            when=4,
            data={'chat_id': chat_id, 'first_name': first_name},
            name='post-reboot-dashboard',
        )


async def _send_dashboard_after_reboot(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data
    await send_dashboard_to_chat(
        context,
        int(data['chat_id']),
        str(data.get('first_name') or 'Администратор'),
    )


async def post_init(application: Application) -> None:
    application.bot_data['admin_id'] = str(config.ADMIN_CHAT_ID)
    setup_jobs(application)
    logger.info('Bot post-init completed')
    if application.job_queue is not None:
        application.job_queue.run_once(_send_post_reboot_notification, when=2)



def main() -> None:
    init_db()
    if config.TOKEN == 'YOUR_BOT_TOKEN_HERE':
        raise RuntimeError('Set BOT_TOKEN in .env before running the bot.')

    application = Application.builder().token(config.TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler('start', start_wrapper))
    application.add_handler(CommandHandler('status', status_wrapper))
    application.add_handler(CommandHandler('update', update_wrapper))
    application.add_handler(CommandHandler('reboot', reboot_wrapper))
    application.add_handler(CommandHandler('ping', ping_wrapper))
    application.add_handler(CommandHandler('backup', backup_wrapper))
    application.add_handler(CommandHandler('vps', vps_wrapper))
    application.add_handler(CommandHandler('addvps', add_vps_wrapper))
    application.add_handler(CommandHandler('listvps', list_vps_wrapper))
    application.add_handler(CommandHandler('password', password_wrapper))
    application.add_handler(CommandHandler('help', help_wrapper))

    application.add_handler(CallbackQueryHandler(callback_router))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    application.add_error_handler(error_handler)

    logger.info('Starting bot version %s', (Path(config.PROJECT_DIR) / 'version.txt').read_text(encoding='utf-8').strip() if (Path(config.PROJECT_DIR) / 'version.txt').exists() else 'unknown')
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
