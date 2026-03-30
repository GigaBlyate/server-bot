#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import html
from datetime import timedelta
from typing import Any


def escape_html(value: Any) -> str:
    if value is None:
        return ''
    return html.escape(str(value), quote=True)



def format_size(bytes_value: float) -> str:
    units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
    size = float(bytes_value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == 'B':
                return f'{int(size)} {unit}'
            return f'{size:.1f} {unit}'
        size /= 1024
    return f'{size:.1f} PB'



def format_gb(value_gb: float) -> str:
    if value_gb >= 1024:
        return f'{value_gb / 1024:.1f} TB'
    return f'{value_gb:.0f} GB'



def format_uptime(seconds: float, include_seconds: bool = False) -> str:
    total = int(seconds)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f'{days}д')
    if hours:
        parts.append(f'{hours}ч')
    if minutes:
        parts.append(f'{minutes}м')
    if include_seconds and secs and len(parts) < 3:
        parts.append(f'{secs}с')
    return ' '.join(parts) if parts else '0м'



def compact_bar(percent: float, width: int = 4) -> str:
    ratio = max(0.0, min(100.0, float(percent))) / 100.0
    filled = round(ratio * width)
    return '▓' * filled + '░' * (width - filled)



def compact_metric(label: str, percent: float) -> str:
    return f'{label} {percent:.1f}% {compact_bar(percent)}'



def health_icon(value: bool) -> str:
    return '🟢' if value else '🔴'



def days_left_text(days_left: int) -> str:
    if days_left < 0:
        return f'просрочено на {abs(days_left)} дн.'
    if days_left == 0:
        return 'сегодня'
    return f'{days_left} дн.'
