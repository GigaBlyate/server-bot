#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
os.chdir(PROJECT_DIR)

from services.telemetry import send_signed_event_sync  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description='Telemetry control utility')
    parser.add_argument('event', choices=['install', 'heartbeat', 'uninstall'])
    parser.add_argument('--url', default='', help='Override telemetry base URL')
    parser.add_argument('--timeout', type=int, default=10, help='HTTP timeout in seconds')
    args = parser.parse_args()
    ok = send_signed_event_sync(args.event, url_override=(args.url or None), timeout=args.timeout)
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
