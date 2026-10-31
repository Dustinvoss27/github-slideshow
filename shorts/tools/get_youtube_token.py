"""Run ONCE on your own computer to get a YouTube refresh token for GitHub Actions.

1. Google Cloud Console -> create a project -> enable "YouTube Data API v3".
2. OAuth consent screen -> External -> add yourself as a test user -> then PUBLISH the app
   ("In production"). In "Testing" mode refresh tokens expire after 7 days.
3. Credentials -> Create OAuth client ID -> "Desktop app" -> download JSON as client_secret.json
4. pip install google-auth-oauthlib
5. python tools/get_youtube_token.py path/to/client_secret.json
   Sign in with the Google account that OWNS the channel (pick the channel if asked).
6. Copy the three printed values into GitHub -> Settings -> Secrets and variables -> Actions.
"""
import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

path = sys.argv[1] if len(sys.argv) > 1 else "client_secret.json"
flow = InstalledAppFlow.from_client_secrets_file(path, SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
info = json.load(open(path))
info = info.get("installed") or info.get("web")

print("\nAdd these as GitHub Actions secrets:\n")
print(f"YT_CLIENT_ID={info['client_id']}")
print(f"YT_CLIENT_SECRET={info['client_secret']}")
print(f"YT_REFRESH_TOKEN={creds.refresh_token}")
