#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os
import re
import shutil
import time
from typing import List, Tuple

import config
from security import safe_run_command

logger = logging.getLogger(__name__)

_DOMAIN_RE = re.compile(r'^(?=.{1,253}$)(?!-)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(?:\.(?!-)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?))*$')
_JID_RE = re.compile(r'^[A-Za-z0-9._%+=-]+@[A-Za-z0-9.-]+$')


_PROSODY_DETECT_CACHE = {'value': None, 'expires': 0.0}


def is_prosody_installed() -> bool:
    now = time.time()
    if _PROSODY_DETECT_CACHE['expires'] > now and _PROSODY_DETECT_CACHE['value'] is not None:
        return bool(_PROSODY_DETECT_CACHE['value'])

    present = any(
        [
            shutil.which('prosodyctl') is not None,
            os.path.exists('/etc/prosody/prosody.cfg.lua'),
            os.path.isdir('/etc/prosody/conf.d'),
            os.path.exists('/lib/systemd/system/prosody.service'),
            os.path.exists('/etc/systemd/system/prosody.service'),
        ]
    )
    _PROSODY_DETECT_CACHE['value'] = bool(present)
    _PROSODY_DETECT_CACHE['expires'] = now + 60
    return bool(present)


def _root_helper(*args: str) -> List[str]:
    return ['sudo', config.ROOT_HELPER, *args]


def validate_domain(domain: str) -> bool:
    return bool(_DOMAIN_RE.fullmatch((domain or '').strip()))


def validate_jid(jid: str) -> bool:
    return bool(_JID_RE.fullmatch((jid or '').strip()))


async def get_domains() -> Tuple[bool, List[str], str]:
    code, out, err = await safe_run_command(_root_helper('prosody-domains'), timeout=20)
    raw = (out or err or '').strip()
    if code != 0:
        return False, [], raw or 'Не удалось получить список доменов Prosody.'
    domains = []
    for line in raw.splitlines():
        item = line.strip().lower()
        if item and validate_domain(item) and item not in domains:
            domains.append(item)
    return True, domains, raw


async def list_users(domain: str) -> Tuple[bool, List[str], str]:
    host = (domain or '').strip().lower()
    if not validate_domain(host):
        return False, [], 'Некорректный домен.'
    code, out, err = await safe_run_command(_root_helper('prosody-list-users', host), timeout=30)
    raw = (out or err or '').strip()
    if code != 0:
        return False, [], raw or 'Не удалось получить список клиентов Prosody.'
    users: List[str] = []
    jid_pattern = re.compile(rf'([A-Za-z0-9._%+=-]+@{re.escape(host)})', re.IGNORECASE)
    user_pattern = re.compile(r'^[A-Za-z0-9._%+=-]+$')
    for line in raw.splitlines():
        clean = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', line).strip().strip('"\'"`[](),')
        if not clean:
            continue
        found = jid_pattern.findall(clean)
        if found:
            for jid in found:
                jid_norm = jid.lower()
                if jid_norm not in users:
                    users.append(jid_norm)
            continue
        if '@' not in clean and user_pattern.fullmatch(clean):
            jid = f'{clean.lower()}@{host}'
            if jid not in users:
                users.append(jid)
    return True, users, raw


async def add_user(jid: str, password: str) -> Tuple[bool, str]:
    login = (jid or '').strip().lower()
    if not validate_jid(login):
        return False, 'Некорректный JID. Используйте формат user@domain.'
    if not password:
        return False, 'Пароль пустой.'
    code, out, err = await safe_run_command(_root_helper('prosody-add-user', login, password), timeout=30)
    raw = (out or err or '').strip()
    ok = code == 0 and 'error' not in raw.lower()
    return ok, (raw or ('Клиент Prosody добавлен.' if ok else 'Не удалось добавить клиента Prosody.'))


async def delete_user(jid: str) -> Tuple[bool, str]:
    login = (jid or '').strip().lower()
    if not validate_jid(login):
        return False, 'Некорректный JID. Используйте формат user@domain.'
    code, out, err = await safe_run_command(_root_helper('prosody-delete-user', login), timeout=30)
    raw = (out or err or '').strip()
    ok = code == 0 and 'error' not in raw.lower()
    return ok, (raw or ('Клиент Prosody удалён.' if ok else 'Не удалось удалить клиента Prosody.'))


async def set_password(jid: str, password: str) -> Tuple[bool, str]:
    login = (jid or '').strip().lower()
    if not validate_jid(login):
        return False, 'Некорректный JID. Используйте формат user@domain.'
    if not password:
        return False, 'Пароль пустой.'
    code, out, err = await safe_run_command(_root_helper('prosody-set-password', login, password), timeout=30)
    raw = (out or err or '').strip()
    ok = code == 0 and 'error' not in raw.lower()
    return ok, (raw or ('Пароль клиента Prosody обновлён.' if ok else 'Не удалось обновить пароль клиента Prosody.'))


async def restart_prosody() -> Tuple[bool, str]:
    code, out, err = await safe_run_command(_root_helper('prosody-restart'), timeout=20)
    raw = (out or err or '').strip()
    return code == 0, raw or ('Prosody перезапущен.' if code == 0 else 'Не удалось перезапустить Prosody.')


async def update_prosody() -> Tuple[bool, str]:
    code, out, err = await safe_run_command(_root_helper('prosody-update'), timeout=1800)
    raw = (out or err or '').strip()
    return code == 0, raw or ('Prosody обновлён.' if code == 0 else 'Не удалось обновить Prosody.')
