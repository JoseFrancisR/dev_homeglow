# This starts the getting of database 

from firebase_admin import initialize_app, credentials, firestore
import firebase_admin
from pathlib import Path
from dotenv import load_dotenv
import os
import logging

env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=env_path)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

firebase_initialized = False
firestore_client = None

def initialize_firebase():
    global firebase_initialized

    if firebase_initialized:
        return

    if not firebase_admin._apps:
        try:
            initialize_app()
            logger.info("Firebase initialized successfully.")
            firebase_initialized = True
        except Exception as error:
            logger.exception("Failed to initialize Firebase:")
            raise


def get_db():
    global firestore_client
    if firestore_client is None:
        initialize_firebase()
        firestore_client = firestore.client()
    return firestore_client