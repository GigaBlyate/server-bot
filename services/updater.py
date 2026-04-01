#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import config
from security import safe_run_command

logger = logging.getLogger(__name__)
ProgressCb = Optional[Callable[[str], None]]


def _root_helper(action: str) -> List[str]:
    return ['sudo', config.ROOT_HELPER, action]


def get_current_version() -> str:
    try:
        with open(f"{config.PROJECT_DIR}/version.txt", "r", encoding="utf-8") as handle:
            return handle.read().strip() or "unknown"
    except Exception:
        return "unknown"


async def get_upgradable_packages(limit: int = 10) -> Tuple[int, List[str]]:
    await safe_run_command(_root_helper('apt-update'), timeout=180)
    code, out, err = await safe_run_command(['apt', 'list', '--upgradable'], timeout=60)
    raw = out or err
    if code != 0 and not raw.strip():
        logger.warning('apt list --upgradable failed with code %s', code)
        return 0, []

    packages = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith('Listing...') or '/' not in line:
            continue
        package = line.split('/', 1)[0].strip()
        if package and package not in packages:
            packages.append(package)
    return len(packages), packages[:limit]


async def install_system_updates(progress_cb: ProgressCb = None) -> Tuple[bool, str]:
    if progress_cb:
        progress_cb('Обновляю список пакетов')
    code, out, err = await safe_run_command(_root_helper('apt-update'), timeout=180)
    if code != 0:
        return False, (err or out or 'apt update завершился ошибкой')[-3000:]

    if progress_cb:
        progress_cb('Устанавливаю доступные обновления')
    code, out, err = await safe_run_command(_root_helper('apt-upgrade'), timeout=1800)
    if code != 0:
        return False, (err or out or 'apt upgrade завершился ошибкой')[-3000:]

    if progress_cb:
        progress_cb('Очищаю ненужные пакеты')
    cleanup_parts = []
    for action in ('apt-autoremove', 'apt-autoclean'):
        cleanup_code, cleanup_out, cleanup_err = await safe_run_command(_root_helper(action), timeout=900)
        if cleanup_out.strip():
            cleanup_parts.append(cleanup_out.strip())
        if cleanup_err.strip():
            cleanup_parts.append(cleanup_err.strip())
        if cleanup_code != 0:
            cleanup_parts.append(f'{action} exited with code {cleanup_code}')

    summary = '\n'.join(line for line in (out or err).splitlines()[-20:] if line.strip())
    if cleanup_parts:
        summary = '\n'.join(filter(None, [summary, '\n'.join(cleanup_parts)[-1200:]]))
    return True, summary or 'Обновление системы завершено.'


async def get_bot_update_status(limit: int = 5) -> Tuple[int, List[str], str]:
    project_dir = config.PROJECT_DIR
    fetch_code, _, fetch_err = await safe_run_command(['git', 'fetch', '--all'], timeout=300, cwd=project_dir)
    if fetch_code != 0:
        return 0, [], (fetch_err.strip() or 'git fetch failed')

    code, out, err = await safe_run_command(
        ['git', 'rev-list', '--count', 'HEAD..origin/main'],
        timeout=60,
        cwd=project_dir,
    )
    raw_count = (out or err).strip() or '0'
    if code != 0:
        return 0, [], raw_count
    try:
        count = int(raw_count)
    except ValueError:
        count = 0
    log_code, log_out, log_err = await safe_run_command(
        ['git', 'log', '--oneline', f'-{limit}', 'HEAD..origin/main'],
        timeout=60,
        cwd=project_dir,
    )
    commits = [line.strip() for line in (log_out if log_code == 0 else log_err).splitlines() if line.strip()]
    return count, commits, raw_count


async def update_bot_code(progress_cb: ProgressCb = None) -> Tuple[bool, str]:
    project_dir = Path(config.PROJECT_DIR)
    pip_path = project_dir / 'venv' / 'bin' / 'pip'
    commands = [
        ('Получаю изменения из GitHub', ['git', 'fetch', '--all']),
        ('Обновляю код проекта', ['git', 'reset', '--hard', 'origin/main']),
        ('Обновляю Python зависимости', [str(pip_path), 'install', '-r', 'requirements.txt']),
    ]

    last_output = ''
    for title, cmd in commands:
        if progress_cb:
            progress_cb(title)
        code, out, err = await safe_run_command(cmd, timeout=1800, cwd=str(project_dir))
        last_output = (out or err).strip()
        if code != 0:
            return False, last_output or f'{title}: команда завершилась с кодом {code}'

    return True, last_output or 'Код бота обновлён.'
