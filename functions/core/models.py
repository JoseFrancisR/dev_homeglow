from pydantic import BaseModel, field_validator, model_validator
from typing import Optional
from datetime import datetime

# Structured data to be used for the endpoints

class LightCommand(BaseModel):
    status: str
    light_id: Optional[str] = None

class TimeoutRequest(BaseModel):
    email: str
    hours: Optional[int] = 0
    minutes: Optional[int] = 0
    seconds: Optional[int] = 0

    @field_validator('hours')
    @classmethod
    def validate_hours(cls, hrs):
        if hrs < 0 or hrs > 23:
            raise ValueError('Hours must be between 0 and 23')
        return hrs

    @field_validator('minutes')
    @classmethod
    def validate_minutes(cls, min):
        if min < 0 or min > 59:
            raise ValueError('Minutes must be between 0 and 59')
        return min

    @field_validator('seconds')
    @classmethod
    def validate_seconds(cls, sec):
        if sec < 0 or sec > 59:
            raise ValueError('Seconds must be between 0 and 59')
        return sec

class AutoTimeoutToggleRequest(BaseModel):
    email: str
    enabled: bool

class register_device_model(BaseModel):
    device_id: str
    nickname: str

class EnergyMonitoring(BaseModel):
    device_id: str
    light_id: str
    energy_wh: float
    timestamp: Optional[datetime] = None

class individual_energy_monitoring(BaseModel):
    device_id: str
    light_id: str
    energy_wh: float
    timestamp: Optional[datetime] = None

class PairDeviceRequest(BaseModel):
    device_id: str
    email: str

class LightScheduleUpdate(BaseModel):
    wake_up: Optional[str] = None
    sleep: Optional[str] = None
    wake_up_light_id: Optional[str] = None
    sleep_light_id: Optional[str] = None

    @model_validator(mode='after')
    @classmethod
    def check_at_least_one_time(cls, values):
        if not values.wake_up and not values.sleep:
            raise ValueError("At least one of 'wake_up' or 'sleep' must be provided")
        return values
