#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
from statistics import mean
from typing import Any, Dict, List

from core.formatting import compact_bar
from security import safe_run_command, validate_hostname

PING_STAT_RE = re.compile(
    r'(?P<sent>\d+) packets transmitted, (?P<received>\d+) received, '
    r'(?P<loss>[\d.]+)% packet loss'
)
RTT_RE = re.compile(
    r'(?:rtt|round-trip) min/avg/max(?:/mdev)? = '
    r'(?P<min>[\d.]+)/(?P<avg>[\d.]+)/(?P<max>[\d.]+)'
)
TIME_RE = re.compile(r'time=([\d.]+)')



def get_ping_targets(region: str, category: str) -> List[Dict[str, str]]:
    common = {
        'quick': [
            {'label': 'Cloudflare DNS', 'host': '1.1.1.1'},
            {'label': 'Google DNS', 'host': '8.8.8.8'},
            {'label': 'Quad9 DNS', 'host': '9.9.9.9'},
        ],
        'dns': [
            {'label': 'github.com', 'host': 'github.com'},
            {'label': 'cloudflare.com', 'host': 'cloudflare.com'},
            {'label': 'google.com', 'host': 'google.com'},
        ],
    }
    regional = {
        'europe': [
            {'label': 'Hetzner', 'host': 'hetzner.com'},
            {'label': 'OVH Europe', 'host': 'ovhcloud.com'},
            {'label': 'Cloudflare', 'host': '1.1.1.1'},
        ],
        'north_america': [
            {'label': 'Cloudflare', 'host': '1.1.1.1'},
            {'label': 'Google DNS', 'host': '8.8.8.8'},
            {'label': 'GitHub', 'host': 'github.com'},
        ],
        'asia_pacific': [
            {'label': 'Cloudflare', 'host': '1.1.1.1'},
            {'label': 'Google DNS', 'host': '8.8.8.8'},
            {'label': 'fastly.com', 'host': 'fastly.com'},
        ],
        'global': [
            {'label': 'Cloudflare', 'host': '1.1.1.1'},
            {'label': 'Google DNS', 'host': '8.8.8.8'},
            {'label': 'GitHub', 'host': 'github.com'},
        ],
    }
    if category == 'regional':
        return regional.get(region, regional['global'])
    return common.get(category, common['quick'])


async def run_ping(host: str, count: int = 4) -> Dict[str, Any]:
    if not validate_hostname(host):
        return {'host': host, 'ok': False, 'error': 'Неверный формат хоста'}

    code, out, err = await safe_run_command(['ping', '-c', str(count), '-W', '3', host], timeout=20)
    text = out or err
    if not text:
        return {'host': host, 'ok': False, 'error': 'Нет ответа от ping'}

    stat_match = PING_STAT_RE.search(text)
    rtt_match = RTT_RE.search(text)
    samples = [float(match.group(1)) for match in TIME_RE.finditer(text)]

    if code != 0 and not stat_match:
        return {'host': host, 'ok': False, 'error': (text.strip() or 'Команда ping завершилась ошибкой')}

    if not stat_match:
        return {'host': host, 'ok': False, 'error': 'Не удалось разобрать результат'}

    sent = int(stat_match.group('sent'))
    received = int(stat_match.group('received'))
    loss = float(stat_match.group('loss'))
    avg = float(rtt_match.group('avg')) if rtt_match else (mean(samples) if samples else 0.0)
    min_time = float(rtt_match.group('min')) if rtt_match else (min(samples) if samples else 0.0)
    max_time = float(rtt_match.group('max')) if rtt_match else (max(samples) if samples else 0.0)
    rating = diagnose_ping(avg, loss)
    return {
        'host': host,
        'ok': received > 0,
        'sent': sent,
        'received': received,
        'loss': loss,
        'avg': avg,
        'min': min_time,
        'max': max_time,
        'samples': samples,
        'rating': rating,
        'text': text,
    }



def diagnose_ping(avg: float, loss: float) -> str:
    if loss >= 100:
        return 'Нет ответа'
    if loss >= 25:
        return 'Сильные потери'
    if avg <= 30 and loss == 0:
        return 'Отлично'
    if avg <= 80 and loss <= 2:
        return 'Нормально'
    if avg <= 150 and loss <= 5:
        return 'Есть задержка'
    return 'Связь нестабильна'



def latency_bar(avg: float) -> str:
    if avg <= 30:
        percent = 15
    elif avg <= 80:
        percent = 40
    elif avg <= 150:
        percent = 70
    else:
        percent = 95
    return compact_bar(percent)
