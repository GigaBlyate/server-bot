#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import pickle

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ['https://www.googleapis.com/auth/drive.file']
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(PROJECT_DIR, 'token.pickle')
CREDENTIALS_FILE = os.path.join(PROJECT_DIR, 'oauth-credentials.json')


def main():
    if not os.path.exists(CREDENTIALS_FILE):
        print(f'❌ File {CREDENTIALS_FILE} not found!')
        print('Download OAuth 2.0 Desktop App credentials from Google Cloud Console first.')
        return

    print('\n' + '=' * 60)
    print('🔐 GOOGLE DRIVE AUTHORIZATION')
    print('=' * 60)
    print('This script opens a local browser flow for a Desktop App OAuth client.')
    print('If your server has no browser, run this script on your local PC with the same')
    print('oauth-credentials.json, then copy token.pickle back to the project directory.')
    print('=' * 60)

    try:
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
        creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'wb') as token:
            pickle.dump(creds, token)
        print(f'\n✅ Authorization successful! Tokens saved to {TOKEN_FILE}')
        print('\n📦 Bot can now upload files to Google Drive')
    except Exception as exc:
        print(f'\n❌ Error: {exc}')


if __name__ == '__main__':
    main()
