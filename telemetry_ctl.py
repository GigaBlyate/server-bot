#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from services.telemetry import (
    get_server_uid,
    get_server_uid_aliases,
    post_telemetry_event,
    send_uninstall_event,
)


def main() -> int:
    parser = argparse.ArgumentParser(description='G-PANEL telemetry control utility')
    sub = parser.add_subparsers(dest='command', required=True)

    sub.add_parser('install')
    sub.add_parser('heartbeat')
    sub.add_parser('uninstall')
    sub.add_parser('server-uid')
    sub.add_parser('aliases')

    args = parser.parse_args()

    if args.command == 'server-uid':
        print(get_server_uid())
        return 0

    if args.command == 'aliases':
        print(json.dumps(get_server_uid_aliases(), ensure_ascii=False))
        return 0

    if args.command == 'uninstall':
        ok = asyncio.run(send_uninstall_event())
        return 0 if ok else 1

    ok = asyncio.run(post_telemetry_event(args.command))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
