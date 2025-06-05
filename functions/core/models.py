from pydantic import BaseModel, validator
from typing import Optional
from datetime import datetime

#Structured data to be used for the endpoints 
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
    def validate_hours(cls, hrs):
        if hrs < 0 or hrs > 23:
            raise ValueError('Hours must be between 0 and 23')
        return hrs

    @validator('minutes')
    def validate_minutes(cls, min):
        if min < 0 or min > 59:
            raise ValueError('Minutes must be between 0 and 59')
        return min

    @validator('seconds')
    def validate_seconds(cls, sec):
        if sec < 0 or sec > 59:
            raise ValueError('Seconds must be between 0 and 59')
        return sec
    
class AutoTimeoutToggleRequest(BaseModel):
    email: str
    enabled: bool

class energy_monitoring(BaseModel):
    device_id: str
    watts: float
    timestamp: datetime

class register_device_model(BaseModel):
    device_id: str
    nickname: str