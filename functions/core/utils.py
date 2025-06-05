from datetime import datetime, timezone

def get_current_utc_datetime():
    return datetime.now(timezone.utc)

def ensure_timezone_aware(dt):
    if dt is None:
        return None
    if hasattr(dt, 'timestamp'):
        return dt
    if dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=timezone.utc)

def calculate_total_seconds(hours: int, minutes: int, seconds: int) -> int:
    return (hours or 0) * 3600 + (minutes or 0) * 60 + (seconds or 0)

def format_timeout_display(total_seconds: int) -> str:
    
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    parts = []
    if hours > 0:
        parts.append(f"{hours} hour/s")
    if minutes > 0:
        parts.append(f"{minutes} minute/s")
    if seconds > 0:
        parts.append(f"{seconds} second/s")

    return ", ".join(parts) or "0 seconds"
