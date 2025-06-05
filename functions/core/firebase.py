from firebase_admin import initialize_app, credentials, firestore
import firebase_admin
from pathlib import Path
from dotenv import load_dotenv
import os
import logging

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent.parent / ".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_db = None
_app_initialized = False

def initialize_firebase():
    global _app_initialized
    if not _app_initialized and not firebase_admin._apps:
        try:
            initialize_app()
            logger.info("Firebase Admin initialized successfully")
            _app_initialized = True
        except Exception as e:
            logger.error(f"Failed to initialize Firebase Admin: {e}")
            raise

def get_db():
    global _db, _app_initialized
    if _db is None:
        if not _app_initialized:
            initialize_firebase()
        _db = firestore.client()
    return _db
