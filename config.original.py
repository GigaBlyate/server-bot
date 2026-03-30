#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_CHAT_ID = os.environ.get('ADMIN_ID')
SERVER_NAME = os.environ.get('SERVER_NAME', 'MyVPS')

ALLOWED_PATHS = ['/var/', '/home/', '/etc/', '/tmp/', '/opt/']
LOG_DIR = '/var/log/server-bot'
LOG_LEVEL = 'INFO'
BACKUP_DIR = os.path.join(os.path.dirname(__file__), 'backups')
