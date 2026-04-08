#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import logging
import os
import pickle
from typing import Optional, Tuple

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/drive.file']
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(PROJECT_DIR, 'token.pickle')
CREDENTIALS_FILE = os.path.join(PROJECT_DIR, 'oauth-credentials.json')


def _save_credentials(creds) -> None:
    with open(TOKEN_FILE, 'wb') as token:
        pickle.dump(creds, token)


def get_credentials(interactive: bool = False):
    creds = None

    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'rb') as token:
            creds = pickle.load(token)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_credentials(creds)
            return creds
        except Exception as exc:
            logger.warning('Google token refresh failed: %s', exc)
            raise RuntimeError(
                'Google Drive token истёк или был отозван. Пересоздайте token.pickle через auth_manual.py.'
            ) from exc

    if not interactive:
        raise RuntimeError(
            'Google Drive не авторизован. Создайте oauth-credentials.json и token.pickle через auth_manual.py.'
        )

    if not os.path.exists(CREDENTIALS_FILE):
        raise RuntimeError('oauth-credentials.json не найден в папке проекта.')

    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
    creds = flow.run_local_server(port=0)
    _save_credentials(creds)
    return creds


def _upload_sync(file_path: str, folder_id: str) -> Tuple[Optional[dict], Optional[str]]:
    try:
        if not os.path.exists(file_path):
            return None, f'File not found: {file_path}'

        creds = get_credentials(interactive=False)
        service = build('drive', 'v3', credentials=creds)

        file_name = os.path.basename(file_path)
        file_metadata = {'name': file_name, 'parents': [folder_id]}
        media = MediaFileUpload(file_path, resumable=True, chunksize=10 * 1024 * 1024)

        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, name, size',
            supportsAllDrives=True,
        ).execute()

        file_id = file.get('id')
        uploaded_name = file.get('name')
        file_size = int(file.get('size', 0)) / 1024 / 1024
        logger.info('File uploaded to Google Drive: %s', uploaded_name)
        return {
            'id': file_id,
            'name': uploaded_name,
            'size_mb': round(file_size, 2),
            'link': f'https://drive.google.com/file/d/{file_id}/view',
        }, None
    except Exception as exc:
        logger.error('Upload error: %s', exc)
        return None, str(exc)


async def upload_to_google_drive(file_path: str, folder_id: str) -> Tuple[Optional[dict], Optional[str]]:
    return await asyncio.to_thread(_upload_sync, file_path, folder_id)
