from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ChargerStatus(str, Enum):
    AVAILABLE = "available"
    OCCUPIED = "occupied"
    FAULTED = "faulted"
    OFFLINE = "offline"


class SessionStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"


@dataclass
class PowerKw:
    value: float

    def __post_init__(self):
        if self.value < 0:
            raise ValueError("Power cannot be negative")

    def to_float(self):
        return round(float(self.value), 2)


@dataclass
class EnergyKwh:
    value: float

    def __post_init__(self):
        if self.value < 0:
            raise ValueError("Energy cannot be negative")

    def to_float(self):
        return round(float(self.value), 2)


@dataclass
class MoneyDkk:
    value: float

    def __post_init__(self):
        if self.value < 0:
            raise ValueError("Money cannot be negative")

    def to_float(self):
        return round(float(self.value), 2)


@dataclass
class Charger:
    id: str
    name: str
    location: str
    region: str = "DK2"
    sockets: list[Socket] = field(default_factory=list)

    @classmethod
    def create(cls, charger_id, name, location, region, socket_specs, heartbeat):
        charger = cls(id=charger_id, name=name, location=location, region=region)
        for spec in socket_specs:
            charger.add_socket(
                max_power_kw=float(spec["max_power_kw"]),
                connector_type=spec.get("connector_type", "Type2"),
                heartbeat=heartbeat,
            )
        return charger

    def add_socket(self, max_power_kw, connector_type, heartbeat):
        socket_number = len(self.sockets) + 1
        socket = Socket(
            id=f"{self.id}-S{socket_number}",
            charger_id=self.id,
            socket_number=socket_number,
            max_power_kw=max_power_kw,
            status=ChargerStatus.AVAILABLE,
            connector_type=connector_type,
            last_heartbeat=heartbeat,
        )
        self.sockets.append(socket)
        return socket

    def to_record(self):
        return {
            "id": self.id,
            "name": self.name,
            "location": self.location,
            "region": self.region,
            "sockets": [socket.to_record() for socket in self.sockets],
        }


@dataclass
class Socket:
    id: str
    charger_id: str
    socket_number: int
    max_power_kw: float
    status: ChargerStatus
    connector_type: str
    last_heartbeat: str | None = None

    def can_start_session(self):
        return self.status == ChargerStatus.AVAILABLE

    def with_status(self, status: ChargerStatus, heartbeat: str):
        return Socket(
            self.id, self.charger_id, self.socket_number,
            self.max_power_kw, status, self.connector_type, heartbeat,
        )

    def to_record(self):
        return {
            "id": self.id,
            "charger_id": self.charger_id,
            "socket_number": self.socket_number,
            "max_power_kw": self.max_power_kw,
            "status": self.status.value,
            "connector_type": self.connector_type,
            "last_heartbeat": self.last_heartbeat,
        }


@dataclass
class TelemetryReading:
    socket_id: str
    power_kw: PowerKw
    voltage: float
    current: float
    status: ChargerStatus
    timestamp: datetime

    def to_record(self):
        return {
            "socket_id": self.socket_id,
            "power_kw": self.power_kw.to_float(),
            "voltage": self.voltage,
            "current": self.current,
            "status": self.status.value,
            "timestamp": self.timestamp.isoformat(timespec="seconds"),
        }


@dataclass
class ChargingSession:
    id: int | None
    socket_id: str
    contract_id: str
    start_time: datetime
    end_time: datetime | None
    energy_kwh: EnergyKwh
    price_dkk: MoneyDkk
    status: SessionStatus

    @classmethod
    def start(cls, socket_id: str, contract_id: str, started_at: datetime):
        return cls(
            id=None,
            socket_id=socket_id,
            contract_id=contract_id,
            start_time=started_at,
            end_time=None,
            energy_kwh=EnergyKwh(0),
            price_dkk=MoneyDkk(0),
            status=SessionStatus.ACTIVE,
        )

    def complete(self, ended_at: datetime, energy_kwh: EnergyKwh, price_per_kwh: float):
        return ChargingSession(
            id=self.id,
            socket_id=self.socket_id,
            contract_id=self.contract_id,
            start_time=self.start_time,
            end_time=ended_at,
            energy_kwh=energy_kwh,
            price_dkk=MoneyDkk(energy_kwh.to_float() * price_per_kwh),
            status=SessionStatus.COMPLETED,
        )

    def to_record(self):
        return {
            "id": self.id,
            "socket_id": self.socket_id,
            "contract_id": self.contract_id,
            "start_time": self.start_time.isoformat(timespec="seconds"),
            "end_time": self.end_time.isoformat(timespec="seconds") if self.end_time else None,
            "energy_kwh": self.energy_kwh.to_float(),
            "price_dkk": self.price_dkk.to_float(),
            "status": self.status.value,
        }


@dataclass
class Incident:
    charger_id: str
    description: str
    severity: str
    created_at: datetime
    resolved_at: datetime | None = None

    def to_record(self):
        return {
            "charger_id": self.charger_id,
            "description": self.description,
            "severity": self.severity,
            "created_at": self.created_at.isoformat(timespec="seconds"),
            "resolved_at": self.resolved_at.isoformat(timespec="seconds") if self.resolved_at else None,
        }


@dataclass
class DomainEvent:
    name: str
    entity_id: str
    description: str
    created_at: datetime

    def to_record(self):
        return {
            "event_name": self.name,
            "entity_id": self.entity_id,
            "description": self.description,
            "created_at": self.created_at.isoformat(timespec="seconds"),
        }


@dataclass(frozen=True)
class LoadForecast:
    next_hour_kw: float
    model: str
    sample_size: int
    r2_score: float | None = None
    feature_names: tuple[str, ...] = ()
    coefficients: tuple[float, ...] = ()
    intercept: float | None = None

    def to_record(self):
        return {
            "next_hour_kw": self.next_hour_kw,
            "model": self.model,
            "sample_size": self.sample_size,
            "r2_score": self.r2_score,
            "feature_names": list(self.feature_names),
            "coefficients": list(self.coefficients),
            "intercept": self.intercept,
        }
