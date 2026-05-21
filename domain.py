from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ChargerStatus(str, Enum):
    AVAILABLE = "available"
    OCCUPIED = "occupied"
    FAULTED = "faulted"
    OFFLINE = "offline"


@dataclass
class PowerKw:
    value: float

    def __post_init__(self):
        if self.value < 0:
            raise ValueError("Power cannot be negative")


@dataclass
class EnergyKwh:
    value: float

    def __post_init__(self):
        if self.value < 0:
            raise ValueError("Energy cannot be negative")


@dataclass
class MoneyDkk:
    value: float

    def __post_init__(self):
        if self.value < 0:
            raise ValueError("Money cannot be negative")


@dataclass
class Charger:
    id: str
    name: str
    location: str
    status: ChargerStatus
    max_power_kw: float
    last_heartbeat: str | None = None


@dataclass
class TelemetryReading:
    charger_id: str
    power_kw: PowerKw
    voltage: float
    current: float
    status: ChargerStatus
    timestamp: datetime


@dataclass
class ChargingSession:
    id: int | None
    charger_id: str
    contract_id: str
    start_time: datetime
    end_time: datetime | None
    energy_kwh: EnergyKwh
    price_dkk: float
    status: str


@dataclass
class Incident:
    charger_id: str
    description: str
    severity: str
    created_at: datetime
    resolved_at: datetime | None = None


@dataclass
class DomainEvent:
    name: str
    entity_id: str
    description: str
    created_at: datetime
