import asyncio
import logging
from typing import Dict, Optional
from core.firebase import get_db
from core.utils import ensure_timezone_aware, get_current_utc_datetime
from core.email import send_light_on_notification

logger = logging.getLogger(__name__)

class LightTimeoutManager:
    def __init__(self):
        self.tasks: Dict[str, Dict[str, asyncio.Task]] = {}
        self.monitor_task: Optional[asyncio.Task] = None
        self.running = False
        self.lock = asyncio.Lock()

    async def start_monitoring(self):
        if self.running:
            return
        self.running = True
        self.monitor_task = asyncio.create_task(self._monitor_lights())
        logger.info("Started light timeout monitor.")

    async def stop_monitoring(self):
        self.running = False
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass

        async with self.lock:
            for task_map in self.tasks.values():
                for task in task_map.values():
                    task.cancel()
            self.tasks.clear()

        logger.info("Stopped light timeout monitor.")

    async def _monitor_lights(self):
        while self.running:
            try:
                await self._check_all_lights()
            except Exception as e:
                logger.error(f"Monitoring error: {e}")
            await asyncio.sleep(30)

    async def _check_all_lights(self):
        db = get_db()
        for user_doc in db.collection("users").stream():
            user = user_doc.to_dict()
            user_id = user_doc.id
            email = user.get("email")
            if not email or not user.get("auto_timeout_enabled", True):
                continue

            light_ref = db.collection("users").document(user_id).collection("light")
            for light_doc in light_ref.stream():
                light = light_doc.to_dict()
                light_id = light_doc.id

                if light.get("status") != "ON" or not light.get("timestamp"):
                    continue

                on_time = ensure_timezone_aware(light["timestamp"])
                now = get_current_utc_datetime()
                elapsed = (now - on_time).total_seconds()

                timeout = user.get("light_timeout_seconds", 600)
                notify_time = user.get("light_notification_seconds", 300)
                notified = light.get("notification_sent", False)

                if elapsed >= timeout:
                    await self._turn_off_light(email, user_id, light_id)
                    logger.info(f"Auto-turned off {light_id} for {email} after {elapsed:.1f} seconds.")
                else:
                    await self._schedule_light_turnoff(email, user_id, timeout - elapsed, light_id)

                    if not notified and elapsed >= notify_time:
                        send_light_on_notification(email, user.get("username"), notify_time // 60)
                        logger.info(f"Notification sent to {email} for {light_id}.")
                        light_ref.document(light_id).update({"notification_sent": True})

    async def _schedule_light_turnoff(self, email: str, user_id: str, delay: float, light_id: str):
        if delay <= 0 or delay > 86400:
            return

        async with self.lock:
            self.tasks.setdefault(email, {})
            if light_id in self.tasks[email]:
                self.tasks[email][light_id].cancel()

            task = asyncio.create_task(self._delayed_light_turnoff(email, user_id, delay, light_id))
            self.tasks[email][light_id] = task
            logger.info(f"Scheduled turn-off for {light_id} in {delay:.1f} seconds.")

    async def _delayed_light_turnoff(self, email: str, user_id: str, delay: float, light_id: str):
        try:
            await asyncio.sleep(delay)
            await self._turn_off_light(email, user_id, light_id)
            logger.info(f"{light_id} for {email} auto-turned off after delay.")
        except asyncio.CancelledError:
            logger.info(f"Turn-off for {light_id} was cancelled for {email}.")
        except Exception as e:
            logger.error(f"Error auto-turning off {light_id} for {email}: {e}")
        finally:
            async with self.lock:
                self.tasks[email].pop(light_id, None)

    async def _turn_off_light(self, email: str, user_id: str, light_id: str):
        try:
            db = get_db()
            ref = db.collection("users").document(user_id).collection("light").document(light_id)
            doc = ref.get()
            if doc.exists and doc.to_dict().get("status") == "ON":
                ref.set({
                    "status": "OFF",
                    "auto_turned_off": True,
                    "turned_off_at": get_current_utc_datetime(),
                    "notification_sent": False
                }, merge=True)
                logger.info(f"{light_id} turned off for {email}.")
        except Exception as e:
            logger.error(f"Failed to turn off {light_id} for {email}: {e}")

    async def cancel_all(self, email: str):
        async with self.lock:
            if email in self.tasks:
                for task in self.tasks[email].values():
                    task.cancel()
                del self.tasks[email]
                logger.info(f"Cancelled all light tasks for {email}.")

timeout_manager = LightTimeoutManager()
