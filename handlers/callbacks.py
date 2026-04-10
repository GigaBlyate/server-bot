#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from telegram import Update
from telegram.ext import ContextTypes

from core.auth import ensure_admin_access
from handlers.backup import handle_backup_callback
from handlers.dashboard import cancel_dashboard_refresh, show_dashboard_callback
from handlers.info import show_certificates, show_info_menu, show_process_detail, show_process_list, show_server_info, show_top_processes
from handlers.password import handle_password_callback
from handlers.prosody import handle_prosody_callback, show_prosody_menu
from handlers.ping import ask_custom_ping, run_predefined_ping, show_ping_menu
from handlers.settings import handle_settings_callback, show_settings, show_traffic_menu
from handlers.system import handle_system_callback
from handlers.vps import handle_vps_callback


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_admin_access(update):
        return

    data = update.callback_query.data
    if data not in {'menu', 'refresh_dashboard'}:
        cancel_dashboard_refresh(context, update.callback_query.message.chat_id)
    if data in {'menu', 'refresh_dashboard'}:
        await show_dashboard_callback(update, context)
        return
    if data == 'info_menu':
        await show_info_menu(update, context)
        return
    if data == 'info_server':
        await show_server_info(update, context)
        return
    if data == 'info_certs':
        await show_certificates(update, context)
        return
    if data == 'info_top_processes':
        await show_top_processes(update, context)
        return
    if data == 'info_top_cpu':
        await show_process_list(update, context, 'cpu')
        return
    if data == 'info_top_ram':
        await show_process_list(update, context, 'ram')
        return
    if data.startswith('proc_pid_'):
        try:
            pid = int(data.split('_')[-1])
        except Exception:
            await update.callback_query.answer('Неверный PID')
            return
        await show_process_detail(update, context, pid)
        return
        return
        return
    if data == 'prosody_menu':
        await show_prosody_menu(update, context)
        return
    if data == 'ping_menu':
        await show_ping_menu(update, context)
        return
    if data == 'ping_run_quick':
        await run_predefined_ping(update, context, 'quick')
        return
    if data == 'ping_run_dns':
        await run_predefined_ping(update, context, 'dns')
        return
    if data == 'ping_run_regional':
        await run_predefined_ping(update, context, 'regional')
        return
    if data == 'ping_custom_prompt':
        await ask_custom_ping(update, context)
        return
    if await handle_password_callback(update, context, data):
        return
    if await handle_prosody_callback(update, context, data):
        return
    if await handle_vps_callback(update, context, data):
        return
    if await handle_backup_callback(update, context, data):
        return
    if await handle_settings_callback(update, context, data):
        return
    if await handle_system_callback(update, context, data):
        return
    if data == 'settings_menu':
        await show_settings(update, context)
        return
    if data == 'traffic_menu':
        await show_traffic_menu(update, context)
        return
    await update.callback_query.answer('Действие не обработано')