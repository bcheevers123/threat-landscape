"""Data models for conference events."""
from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class ConferenceEvent(BaseModel):
    name: str
    url: str
    start_date: date
    end_date: date
    city: str
    country: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    tags: list[str] = Field(default_factory=list)
    description: str = ""
    virtual: bool = False
    cost: str = "Unknown"
    cfp_url: Optional[str] = None
    cfp_deadline: Optional[date] = None

    @property
    def id(self) -> str:
        """URL-safe identifier derived from the event name."""
        import re
        slug = re.sub(r"[^a-z0-9]+", "-", self.name.lower()).strip("-")
        return slug

    @property
    def location(self) -> str:
        return f"{self.city}, {self.country}"

    @property
    def status(self) -> str:
        today = date.today()
        if self.end_date < today:
            return "past"
        if self.start_date <= today:
            return "ongoing"
        return "upcoming"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "city": self.city,
            "country": self.country,
            "location": self.location,
            "lat": self.lat,
            "lon": self.lon,
            "tags": self.tags,
            "description": self.description,
            "virtual": self.virtual,
            "cost": self.cost,
            "cfp_url": self.cfp_url,
            "cfp_deadline": self.cfp_deadline.isoformat() if self.cfp_deadline else None,
            "status": self.status,
        }


class ConferencesOutput(BaseModel):
    events: list[ConferenceEvent]
    generated_at: str
    total_upcoming: int
    total_countries: int
