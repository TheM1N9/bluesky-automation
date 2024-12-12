from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
import json
import os

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def generate_tokens():
    # Load client configuration from credentials.json
    with open("credentials.json", "r") as f:
        client_config = json.load(f)

    # Create flow instance
    flow = InstalledAppFlow.from_client_secrets_file(
        "credentials.json", scopes=SCOPES, redirect_uri="http://localhost"
    )

    # Run local server to get authorization
    creds = flow.run_local_server(port=0)

    # Create a dictionary with all necessary tokens
    tokens = {
        "GMAIL_CLIENT_ID": client_config["installed"]["client_id"],
        "GMAIL_CLIENT_SECRET": client_config["installed"]["client_secret"],
        "GMAIL_REFRESH_TOKEN": creds.refresh_token,
        "GMAIL_TOKEN": creds.token,
    }

    # Save to a file
    with open("aws_gmail_tokens.txt", "w") as f:
        for key, value in tokens.items():
            f.write(f"{key}={value}\n")

    print("\n=== Gmail Tokens Generated Successfully ===")
    print("Tokens have been saved to 'aws_gmail_tokens.txt'")
    print("\nAdd these values to your AWS environment variables:")
    for key, value in tokens.items():
        print(f"\n{key}={value}")


if __name__ == "__main__":
    generate_tokens()
