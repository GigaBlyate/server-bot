#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import pickle
import json
import webbrowser

SCOPES = ['https://www.googleapis.com/auth/drive.file']
TOKEN_FILE = 'token.pickle'
CREDENTIALS_FILE = 'oauth-credentials.json'

def main():
    if not os.path.exists(CREDENTIALS_FILE):
        print(f"❌ File {CREDENTIALS_FILE} not found!")
        print("Please download OAuth 2.0 credentials from Google Cloud Console")
        return

    print("\n" + "="*60)
    print("🔐 GOOGLE DRIVE AUTHORIZATION")
    print("="*60)

    with open(CREDENTIALS_FILE, 'r') as f:
        client_config = json.load(f)

    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri='urn:ietf:wg:oauth:2.0:oob'
    )

    auth_url, _ = flow.authorization_url(prompt='consent')

    print("\n🔗 Open this link in your browser:")
    print("\n" + auth_url)
    print("\n" + "="*60)
    print("\n📌 Instructions:")
    print("1. Copy the link above")
    print("2. Open it in your browser on your computer")
    print("3. Log in to your Google account")
    print("4. Click 'Allow'")
    print("5. You will get a code")
    print("6. Copy that code and paste it below")
    print("="*60)

    try:
        webbrowser.open(auth_url)
        print("\n🌐 Browser opened automatically!")
    except:
        print("\n⚠️ Could not open browser automatically")

    print("\n👉 Paste the authorization code here and press Enter:")
    auth_code = input().strip()

    if not auth_code:
        print("❌ No code provided")
        return

    try:
        flow.fetch_token(code=auth_code)
        creds = flow.credentials

        with open(TOKEN_FILE, 'wb') as token:
            pickle.dump(creds, token)

        print(f"\n✅ Authorization successful! Tokens saved to {TOKEN_FILE}")
        print("\n📦 Bot can now upload files to Google Drive")

    except Exception as e:
        print(f"\n❌ Error: {e}")

if __name__ == '__main__':
    main()
