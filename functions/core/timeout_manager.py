import asyncio
import logging
from typing import Dict, Optional
from core.firebase import get_db
from core.utils import ensure_timezone_aware, get_current_utc_datetime
from core.email import send_light_on_notification
import pytz

logger = logging.getLogger(__name__)

class LightTimeoutManager:
    WAKE_SLEEP_RUN_WINDOW_SECONDS = 60  # run wake/sleep only once per minute

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
            await asyncio.sleep(30)  # Polling interval

    async def _check_all_lights(self):
        db = get_db()
        now = get_current_utc_datetime()

        for user_doc in db.collection("users").stream():
            user = user_doc.to_dict()
            user_id = user_doc.id
            email = user.get("email")
            if not email:
                continue

            ### WAKE / SLEEP ROUTINES ###
            try:
                schedule_ref = db.collection("users").document(user_id).collection("settings").document("light_schedule")
                schedule_doc = schedule_ref.get()

                if schedule_doc.exists:
                    schedule = schedule_doc.to_dict()
                    wake_up_time_str = schedule.get("wake_up")
                    sleep_time_str = schedule.get("sleep")

                    # Read last_run timestamps
                    last_run_ref = db.collection("users").document(user_id).collection("settings").document("routine_status")
                    last_run_doc = last_run_ref.get()
                    last_run = last_run_doc.to_dict() if last_run_doc.exists else {}

                    if wake_up_time_str:
                        wake_up_dt = ensure_timezone_aware(now.replace(
                            hour=int(wake_up_time_str.split(":")[0]),
                            minute=int(wake_up_time_str.split(":")[1]),
                            second=0,
                            microsecond=0
                        ))

                        last_wake_run_ts = last_run.get("wake_up_last_run")
                        if (now >= wake_up_dt and (now - wake_up_dt).total_seconds() < self.WAKE_SLEEP_RUN_WINDOW_SECONDS and
                            (not last_wake_run_ts or (now - ensure_timezone_aware(last_wake_run_ts)).total_seconds() > 3600)):
                            await self._turn_on_all_lights(user_id)
                            logger.info(f"✅ Ran Wake Up routine for {email}")

                            # Update last run
                            last_run_ref.set({
                                "wake_up_last_run": now
                            }, merge=True)

                    if sleep_time_str:
                        sleep_dt = ensure_timezone_aware(now.replace(
                            hour=int(sleep_time_str.split(":")[0]),
                            minute=int(sleep_time_str.split(":")[1]),
                            second=0,
                            microsecond=0
                        ))

                        last_sleep_run_ts = last_run.get("sleep_last_run")
                        if (now >= sleep_dt and (now - sleep_dt).total_seconds() < self.WAKE_SLEEP_RUN_WINDOW_SECONDS and
                            (not last_sleep_run_ts or (now - ensure_timezone_aware(last_sleep_run_ts)).total_seconds() > 3600)):
                            await self._turn_off_all_lights(user_id)
                            logger.info(f"✅ Ran Sleep routine for {email}")

                            # Update last run
                            last_run_ref.set({
                                "sleep_last_run": now
                            }, merge=True)

            except Exception as e:
                logger.error(f"❌ Error running Wake/Sleep routine for {email}: {e}")

            light_ref = db.collection("users").document(user_id).collection("light")
            for light_doc in light_ref.stream():
                light = light_doc.to_dict()
                light_id = light_doc.id

                if light.get("status") != "ON" or not light.get("timestamp"):
                    continue

                on_time = ensure_timezone_aware(light["timestamp"])
                elapsed = (now - on_time).total_seconds()

                timeout = user.get("light_timeout_seconds", 600)
                notify_time = light.get("notify_duration", 300)
                notified = light.get("notification_sent", False)

                # Schedule auto turn-off
                await self.schedule_light_turnoff(email, user_id, timeout - elapsed, light_id)

                # Send notification if needed
                if not notified and elapsed >= notify_time:
                    try:
                        send_light_on_notification(
                            to_email=email,
                            username=user.get("username"),
                            duration_minutes=int(elapsed // 60)
                        )
                        logger.info(f"✅ Notification sent to {email} for light {light_id}.")
                        light_ref.document(light_id).update({"notification_sent": True})
                    except Exception as e:
                        logger.error(f"❌ Failed to send notification to {email} for light {light_id}: {e}")

                # Auto turn OFF light if timeout exceeded
                if elapsed >= timeout:
                    await self._turn_off_light(email, user_id, light_id)
                    logger.info(f"✅ Auto-turned off {light_id} for {email} after {elapsed:.1f} seconds.")

    async def _turn_on_all_lights(self, user_id: str):
        db = get_db()
        light_ref = db.collection("users").document(user_id).collection("light")
        for light_doc in light_ref.stream():
            light_id = light_doc.id
            ref = light_ref.document(light_id)
            ref.set({
                "status": "ON",
                "timestamp": get_current_utc_datetime(),
                "auto_turned_off": False,
                "notification_sent": False
            }, merge=True)
            logger.info(f"✅ Turned ON {light_id} for user {user_id}")

    async def _turn_off_all_lights(self, user_id: str):
        db = get_db()
        light_ref = db.collection("users").document(user_id).collection("light")
        for light_doc in light_ref.stream():
            light_id = light_doc.id
            ref = light_ref.document(light_id)
            ref.set({
                "status": "OFF",
                "turned_off_at": get_current_utc_datetime(),
                "auto_turned_off": True,
                "notification_sent": False
            }, merge=True)
            logger.info(f"✅ Turned OFF {light_id} for user {user_id}")

    async def schedule_light_turnoff(self, email: str, user_id: str, delay: float, light_id: str):
        if delay <= 0 or delay > 86400:  # Ignore invalid delay
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
            logger.info(f"✅ {light_id} for {email} auto-turned off after delay.")
        except asyncio.CancelledError:
            logger.info(f"⏹️ Turn-off for {light_id} was cancelled for {email}.")
        except Exception as e:
            logger.error(f"❌ Error auto-turning off {light_id} for {email}: {e}")
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
                logger.info(f"✅ {light_id} turned off for {email}.")
        except Exception as e:
            logger.error(f"❌ Failed to turn off {light_id} for {email}: {e}")

    async def cancel_all(self, email: str):
        async with self.lock:
            if email in self.tasks:
                for task in self.tasks[email].values():
                    task.cancel()
                del self.tasks[email]
                logger.info(f"Cancelled all light tasks for {email}.")

    async def cancel_timeout_for_light(self, email: str, light_id: str):
        async with self.lock:
            if email in self.tasks and light_id in self.tasks[email]:
                self.tasks[email][light_id].cancel()
                del self.tasks[email][light_id]
                logger.info(f"Cancelled timeout for {light_id} of {email}.")
                if not self.tasks[email]:
                    del self.tasks[email]

# Singleton instance
timeout_manager = LightTimeoutManager()
