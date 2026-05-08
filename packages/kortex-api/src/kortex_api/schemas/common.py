"""Shared schemas."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class TimestampedOut(APIModel):
    public_id: uuid.UUID
    created_at: dt.datetime
    updated_at: dt.datetime
