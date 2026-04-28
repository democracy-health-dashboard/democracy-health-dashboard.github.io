import os
from dotenv import load_dotenv

# Load variables from a local .env file
load_dotenv()

def get_secret(key_name):
    """
    Retrieves a secret from local environment variables.
    """
    val = os.getenv(key_name)
    if not val:
        raise ValueError(f"Secret {key_name} not found in environment.")
    return val
