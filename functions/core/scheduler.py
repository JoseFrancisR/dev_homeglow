from datetime import datetime
from core.firebase import get_db

#this functions gets both wake up(light turn on) and sleep(light turn off)
def set_light_schedule(user_id: str, wake_up: str = None, sleep: str = None):
    db = get_db()
    schedule_ref = db.collection("users").document(user_id).collection("settings").document("light_schedule")

    update_data = {}
    if wake_up is not None:
        update_data["wake_up"] = wake_up
    if sleep is not None:
        update_data["off_time"] = sleep

    if update_data:
        schedule_ref.set(update_data, merge=True)

def get_light_schedule(user_id: str):
    db = get_db()
    schedule_ref = db.collection("users").document(user_id).collection("settings").document("light_schedule")
    doc = schedule_ref.get()
    if doc.exists:
        return doc.to_dict()
    return None
