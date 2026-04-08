#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import ipaddress
import logging
import os
import re
import shlex
import signal
from collections import defaultdict
from datetime import datetime
from functools import wraps
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)
security_logger = logging.getLogger('security')

user_last_command: Dict[str, float] = defaultdict(float)
user_command_count: Dict[str, List[float]] = defaultdict(list)
RATE_LIMIT_COOLDOWN = 2
RATE_LIMIT_MAX_CALLS = 10
RATE_LIMIT_PERIOD = 60

_HOSTNAME_RE = re.compile(
    r'^(?=.{1,253}$)(?!-)(?:[a-zA-Z0-9]'
    r'(?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)'
    r'(?:\.(?!-)(?:[a-zA-Z0-9]'
    r'(?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?))*$'
)
_GOOGLE_ID_RE = re.compile(r'^[A-Za-z0-9_-]{10,200}$')
_NOTIFY_DAYS_RE = re.compile(r'^\d+(?:,\d+)*$')
_CONTROL_CHARS_RE = re.compile(r'[\x00-\x1f\x7f]')


def rate_limit(func):
    """Throttle repetitive user actions."""

    @wraps(func)
    async def wrapper(update, context, *args, **kwargs):
        user = getattr(update, 'effective_user', None)
        if user is None:
            return await func(update, context, *args, **kwargs)

        user_id = str(user.id)
        now = datetime.now().timestamp()

        if now - user_last_command[user_id] < RATE_LIMIT_COOLDOWN:
            security_logger.warning('Rate limit cooldown for user %s', user_id)
            message = getattr(update, 'message', None)
            if message:
                await message.reply_text('⏳ Слишком часто. Подождите пару секунд.')
            return None
        user_last_command[user_id] = now

        user_calls = [t for t in user_command_count[user_id] if now - t < RATE_LIMIT_PERIOD]
        if len(user_calls) >= RATE_LIMIT_MAX_CALLS:
            security_logger.warning('Rate limit max calls for user %s', user_id)
            message = getattr(update, 'message', None)
            if message:
                await message.reply_text(
                    f'⏳ Слишком много запросов. Подождите {RATE_LIMIT_PERIOD} секунд.'
                )
            return None

        user_calls.append(now)
        user_command_count[user_id] = user_calls
        return await func(update, context, *args, **kwargs)

    return wrapper


def sanitize_path(path: str, allowed_prefixes: Optional[List[str]] = None) -> str:
    """Normalize a path and ensure it stays within allowed roots."""
    if not isinstance(path, str) or not path.strip():
        raise ValueError('Путь не указан')
    if '\x00' in path:
        raise ValueError('Путь содержит недопустимые символы')

    if allowed_prefixes is None:
        from config import ALLOWED_PATHS

        allowed_prefixes = ALLOWED_PATHS

    candidate = os.path.realpath(os.path.abspath(os.path.expanduser(path.strip())))
    normalized_allowed = [
        os.path.realpath(os.path.abspath(os.path.expanduser(prefix)))
        for prefix in allowed_prefixes
    ]

    for prefix in normalized_allowed:
        try:
            if os.path.commonpath([candidate, prefix]) == prefix:
                security_logger.info('Path validated: %s -> %s', path, candidate)
                return candidate
        except ValueError:
            continue

    security_logger.error('Path validation failed: %s -> %s', path, candidate)
    raise ValueError(f'Недопустимый путь: {path}. Разрешены только: {allowed_prefixes}')


def validate_hostname(host: str) -> bool:
    """Validate hostname, IPv4 or IPv6."""
    if not isinstance(host, str):
        return False

    host = host.strip()
    if not host or len(host) > 253 or any(ch.isspace() for ch in host):
        security_logger.warning('Host validation failed: %r', host)
        return False

    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass

    return bool(_HOSTNAME_RE.fullmatch(host))


def validate_google_drive_id(resource_id: str) -> bool:
    if not isinstance(resource_id, str):
        return False
    return bool(_GOOGLE_ID_RE.fullmatch(resource_id.strip()))


def validate_notify_days_list(value: str) -> bool:
    if not isinstance(value, str):
        return False
    value = value.strip()
    if not _NOTIFY_DAYS_RE.fullmatch(value):
        return False
    try:
        days = [int(item) for item in value.split(',')]
    except ValueError:
        return False
    return all(0 <= day <= 365 for day in days)


def escape_shell_arg(arg: str) -> str:
    return shlex.quote(str(arg))


async def _terminate_process_group(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None or proc.pid is None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except Exception:
        security_logger.exception('Failed to terminate process group %s', proc.pid)
        return

    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
        return
    except asyncio.TimeoutError:
        pass

    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except Exception:
        security_logger.exception('Failed to kill process group %s', proc.pid)
        return

    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except asyncio.TimeoutError:
        security_logger.error('Process group %s did not exit after SIGKILL', proc.pid)


async def safe_run_command(
    cmd_parts: List[str],
    timeout: int = 30,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
) -> Tuple[int, str, str]:
    """Run a command without shell and with strict timeout handling."""
    try:
        if not cmd_parts or not all(isinstance(part, str) and part for part in cmd_parts):
            raise ValueError('Команда должна быть непустым списком строк')

        proc = await asyncio.create_subprocess_exec(
            *cmd_parts,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
            start_new_session=True,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            await _terminate_process_group(proc)
            security_logger.error('Command timeout after %ss: %s', timeout, ' '.join(cmd_parts))
            return 124, '', f'Timeout after {timeout}s'

        return (
            int(proc.returncode or 0),
            out.decode('utf-8', errors='ignore'),
            err.decode('utf-8', errors='ignore'),
        )
    except Exception as exc:
        security_logger.error('Command execution error: %s', exc)
        return 1, '', str(exc)


async def safe_run_shell(cmd: str, timeout: int = 30) -> Tuple[int, str, str]:
    """Fallback shell execution for known internal workflows only."""
    if not isinstance(cmd, str) or not cmd.strip():
        return 1, '', 'Empty command'
    if '\x00' in cmd:
        return 1, '', 'Invalid null byte in command'
    security_logger.warning('safe_run_shell used: %s', cmd)
    return await safe_run_command(['/bin/bash', '-c', cmd], timeout=timeout)


def validate_and_clean_input(text: str, max_length: int = 1000) -> str:
    if text is None:
        return ''

    text = str(text)
    if len(text) > max_length:
        text = text[:max_length]

    text = _CONTROL_CHARS_RE.sub('', text)
    return text.strip()
