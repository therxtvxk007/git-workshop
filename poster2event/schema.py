"""The structured shape a poster is extracted into.

Kept deliberately flat and constraint-free (no min/max lengths, no regex) so it
maps cleanly onto the Anthropic structured-outputs JSON-schema subset. Every
optional field defaults to None so the model can leave unknowns blank.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class Contact(BaseModel):
    name: str = Field(description="Contact person's name")
    phone: str = Field(description="Phone number, including country code if shown")


class Session(BaseModel):
    """One dated occurrence of the event (a multi-day event has several)."""

    day: Optional[int] = Field(
        default=None, description="Day number if the poster labels one (Day 1, Day 2)"
    )
    title: str = Field(description="This session's title, e.g. 'Debate'")
    date: Optional[str] = Field(
        default=None, description="ISO date YYYY-MM-DD. Infer the year from context."
    )
    start_time: Optional[str] = Field(
        default=None, description="24-hour start time HH:MM, e.g. '16:30'"
    )
    venue: Optional[str] = Field(default=None, description="Room / building / location")
    note: Optional[str] = Field(
        default=None,
        description="Any qualifier, e.g. 'must qualify from Day 1', 'finals'",
    )


class EventData(BaseModel):
    """Everything worth pulling off a poster to create the event."""

    event_name: str = Field(description="The main event name, e.g. 'VERTEXA'")
    fest: Optional[str] = Field(
        default=None, description="Parent fest/series, e.g. \"KRANTHI'26\""
    )
    tagline: Optional[str] = Field(
        default=None, description="Subtitle, e.g. 'Debate x Design Dilemma'"
    )
    slogan: Optional[str] = Field(
        default=None, description="Marketing slogan, e.g. 'Think. Argue. Design. Build.'"
    )
    organizer: Optional[str] = Field(
        default=None, description="Organizing body/club, plus institution if shown"
    )
    description: Optional[str] = Field(
        default=None, description="One or two sentence description of the event"
    )
    category: Optional[str] = Field(
        default=None,
        description="Best-guess category, e.g. 'Technical', 'Debate', 'Design'",
    )
    prize_pool_inr: Optional[int] = Field(
        default=None, description="Total prize pool in whole rupees; '1.5K' -> 1500"
    )
    entry_fee_note: Optional[str] = Field(
        default=None,
        description="Entry fee as written, e.g. 'GECians free; others INR 30'",
    )
    registration_url: Optional[str] = Field(
        default=None,
        description="Registration link. Leave null — this is filled from the QR code.",
    )
    contacts: List[Contact] = Field(
        default_factory=list, description="Contact people listed on the poster"
    )
    sessions: List[Session] = Field(
        default_factory=list, description="Each dated session/round of the event"
    )
