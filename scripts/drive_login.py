"""One-time Google login that lets the app read the Drive folder AS YOU (no folder re-sharing needed).

Run this on your own computer (it opens a browser), not inside Docker:

    pip install google-auth-oauthlib
    python scripts/drive_login.py --client-secret path/to/client_secret.json

It writes secrets/oauth-token.json (git-ignored). The file holds a long-lived refresh token: keep it
private, and revoke it any time at https://myaccount.google.com/permissions. Only read-only scopes are
requested (Drive read-only, Sheets read-only).

Getting client_secret.json: Google Cloud console > APIs & Services > enable "Google Drive API" and
"Google Sheets API" > OAuth consent screen (choose "Internal" if your Google Workspace allows it, which
needs no Google review) > Credentials > Create credentials > OAuth client ID > Application type "Desktop app"
> download the JSON.
"""
import argparse
import json
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/drive.readonly", "https://www.googleapis.com/auth/spreadsheets.readonly"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client-secret", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "secrets" / "oauth-token.json")
    args = ap.parse_args()

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(args.client_secret), SCOPES)
    # offline + consent forces Google to return a refresh token even if you approved this app before
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    if not creds.refresh_token:
        raise SystemExit("Google did not return a refresh token. Remove the app at "
                         "https://myaccount.google.com/permissions and run this again.")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "type": "authorized_user", "client_id": creds.client_id, "client_secret": creds.client_secret,
        "refresh_token": creds.refresh_token, "token_uri": creds.token_uri,
    }))
    try:
        args.out.chmod(0o600)
    except OSError:
        pass
    print(f"Saved {args.out}. Next: docker compose run --rm api python -m app.etl.drive_check")


if __name__ == "__main__":
    main()
