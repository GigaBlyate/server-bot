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


ROOT_HELPER = os.environ.get('BOT_ROOT_HELPER', '/usr/local/bin/server-bot-rootctl')
