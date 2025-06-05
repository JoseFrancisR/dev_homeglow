from pydantic import BaseModel, validator
from typing import Optional
from datetime import datetime

class LightCommand(BaseModel):
    email: str
    status: str
    light_id: Optional[str] = None

class TimeoutRequest(BaseModel):
    email: str
    hours: Optional[int] = 0
    minutes: Optional[int] = 0
    seconds: Optional[int] = 0

    @validator('hours')
    def validate_hours(cls, v):
        if v < 0 or v > 23:
            raise ValueError('Hours must be between 0 and 23')
        return v

    @validator('minutes')
    def validate_minutes(cls, v):
        if v < 0 or v > 59:
            raise ValueError('Minutes must be between 0 and 59')
        return v

    @validator('seconds')
    def validate_seconds(cls, v):
        if v < 0 or v > 59:
            raise ValueError('Seconds must be between 0 and 59')
        return v

class AutoTimeoutToggleRequest(BaseModel):
    email: str
    enabled: bool

class energy_monitoring(BaseModel):
    device_id: str
    watts: float
    timestamp: datetime