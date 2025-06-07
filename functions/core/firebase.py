# core/firebase.py

from firebase_admin import initialize_app, credentials, firestore
import firebase_admin
from pathlib import Path
from dotenv import load_dotenv
import os
import logging

# Load .env
env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=env_path)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Globals
firebase_initialized = False
firestore_client = None

def initialize_firebase():
    global firebase_initialized

    if firebase_initialized:
        return

    if not firebase_admin._apps:
        try:
            # Always resolve absolute path to avoid FileNotFoundError
            service_account_path = Path(__file__).parent.parent / "serviceAccountKey.json"
            service_account_path = service_account_path.resolve()

            # Check if file exists first
            if not service_account_path.exists():
                raise FileNotFoundError(f"Service account key not found: {service_account_path}")

            logger.info(f"🔑 Using Firebase service account key: {service_account_path}")

            cred = credentials.Certificate(str(service_account_path))
            initialize_app(cred)
            
            logger.info("✅ Firebase initialized successfully.")
            firebase_initialized = True

        except Exception as error:
            logger.exception("❌ Failed to initialize Firebase:")
            raise

def get_db():
    global firestore_client
    if firestore_client is None:
        initialize_firebase()
        firestore_client = firestore.client()
    return firestore_client
