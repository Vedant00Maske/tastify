"""API shapes of the integrations domain (API_SPEC.md). Tokens never appear in any of them."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ImportOut(BaseModel):
    id: uuid.UUID
    provider: str
    status: str
    fetched: int
    matched: int
    imported: int
    duplicates: int
    error: str | None
    started_at: datetime
    finished_at: datetime | None


class ConnectionOut(BaseModel):
    status: str
    external_name: str | None
    scopes: list[str]
    connected_at: datetime
    last_import: ImportOut | None


class ProviderOut(BaseModel):
    provider: str
    name: str
    description: str
    auth: str
    capabilities: list[str]
    available: bool = Field(description="Configured on this server")
    max_export_tracks: int
    connection: ConnectionOut | None


class ProviderList(BaseModel):
    providers: list[ProviderOut]
    tokens_configured: bool = Field(description="Whether accounts can be connected at all")


class TokenConnectIn(BaseModel):
    token: str = Field(min_length=8, max_length=200)


class ImportIn(BaseModel):
    consent: bool = Field(
        description="The user agrees to copy their listening history into SONIQUEO."
    )


class AuthorizeOut(BaseModel):
    url: str


class ExportIn(BaseModel):
    provider: str = Field(max_length=32)


class ExportOut(BaseModel):
    provider: str
    status: str
    external_url: str | None
    exported: int
    unmatched: int
    attempts: int
    error: str | None
    updated_at: datetime
    completed_at: datetime | None


class ExportList(BaseModel):
    exports: list[ExportOut]


class RecordingOut(BaseModel):
    mbid: str
    title: str
    artist: str
    release: str | None
    length_ms: int | None
    url: str
    track_id: uuid.UUID | None = Field(description="The catalogue track, when SONIQUEO has it")


class RecordingSearchOut(BaseModel):
    query: str
    results: list[RecordingOut]
