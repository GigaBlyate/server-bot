#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import logging
import os
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import config

logger = logging.getLogger(__name__)
DB_PATH = config.DB_PATH
DEFAULT_NOTIFY_DAYS = '30,20,10,5,1'

DEFAULT_SETTINGS: Dict[str, str] = {
    'cpu_threshold': '85',
    'ram_threshold': '90',
    'disk_threshold': '90',
    'monitor_interval': '60',
    'history_limit': '100',
    'enable_daily_report': 'false',
    'report_time': '09:00',
    'report_format': 'detailed',
    'backup_interval': '24',
    'backup_keep_count': '10',
    'google_drive_folder_id': '',
    'backup_selection_profile': '[]',
    'backup_enabled': 'false',
    'auto_update': 'false',
    'traffic_mode': 'unlimited',
    'traffic_quota_gb': '3072',
    'traffic_activation_date': '',
    'traffic_overage_rub_per_tb': '200',
    'traffic_total_bytes': '0',
    'traffic_last_counter_bytes': '0',
    'traffic_last_counter_updated_at': '',
    'traffic_today_date': '',
    'traffic_today_anchor_total_bytes': '0',
    'traffic_yesterday_bytes': '0',
    'traffic_billing_period_start': '',
    'traffic_billing_period_end': '',
    'traffic_period_anchor_total_bytes': '0',
    'traffic_period_anchor_set_at': '',
    'traffic_period_seed_bytes': '0',
    'traffic_alert_sent_1tb': 'false',
    'traffic_alert_sent_300gb': 'false',
    'system_updates_count': '',
    'system_updates_packages_json': '[]',
    'system_updates_checked_at': '',
    'bot_updates_count': '',
    'bot_updates_commits_json': '[]',
    'bot_updates_checked_at': '',
    'last_backup_success': '',
    'last_backup_size_mb': '0',
    'dashboard_autorefresh': 'true',
    'telemetry_install_id': '',
    'telemetry_registered': 'false',
    'telemetry_last_sent': '',
    'telemetry_auth_secret': '',
    'manual_services_json': '[]',
}


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with closing(connect()) as conn:
        conn.executescript(
            '''
            CREATE TABLE IF NOT EXISTS vps_rental (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                expiry_date DATE NOT NULL,
                notify_days TEXT DEFAULT '30,20,10,5,1',
                last_notify TEXT
            );

            CREATE TABLE IF NOT EXISTS process_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                process_name TEXT,
                pid INTEGER,
                cpu_percent REAL,
                memory_percent REAL,
                status TEXT
            );

            CREATE TABLE IF NOT EXISTS alert_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                alert_type TEXT NOT NULL,
                message TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS metrics_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                cpu_percent REAL NOT NULL,
                ram_percent REAL NOT NULL,
                disk_percent REAL NOT NULL,
                net_sent INTEGER NOT NULL,
                net_recv INTEGER NOT NULL,
                load1 REAL DEFAULT 0,
                load5 REAL DEFAULT 0,
                load15 REAL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS process_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                process_name TEXT NOT NULL,
                pid INTEGER,
                cpu_percent REAL DEFAULT 0,
                memory_percent REAL DEFAULT 0,
                memory_mb REAL DEFAULT 0,
                metric_type TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS directory_monitor (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL,
                threshold_mb INTEGER NOT NULL,
                last_notify TEXT
            );

            CREATE TABLE IF NOT EXISTS docker_monitor (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                container_name TEXT NOT NULL,
                cpu_threshold REAL DEFAULT 80,
                memory_threshold REAL DEFAULT 90,
                enabled INTEGER DEFAULT 1,
                last_notify TEXT
            );
            '''
        )

        existing = {
            row['key']: row['value']
            for row in conn.execute('SELECT key, value FROM settings')
        }
        for key, value in DEFAULT_SETTINGS.items():
            if key not in existing:
                conn.execute(
                    'INSERT INTO settings (key, value) VALUES (?, ?)',
                    (key, value),
                )

        conn.execute(
            '''
            UPDATE vps_rental
            SET notify_days = ?
            WHERE notify_days IS NULL
               OR notify_days = ''
               OR notify_days = '30,14,7,3,1'
            ''',
            (DEFAULT_NOTIFY_DAYS,),
        )
        conn.commit()
    logger.info('Database initialized at %s', DB_PATH)


def db_execute(
    query: str,
    params: Sequence[Any] = (),
    fetch: bool = False,
    many: bool = False,
) -> Optional[List[sqlite3.Row]]:
    try:
        with closing(connect()) as conn:
            cur = conn.cursor()
            if many:
                cur.executemany(query, params)  # type: ignore[arg-type]
            else:
                cur.execute(query, params)
            rows = cur.fetchall() if fetch else None
            conn.commit()
            return rows
    except Exception as exc:
        logger.exception('Database error: %s', exc)
        return [] if fetch else None


def get_setting(key: str, default: Any = None) -> Any:
    rows = db_execute('SELECT value FROM settings WHERE key=?', (key,), fetch=True)
    if not rows:
        return default
    return rows[0]['value']


def set_setting(key: str, value: Any) -> None:
    db_execute(
        'INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)',
        (key, str(value)),
    )


def get_all_settings() -> Dict[str, str]:
    rows = db_execute('SELECT key, value FROM settings ORDER BY key', fetch=True) or []
    return {row['key']: row['value'] for row in rows}




def get_json_setting(key: str, default: Any) -> Any:
    raw = get_setting(key, '')
    if raw in (None, ''):
        return default
    try:
        return json.loads(str(raw))
    except Exception:
        return default

def add_alert_event(alert_type: str, message: str) -> None:
    db_execute(
        'INSERT INTO alert_events (alert_type, message) VALUES (?, ?)',
        (alert_type, message),
    )


def add_metrics_sample(
    timestamp: str,
    cpu_percent: float,
    ram_percent: float,
    disk_percent: float,
    net_sent: int,
    net_recv: int,
    load1: float,
    load5: float,
    load15: float,
) -> None:
    db_execute(
        '''
        INSERT INTO metrics_samples (
            timestamp, cpu_percent, ram_percent, disk_percent,
            net_sent, net_recv, load1, load5, load15
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            timestamp,
            cpu_percent,
            ram_percent,
            disk_percent,
            net_sent,
            net_recv,
            load1,
            load5,
            load15,
        ),
    )


def add_process_samples(
    timestamp: str,
    samples: Iterable[Tuple[str, int, float, float, float, str]],
) -> None:
    data = list(samples)
    if not data:
        return
    db_execute(
        '''
        INSERT INTO process_samples (
            timestamp, process_name, pid, cpu_percent,
            memory_percent, memory_mb, metric_type
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ''',
        data,
        many=True,
    )


def cleanup_old_samples(days_to_keep: int = 10) -> None:
    cutoff = (datetime.now() - timedelta(days=days_to_keep)).isoformat(
        timespec='seconds'
    )
    db_execute('DELETE FROM metrics_samples WHERE timestamp < ?', (cutoff,))
    db_execute('DELETE FROM process_samples WHERE timestamp < ?', (cutoff,))


def get_previous_day_window() -> Tuple[str, str, date]:
    target_day = date.today() - timedelta(days=1)
    start = datetime.combine(target_day, datetime.min.time())
    end = start + timedelta(days=1)
    return start.isoformat(timespec='seconds'), end.isoformat(timespec='seconds'), target_day


def get_daily_metrics_summary() -> Dict[str, Any]:
    start, end, target_day = get_previous_day_window()
    rows = db_execute(
        '''
        SELECT
            AVG(cpu_percent) AS avg_cpu,
            MAX(cpu_percent) AS max_cpu,
            AVG(ram_percent) AS avg_ram,
            MAX(ram_percent) AS max_ram,
            AVG(disk_percent) AS avg_disk,
            MAX(disk_percent) AS max_disk,
            AVG(load1) AS avg_load1,
            AVG(load5) AS avg_load5,
            AVG(load15) AS avg_load15,
            MIN(net_sent) AS min_sent,
            MAX(net_sent) AS max_sent,
            MIN(net_recv) AS min_recv,
            MAX(net_recv) AS max_recv,
            COUNT(*) AS samples
        FROM metrics_samples
        WHERE timestamp >= ? AND timestamp < ?
        ''',
        (start, end),
        fetch=True,
    ) or []

    summary = dict(rows[0]) if rows else {}
    summary['target_day'] = target_day
    summary['traffic_sent'] = max(
        0,
        (summary.get('max_sent') or 0) - (summary.get('min_sent') or 0),
    )
    summary['traffic_recv'] = max(
        0,
        (summary.get('max_recv') or 0) - (summary.get('min_recv') or 0),
    )
    return summary


def get_daily_top_processes(metric_type: str, limit: int = 5) -> List[Dict[str, Any]]:
    start, end, _ = get_previous_day_window()
    order_field = 'max_cpu' if metric_type == 'cpu' else 'max_memory_percent'
    rows = db_execute(
        f'''
        SELECT
            process_name,
            MAX(cpu_percent) AS max_cpu,
            MAX(memory_percent) AS max_memory_percent,
            MAX(memory_mb) AS max_memory_mb,
            COUNT(*) AS hits
        FROM process_samples
        WHERE metric_type = ? AND timestamp >= ? AND timestamp < ?
        GROUP BY process_name
        ORDER BY {order_field} DESC, hits DESC
        LIMIT ?
        ''',
        (metric_type, start, end, limit),
        fetch=True,
    ) or []
    return [dict(row) for row in rows]


def get_previous_day_alert_count() -> int:
    start, end, _ = get_previous_day_window()
    rows = db_execute(
        'SELECT COUNT(*) AS cnt FROM alert_events WHERE timestamp >= ? AND timestamp < ?',
        (start, end),
        fetch=True,
    ) or []
    return int(rows[0]['cnt']) if rows else 0


def get_recent_alert_count(days: int = 1) -> int:
    rows = db_execute(
        "SELECT COUNT(*) AS cnt FROM alert_events WHERE timestamp > datetime('now', ?)",
        (f'-{days} day',),
        fetch=True,
    ) or []
    return int(rows[0]['cnt']) if rows else 0


def add_vps(name: str, expiry_date: str, notify_days: str = DEFAULT_NOTIFY_DAYS) -> None:
    db_execute(
        'INSERT INTO vps_rental (name, expiry_date, notify_days, last_notify) VALUES (?, ?, ?, ?)',
        (name, expiry_date, notify_days, ''),
    )


def update_vps_expiry(vps_id: int, expiry_date: str) -> None:
    db_execute(
        'UPDATE vps_rental SET expiry_date=?, notify_days=?, last_notify=? WHERE id=?',
        (expiry_date, DEFAULT_NOTIFY_DAYS, '', vps_id),
    )


def delete_vps(vps_id: int) -> None:
    db_execute('DELETE FROM vps_rental WHERE id=?', (vps_id,))


def get_vps_list() -> List[Dict[str, Any]]:
    rows = db_execute(
        'SELECT id, name, expiry_date, notify_days, last_notify FROM vps_rental ORDER BY expiry_date ASC',
        fetch=True,
    ) or []
    return [dict(row) for row in rows]


def get_due_vps(days_limit: int = 30) -> List[Dict[str, Any]]:
    today = date.today()
    due: List[Dict[str, Any]] = []
    for item in get_vps_list():
        try:
            expiry = date.fromisoformat(item['expiry_date'])
        except Exception:
            continue
        days_left = (expiry - today).days
        if days_left <= days_limit:
            item['days_left'] = days_left
            due.append(item)
    return due


def mark_vps_notified(vps_id: int) -> None:
    db_execute(
        'UPDATE vps_rental SET last_notify=? WHERE id=?',
        (date.today().isoformat(), vps_id),
    )


def get_notifiable_vps() -> List[Dict[str, Any]]:
    today = date.today()
    result: List[Dict[str, Any]] = []
    for item in get_vps_list():
        try:
            expiry = date.fromisoformat(item['expiry_date'])
        except Exception:
            continue
        days_left = (expiry - today).days
        notify_days = [
            int(chunk)
            for chunk in str(item.get('notify_days') or DEFAULT_NOTIFY_DAYS).split(',')
            if chunk.strip().isdigit()
        ]
        if days_left in notify_days and item.get('last_notify') != today.isoformat():
            item['days_left'] = days_left
            result.append(item)
    return result


def save_backup_result(size_mb: float) -> None:
    set_setting('last_backup_success', datetime.now().isoformat(timespec='seconds'))
    set_setting('last_backup_size_mb', f'{size_mb:.1f}')


def get_backup_result() -> Dict[str, str]:
    return {
        'last_backup_success': get_setting('last_backup_success', ''),
        'last_backup_size_mb': get_setting('last_backup_size_mb', '0'),
    }


def get_saved_backup_selection() -> List[str]:
    raw = get_setting('backup_selection_profile', '[]')
    try:
        payload = json.loads(raw)
        if isinstance(payload, list):
            return [str(item) for item in payload]
    except json.JSONDecodeError:
        logger.warning('Cannot decode backup_selection_profile')
    return []


def set_saved_backup_selection(selection: List[str]) -> None:
    set_setting('backup_selection_profile', json.dumps(selection, ensure_ascii=False))
