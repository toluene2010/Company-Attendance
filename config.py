import os
import json

def get_credentials():
    # Path to your service account JSON file
    creds_path = os.path.join(os.path.dirname(__file__), "service-account.json")
    
    # Check if the file exists
    if not os.path.exists(creds_path):
        raise FileNotFoundError(f"Service account file not found at {creds_path}")
    
    # Load the credentials
    with open(creds_path, 'r') as f:
        credentials = json.load(f)
    
    return credentials