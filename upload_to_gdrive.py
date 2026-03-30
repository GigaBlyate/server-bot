#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import pickle
import logging
from typing import Tuple, Optional
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

logger = logging.getLogger(__name__)

# Если нужно изменить scopes
SCOPES = ['https://www.googleapis.com/auth/drive.file']
TOKEN_FILE = 'token.pickle'

def get_credentials():
    """Получает учетные данные OAuth 2.0"""
    creds = None
    
    # Пробуем загрузить сохраненные токены
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'rb') as token:
            creds = pickle.load(token)
    
    # Если токенов нет или они недействительны
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'oauth-credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Сохраняем токены для следующего использования
        with open(TOKEN_FILE, 'wb') as token:
            pickle.dump(creds, token)
    
    return creds

async def upload_to_google_drive(file_path: str, folder_id: str) -> Tuple[Optional[dict], Optional[str]]:
    """
    Загружает файл на Google Drive через OAuth 2.0
    """
    try:
        if not os.path.exists(file_path):
            return None, f"File not found: {file_path}"
        
        # Получаем учетные данные
        creds = get_credentials()
        service = build('drive', 'v3', credentials=creds)
        
        file_name = os.path.basename(file_path)
        file_metadata = {
            'name': file_name,
            'parents': [folder_id]
        }
        
        media = MediaFileUpload(
            file_path,
            resumable=True,
            chunksize=10 * 1024 * 1024  # 10 MB
        )
        
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, name, size'
        ).execute()
        
        file_id = file.get('id')
        file_name = file.get('name')
        file_size = int(file.get('size', 0)) / 1024 / 1024
        
        logger.info(f"File uploaded to personal drive: {file_name}")
        
        return {
            'id': file_id,
            'name': file_name,
            'size_mb': round(file_size, 2),
            'link': f"https://drive.google.com/file/d/{file_id}/view"
        }, None
        
    except Exception as e:
        logger.error(f"Upload error: {e}")
        return None, str(e)
