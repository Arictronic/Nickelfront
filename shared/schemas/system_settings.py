"""Schemas for global technical settings."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SystemSettingsResponse(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)
    schema_: dict[str, Any] = Field(default_factory=dict, alias="schema")

    model_config = ConfigDict(populate_by_name=True)


class SystemSettingsSectionUpdate(BaseModel):
    value: dict[str, Any] = Field(default_factory=dict)


class SystemSettingsSectionResponse(BaseModel):
    section: str
    value: dict[str, Any]
