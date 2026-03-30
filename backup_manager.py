#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import glob
import json
import logging
import os
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

import config
from security import sanitize_path

logger = logging.getLogger(__name__)
BACKUP_ALLOWED_PATHS = [
    '/etc', '/var', '/home', '/root', '/opt', '/srv', '/usr/local', '/usr/lib', '/lib', '/var/lib', '/var/spool'
]
ProgressCb = Optional[Callable[[str], Awaitable[None]]]


def _safe_backup_path(path: str) -> str:
    return sanitize_path(path, BACKUP_ALLOWED_PATHS)



def _human_size_kb(size_kb: int) -> str:
    if size_kb >= 1024 * 1024:
        return f'{round(size_kb / 1024 / 1024, 1)} GB'
    if size_kb >= 1024:
        return f'{round(size_kb / 1024, 1)} MB'
    return f'{size_kb} KB'



def _path_size_kb(path: str) -> int:
    try:
        result = subprocess.run(
            ['du', '-sk', path],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if result.stdout.strip():
            return int(result.stdout.split()[0])
    except Exception as exc:
        logger.debug('Cannot get size for %s: %s', path, exc)
    return 0



def _existing_paths(paths: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in paths:
        candidates = glob.glob(item) if any(ch in item for ch in '*?[]') else [item]
        for candidate in candidates:
            try:
                safe = _safe_backup_path(candidate)
            except Exception:
                continue
            if os.path.exists(safe) and safe not in seen:
                seen.add(safe)
                out.append(safe)
    return out


class BackupManager:
    def __init__(self, db_path: str, backup_dir: Optional[str] = None):
        self.db_path = _safe_backup_path(db_path)
        if backup_dir is None:
            backup_dir = config.BACKUP_DIR
        self.backup_dir = _safe_backup_path(backup_dir)
        os.makedirs(self.backup_dir, exist_ok=True)

    async def create_backup(self, include_configs: bool = False, progress_cb: ProgressCb = None) -> Optional[str]:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_file = os.path.join(self.backup_dir, f'backup_{timestamp}.tar.gz')
        try:
            if progress_cb:
                await progress_cb('Подготавливаю базовый бэкап')
            with tempfile.TemporaryDirectory() as tmpdir:
                payload_dir = os.path.join(tmpdir, 'backup_data')
                os.makedirs(payload_dir, exist_ok=True)
                shutil.copy2(self.db_path, os.path.join(payload_dir, 'vps_data.db'))

                config_dir = os.path.join(payload_dir, 'configs')
                os.makedirs(config_dir, exist_ok=True)
                copied_configs: List[str] = []
                config_files = ['config.py', '.env', 'oauth-credentials.json', 'token.pickle', 'version.txt']
                if include_configs:
                    for name in config_files:
                        src = os.path.join(os.path.dirname(self.db_path), name)
                        if os.path.exists(src):
                            shutil.copy2(src, os.path.join(config_dir, os.path.basename(src)))
                            copied_configs.append(name)

                readme_path = os.path.join(payload_dir, 'README.txt')
                with open(readme_path, 'w', encoding='utf-8') as fh:
                    fh.write('SERVER BOT BACKUP\n')
                    fh.write('=' * 60 + '\n')
                    fh.write(f'Created: {datetime.now():%d.%m.%Y %H:%M:%S}\n')
                    fh.write(f'Archive: {os.path.basename(backup_file)}\n\n')
                    fh.write('Included:\n')
                    fh.write('- vps_data.db\n')
                    if copied_configs:
                        for item in copied_configs:
                            fh.write(f'- configs/{item}\n')
                    else:
                        fh.write('- configs not included\n')
                    fh.write('\nRestore:\n')
                    fh.write('1. Stop bot: sudo systemctl stop server-bot\n')
                    fh.write('2. Extract archive\n')
                    fh.write('3. Copy files back to bot directory\n')
                    fh.write('4. Start bot: sudo systemctl start server-bot\n')

                if progress_cb:
                    await progress_cb('Архивирую базовый бэкап')
                with tarfile.open(backup_file, 'w:gz') as tar:
                    tar.add(payload_dir, arcname='backup_data')
            return backup_file
        except Exception as exc:
            logger.exception('Error creating backup: %s', exc)
            return None

    async def upload_to_google_drive(self, file_path: str, folder_id: str) -> Tuple[bool, str]:
        oauth_creds_path = os.path.join(os.path.dirname(self.db_path), 'oauth-credentials.json')
        token_file = os.path.join(os.path.dirname(self.db_path), 'token.pickle')
        if not os.path.exists(oauth_creds_path):
            return False, 'OAuth credentials not found. Please run auth_manual.py first.'
        if not os.path.exists(token_file):
            return False, 'Token not found. Please run auth_manual.py to authorize.'
        try:
            import sys

            sys.path.insert(0, os.path.dirname(self.db_path))
            from upload_to_gdrive import upload_to_google_drive as gdrive_upload

            result, error = await gdrive_upload(file_path, folder_id)
            return (True, 'Загружено успешно') if result else (False, error or 'Upload failed')
        except Exception as exc:
            logger.exception('Upload error: %s', exc)
            return False, str(exc)

    def cleanup_old_backups(self, keep_count: int = 10) -> int:
        try:
            backups = sorted(
                [f for f in os.listdir(self.backup_dir) if f.startswith('backup_') and f.endswith('.tar.gz')],
                key=lambda item: os.path.getctime(os.path.join(self.backup_dir, item)),
            )
            removed = 0
            for backup in backups[:-keep_count]:
                os.remove(os.path.join(self.backup_dir, backup))
                removed += 1
            return removed
        except Exception as exc:
            logger.exception('Error cleaning up backups: %s', exc)
            return 0


class UniversalScanner:
    """Find important services, secrets and project directories for migration backups."""

    def __init__(self):
        self.services: Dict[str, Dict] = {}
        self.skipped_paths: List[str] = []
        self.scan_errors: List[str] = []

    def _remember_skip(self, path: str, reason: str) -> None:
        entry = f'{path} ({reason})'
        if entry not in self.skipped_paths:
            self.skipped_paths.append(entry)
        logger.warning('Skipped path during backup scan: %s', entry)

    def _safe_dir_entries(self, path: str) -> List[os.DirEntry]:
        try:
            with os.scandir(path) as iterator:
                return list(iterator)
        except PermissionError:
            self._remember_skip(path, 'нет прав на чтение')
        except OSError as exc:
            self._remember_skip(path, exc.strerror or str(exc))
        return []

    def _add_component(
        self,
        sid: str,
        name: str,
        stype: str,
        paths: List[str],
        desc: str,
        selected: bool = True,
    ) -> None:
        resolved = _existing_paths(paths)
        if not resolved:
            return
        size_kb = sum(_path_size_kb(path) for path in resolved)
        self.services[sid] = {
            'id': sid,
            'name': name,
            'type': stype,
            'paths': resolved,
            'description': desc,
            'size_kb': size_kb,
            'size_text': _human_size_kb(size_kb),
            'selected': selected,
        }

    def _scan_known_services(self) -> None:
        known = {
            '3x-ui': {
                'paths': ['/etc/x-ui', '/usr/local/x-ui', '/var/lib/x-ui', '/etc/systemd/system/x-ui.service'],
                'desc': '3x-ui: конфиг, база и unit-файл',
            },
            'prosody': {
                'paths': ['/etc/prosody', '/var/lib/prosody', '/var/spool/prosody', '/var/log/prosody'],
                'desc': 'Prosody: конфиги, данные, spool и логи',
            },
            'server-bot': {
                'paths': [config.PROJECT_DIR, '/etc/systemd/system/server-bot.service'],
                'desc': 'Код бота, база, токены и unit-файл',
            },
            'ssh': {
                'paths': ['/etc/ssh', '/root/.ssh', os.path.expanduser('~/.ssh')],
                'desc': 'SSH-конфигурация и ключи доступа',
            },
            'nginx': {
                'paths': ['/etc/nginx', '/var/www', '/srv/www', '/etc/letsencrypt'],
                'desc': 'Nginx, сайты и TLS-сертификаты',
            },
            'fail2ban': {
                'paths': ['/etc/fail2ban', '/var/log/fail2ban.log'],
                'desc': 'Fail2ban правила и лог блокировок',
            },
            'docker': {
                'paths': ['/etc/docker', '/var/lib/docker/volumes', '/var/lib/docker/containers'],
                'desc': 'Docker volumes, контейнеры и конфиги',
            },
            'cron': {
                'paths': ['/etc/crontab', '/etc/cron.d', '/var/spool/cron', '/var/spool/cron/crontabs'],
                'desc': 'Cron задания и crontab пользователей',
            },
            'google-drive-auth': {
                'paths': [
                    os.path.join(config.PROJECT_DIR, 'oauth-credentials.json'),
                    os.path.join(config.PROJECT_DIR, 'token.pickle'),
                    os.path.join(config.PROJECT_DIR, 'vps_data.db'),
                ],
                'desc': 'Ключи, токены и база для бэкапов в Google Drive',
            },
        }
        for service_name, payload in known.items():
            self._add_component(
                f'known_{service_name}',
                service_name,
                'known',
                payload['paths'],
                payload['desc'],
            )

    def _scan_systemd_services(self) -> None:
        try:
            result = subprocess.run(
                ['systemctl', 'list-units', '--type=service', '--state=running', '--no-legend'],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if result.returncode != 0:
                return
            for line in result.stdout.splitlines():
                unit = line.split()[0].strip()
                if not unit.endswith('.service'):
                    continue
                name = unit[:-8]
                unit_paths = [
                    f'/etc/systemd/system/{unit}',
                    f'/lib/systemd/system/{unit}',
                    f'/usr/lib/systemd/system/{unit}',
                    f'/etc/{name}',
                    f'/var/lib/{name}',
                    f'/var/log/{name}',
                    f'/opt/{name}',
                    f'/srv/{name}',
                ]
                self._add_component(
                    f'service_{name}',
                    name,
                    'service',
                    unit_paths,
                    f'Работающий systemd-сервис {name}',
                    selected=name in {'nginx', 'prosody', 'x-ui', 'server-bot'},
                )
        except Exception as exc:
            logger.debug('Systemd service scan failed: %s', exc)

    def _scan_projects(self) -> None:
        roots = [Path('/opt'), Path('/srv'), Path('/home'), Path('/usr/local')]
        for root in roots:
            try:
                safe = _safe_backup_path(str(root))
            except Exception:
                continue
            if not os.path.isdir(safe):
                continue
            candidates = []
            for entry in self._safe_dir_entries(safe):
                if not entry.is_dir(follow_symlinks=False):
                    continue
                candidates.append(entry.path)
                if root.name == 'home':
                    for nested in self._safe_dir_entries(entry.path):
                        if nested.is_dir(follow_symlinks=False):
                            candidates.append(nested.path)
            for candidate_path in candidates:
                child_entries = self._safe_dir_entries(candidate_path)
                names = {child.name for child in child_entries}
                if {'.git', 'docker-compose.yml', 'compose.yaml', '.env'} & names:
                    self._add_component(
                        f'project_{os.path.basename(candidate_path)}',
                        os.path.basename(candidate_path),
                        'project',
                        [candidate_path],
                        'Проект или директория приложения',
                        selected=False,
                    )

    def _scan_secret_files(self) -> None:
        patterns = [
            '/etc/**/*.env',
            '/home/**/*.env',
            '/opt/**/*.env',
            '/srv/**/*.env',
            '/etc/letsencrypt/live/*/*.pem',
            '/etc/prosody/**/*.crt',
            '/etc/prosody/**/*.key',
            '/home/**/token.pickle',
            '/home/**/oauth-credentials.json',
            '/opt/**/token.pickle',
        ]
        found_paths: List[str] = []
        for pattern in patterns:
            found_paths.extend(glob.glob(pattern, recursive=True))
        found_paths = list(dict.fromkeys(found_paths))
        if found_paths:
            self._add_component(
                'secrets_bundle',
                'Secrets bundle',
                'secrets',
                found_paths,
                'Секреты, .env, сертификаты и OAuth-файлы',
                selected=False,
            )

    def _scan_docker_containers(self) -> None:
        try:
            result = subprocess.run(
                ['docker', 'ps', '-a', '--format', '{{.Names}}'],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if result.returncode != 0:
                return
            for container in [line for line in result.stdout.splitlines() if line.strip()]:
                inspect = subprocess.run(
                    ['docker', 'inspect', '--format', '{{.Id}}', container],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                if inspect.returncode != 0 or not inspect.stdout.strip():
                    continue
                container_id = inspect.stdout.strip()
                self._add_component(
                    f'docker_{container}',
                    container,
                    'docker',
                    [f'/var/lib/docker/containers/{container_id}'],
                    f'Docker контейнер {container}',
                    selected=False,
                )
        except Exception as exc:
            logger.debug('Docker scan failed: %s', exc)

    async def scan_all(self, progress_cb: ProgressCb = None) -> Dict[str, Dict]:
        steps = [
            ('Ищу известные сервисы и их данные', self._scan_known_services),
            ('Проверяю работающие systemd-сервисы', self._scan_systemd_services),
            ('Ищу проекты и директории приложений', self._scan_projects),
            ('Ищу ключи, токены и сертификаты', self._scan_secret_files),
            ('Ищу Docker контейнеры и volumes', self._scan_docker_containers),
        ]
        for title, func in steps:
            if progress_cb:
                await progress_cb(title)
            try:
                func()
            except Exception as exc:
                self.scan_errors.append(f'{title}: {exc}')
                logger.exception('Backup scan step failed: %s', title)
        return self.services

    def get_services_list(self) -> List[Tuple[str, str, str, str, bool]]:
        return [
            (
                sid,
                svc['name'],
                svc['description'][:60],
                svc['size_text'],
                svc['selected'],
            )
            for sid, svc in sorted(self.services.items(), key=lambda item: item[1]['name'].lower())
        ]

    def toggle_selection(self, sid: str) -> None:
        if sid in self.services:
            self.services[sid]['selected'] = not self.services[sid]['selected']

    def set_selected(self, selected_ids: List[str]) -> None:
        selected = set(selected_ids)
        for sid, svc in self.services.items():
            svc['selected'] = sid in selected

    def select_all(self) -> None:
        for service in self.services.values():
            service['selected'] = True

    def clear_selection(self) -> None:
        for service in self.services.values():
            service['selected'] = False

    def get_selected(self) -> Dict[str, Dict]:
        return {sid: svc for sid, svc in self.services.items() if svc['selected']}

    def get_total_size(self) -> str:
        total = sum(svc['size_kb'] for svc in self.get_selected().values())
        return _human_size_kb(total)


async def create_selected_backup(
    selected_services: Dict[str, Dict],
    progress_cb: ProgressCb = None,
) -> Optional[str]:
    if not selected_services:
        return None

    tmp_root = None
    try:
        tmp_root = tempfile.mkdtemp(prefix='smart-backup-')
        payload_dir = os.path.join(tmp_root, 'backup_data')
        os.makedirs(payload_dir, exist_ok=True)
        archive_path = os.path.join(
            '/tmp',
            f'smart_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.tar.gz',
        )
        manifest = []
        total = max(1, len(selected_services))
        for index, (sid, svc) in enumerate(selected_services.items(), start=1):
            if progress_cb:
                await progress_cb(f'Копирую {index}/{total}: {svc["name"]}')
            service_dir = os.path.join(payload_dir, sid)
            os.makedirs(service_dir, exist_ok=True)
            copied = []
            for path in svc['paths']:
                try:
                    safe_path = _safe_backup_path(path)
                except Exception:
                    continue
                if not os.path.exists(safe_path):
                    continue
                name = os.path.basename(safe_path.rstrip('/')) or 'root'
                dest = os.path.join(service_dir, name)
                try:
                    if os.path.isfile(safe_path):
                        shutil.copy2(safe_path, dest)
                    else:
                        shutil.copytree(
                            safe_path,
                            dest,
                            symlinks=True,
                            ignore_dangling_symlinks=True,
                            dirs_exist_ok=True,
                        )
                    copied.append(safe_path)
                except Exception as exc:
                    logger.warning('Cannot copy %s: %s', safe_path, exc)
            manifest.append(
                {
                    'id': sid,
                    'name': svc['name'],
                    'type': svc['type'],
                    'description': svc['description'],
                    'paths': copied,
                }
            )

        with open(os.path.join(payload_dir, 'manifest.json'), 'w', encoding='utf-8') as fh:
            json.dump(
                {
                    'created_at': datetime.now().isoformat(),
                    'components': manifest,
                },
                fh,
                ensure_ascii=False,
                indent=2,
            )

        with open(os.path.join(payload_dir, 'RESTORE.txt'), 'w', encoding='utf-8') as fh:
            fh.write('SMART BACKUP RESTORE GUIDE\n')
            fh.write('=' * 60 + '\n')
            fh.write('1. Install required packages/services on new VPS\n')
            fh.write('2. Extract archive to /tmp\n')
            fh.write('3. Review manifest.json\n')
            fh.write('4. Copy folders back to original locations carefully\n')
            fh.write('5. Restore permissions and restart services\n\n')
            fh.write('This archive contains configs, data, keys and service files needed for migration.\n')

        if progress_cb:
            await progress_cb('Упаковываю архив')
        with tarfile.open(archive_path, 'w:gz') as tar:
            tar.add(payload_dir, arcname='backup_data')
        return archive_path
    except Exception as exc:
        logger.exception('Error creating selected backup: %s', exc)
        return None
    finally:
        if tmp_root and os.path.isdir(tmp_root):
            shutil.rmtree(tmp_root, ignore_errors=True)
