import asyncio
import logging
from typing import Dict, Optional
from core.firebase import get_db
from core.utils import ensure_timezone_aware, get_current_utc_datetime
from core.email import send_light_on_notification

logger = logging.getLogger(__name__)

class LightTimeoutManager:
    def __init__(self):
        self.active_tasks: Dict[str, Dict[str, asyncio.Task]] = {}
        self.monitoring_task: Optional[asyncio.Task] = None
        self.is_running = False
        self.lock = asyncio.Lock()

    async def start_monitoring(self):
        if not self.is_running:
            self.is_running = True
            self.monitoring_task = asyncio.create_task(self._monitor_lights())
            logger.info("Light timeout monitoring started")

    async def stop_monitoring(self):
        self.is_running = False
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
        async with self.lock:
            for user_tasks in self.active_tasks.values():
                for task in user_tasks.values():
                    task.cancel()
            self.active_tasks.clear()
        logger.info("Light timeout monitoring stopped")

    async def _monitor_lights(self):
        while self.is_running:
            try:
                await self._check_all_lights()
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in light monitoring: {str(e)}")
                await asyncio.sleep(30)

    async def _check_all_lights(self):
        db = get_db()
        users_ref = db.collection("users")
        users = users_ref.stream()

        for user_doc in users:
            user_data = user_doc.to_dict()
            user_id = user_doc.id
            email = user_data.get("email")
            if not email:
                continue
            if not user_data.get("auto_timeout_enabled", True):
                continue

            lights_ref = db.collection("users").document(user_id).collection("light")
            light_docs = lights_ref.stream()

            for light_doc in light_docs:
                light_data = light_doc.to_dict()
                light_id = light_doc.id

                status = light_data.get("status")
                timestamp = light_data.get("timestamp")

                if status == "ON" and timestamp:
                    timeout_seconds = user_data.get("light_timeout_seconds", 600)
                    notification_seconds = user_data.get("light_notification_seconds", 300)
                    notified = light_data.get("notification_sent", False)

                    turn_on_time = ensure_timezone_aware(timestamp)
                    current_time = get_current_utc_datetime()
                    time_diff = (current_time - turn_on_time).total_seconds()

                    if time_diff >= timeout_seconds:
                        await self._turn_off_light(email, user_id, light_id)
                        logger.info(f"Auto-turned off {light_id} for {email} after {time_diff:.1f} seconds")
                    else:
                        await self.schedule_light_turnoff(email, user_id, timeout_seconds - time_diff, light_id)

                        if not notified and time_diff >= notification_seconds:
                            send_light_on_notification(email, user_data.get("username"), int(notification_seconds / 60))
                            logger.info(f"Sent early notification for {light_id} to {email}")
                            lights_ref.document(light_id).update({"notification_sent": True})

    async def schedule_light_turnoff(self, email: str, user_id: str, delay_seconds: float, light_id: str):
        async with self.lock:
            if email not in self.active_tasks:
                self.active_tasks[email] = {}
            if light_id in self.active_tasks[email]:
                self.active_tasks[email][light_id].cancel()
            if delay_seconds > 0 and delay_seconds <= 86400:
                task = asyncio.create_task(self._delayed_light_turnoff(email, user_id, delay_seconds, light_id))
                self.active_tasks[email][light_id] = task
                logger.info(f"Scheduled light turn-off for {email}'s {light_id} in {delay_seconds:.1f} seconds")

    async def _delayed_light_turnoff(self, email: str, user_id: str, delay_seconds: float, light_id: str):
        try:
            await asyncio.sleep(delay_seconds)
            await self._turn_off_light(email, user_id, light_id)
            logger.info(f"Auto-turned off {light_id} for {email} after scheduled delay")
        except asyncio.CancelledError:
            logger.info(f"Turn-off cancelled for {light_id} of {email}")
        except Exception as e:
            logger.error(f"Error in delayed turn-off for {light_id} of {email}: {str(e)}")
        finally:
            async with self.lock:
                if email in self.active_tasks and light_id in self.active_tasks[email]:
                    del self.active_tasks[email][light_id]

    async def _turn_off_light(self, email: str, user_id: str, light_id: str):
        try:
            db = get_db()
            light_ref = db.collection("users").document(user_id).collection("light").document(light_id)
            light_doc = light_ref.get()
            if light_doc.exists and light_doc.to_dict().get("status") == "ON":
                light_ref.set({
                    "status": "OFF",
                    "auto_turned_off": True,
                    "turned_off_at": get_current_utc_datetime(),
                    "notification_sent": False
                }, merge=True)
                logger.info(f"Successfully auto-turned off {light_id} for {email}")
        except Exception as e:
            logger.error(f"Error turning off {light_id} for {email}: {str(e)}")

    async def cancel_timeout(self, email: str):
        async with self.lock:
            if email in self.active_tasks:
                for task in self.active_tasks[email].values():
                    task.cancel()
                del self.active_tasks[email]
                logger.info(f"Cancelled all timeouts for {email}")

timeout_manager = LightTimeoutManager()
