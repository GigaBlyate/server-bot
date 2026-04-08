#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import time
from typing import Any, Dict

import aiohttp

logger = logging.getLogger(__name__)
CACHE_TTL = 3600


async def get_public_ip_info(bot_data: Dict[str, Any]) -> Dict[str, Any]:
    cached = bot_data.get('public_ip_info')
    if cached and time.time() - cached.get('cached_at', 0) < CACHE_TTL:
        return cached['data']

    data: Dict[str, Any] = {
        'ip': 'N/A',
        'country': 'N/A',
        'country_code': '',
        'city': 'N/A',
        'org': 'N/A',
        'asn': 'N/A',
        'timezone': 'N/A',
        'region': 'global',
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get('https://ipapi.co/json/', timeout=8) as resp:
                if resp.status == 200:
                    payload = await resp.json()
                    data.update(
                        {
                            'ip': payload.get('ip', 'N/A'),
                            'country': payload.get('country_name') or payload.get('country', 'N/A'),
                            'country_code': payload.get('country_code', ''),
                            'city': payload.get('city', 'N/A'),
                            'org': payload.get('org') or payload.get('organization', 'N/A'),
                            'asn': payload.get('asn', 'N/A'),
                            'timezone': payload.get('timezone', 'N/A'),
                        }
                    )
    except Exception as exc:
        logger.warning('Cannot resolve server geolocation: %s', exc)

    country_code = str(data.get('country_code') or '').upper()
    if country_code in {
        'DE', 'FR', 'NL', 'PL', 'CZ', 'AT', 'ES', 'IT', 'GB', 'SE', 'FI',
        'NO', 'DK', 'BE', 'CH', 'PT', 'IE', 'RO', 'HU', 'SK', 'UA', 'LV',
        'LT', 'EE', 'TR',
    }:
        data['region'] = 'europe'
    elif country_code in {'US', 'CA', 'MX'}:
        data['region'] = 'north_america'
    elif country_code in {
        'JP', 'SG', 'IN', 'KR', 'HK', 'ID', 'MY', 'TH', 'VN', 'PH', 'AU',
        'NZ', 'AE', 'IL',
    }:
        data['region'] = 'asia_pacific'
    else:
        data['region'] = 'global'

    bot_data['public_ip_info'] = {'cached_at': time.time(), 'data': data}
    return data
