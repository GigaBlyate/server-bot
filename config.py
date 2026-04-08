#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.environ.get('BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
ADMIN_CHAT_ID = os.environ.get('ADMIN_ID', 'YOUR_ADMIN_ID_HERE')
SERVER_NAME = os.environ.get('SERVER_NAME', 'MyVPS')

ALLOWED_PATHS = [
    '/var',
    '/home',
    '/etc',
    '/tmp',
    '/opt',
    '/srv',
    '/root',
    '/usr/local',
    '/usr/lib',
    '/lib',
]

LOG_DIR = '/var/log/server-bot'
LOG_LEVEL = 'INFO'
BACKUP_DIR = os.path.join(os.path.dirname(__file__), 'backups')
PROJECT_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(PROJECT_DIR, 'vps_data.db')

# Private anonymous installation statistics
TELEMETRY_URL = os.environ.get('TELEMETRY_URL', '').strip().rstrip('/')
TELEMETRY_ENABLED = os.environ.get('TELEMETRY_ENABLED', 'true').strip().lower() == 'true'
TELEMETRY_TIMEOUT = int(os.environ.get('TELEMETRY_TIMEOUT', '10') or '10')
TELEMETRY_OWNER_TOKEN = os.environ.get('TELEMETRY_OWNER_TOKEN', '').strip()
SHOW_PROJECT_STATS = bool(TELEMETRY_OWNER_TOKEN)

ROOT_HELPER = os.environ.get('BOT_ROOT_HELPER', '/usr/local/bin/server-bot-rootctl')
