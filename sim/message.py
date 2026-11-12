"""Common JSON message format for all MQTT payloads.

Schema:
    {"ts": ISO-8601 UTC, "source": str, "valeur": number|str|list|dict, "unite": str}

Example:
    {"ts": "2026-10-09T08:05:00Z", "source": "loop-c3-n", "valeur": 14, "unite": "vehicules"}
"""
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
REQUIRED_KEYS = ("ts", "source", "valeur", "unite")

JSON_SCHEMA = {
    "type": "object",
    "required": list(REQUIRED_KEYS),
    "properties": {
        "ts": {"type": "string", "format": "date-time"},
        "source": {"type": "string", "minLength": 1},
        "valeur": {},
        "unite": {"type": "string"},
    },
    "additionalProperties": False,
}


def now_ts():
    return datetime.now(timezone.utc).strftime(TS_FORMAT)


@dataclass
class Message:
    source: str
    valeur: object
    unite: str = ""
    ts: str = field(default_factory=now_ts)

    def __post_init__(self):
        self.validate()

    def validate(self):
        if not isinstance(self.source, str) or not self.source:
            raise ValueError("source must be a non-empty string")
        if not isinstance(self.unite, str):
            raise ValueError("unite must be a string")
        try:
            datetime.strptime(self.ts, TS_FORMAT)
        except (TypeError, ValueError):
            raise ValueError(f"ts must match {TS_FORMAT}, got {self.ts!r}")

    def to_dict(self):
        return {"ts": self.ts, "source": self.source,
                "valeur": self.valeur, "unite": self.unite}

    def to_json(self):
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, payload):
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8")
        data = json.loads(payload)
        if not isinstance(data, dict):
            raise ValueError("payload must be a JSON object")
        missing = [k for k in REQUIRED_KEYS if k not in data]
        if missing:
            raise ValueError(f"missing keys: {missing}")
        extra = set(data) - set(REQUIRED_KEYS)
        if extra:
            raise ValueError(f"unexpected keys: {sorted(extra)}")
        return cls(source=data["source"], valeur=data["valeur"],
                   unite=data["unite"], ts=data["ts"])
