from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Suggestion item (DaData-style)
# ---------------------------------------------------------------------------

class SuggestionItem(BaseModel):
    value: str = Field(..., description="Display value of the suggestion")
    data: dict[str, Any] | None = Field(default=None, description="Structured data from the provider")


# ---------------------------------------------------------------------------
# City
# ---------------------------------------------------------------------------

class CitySuggestRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=255)


class CitySuggestResponse(BaseModel):
    suggestions: list[SuggestionItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Street
# ---------------------------------------------------------------------------

class StreetSuggestRequest(BaseModel):
    city: str = Field(..., min_length=1, max_length=255)
    query: str = Field(..., min_length=1, max_length=255)


class StreetSuggestResponse(BaseModel):
    suggestions: list[SuggestionItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# House
# ---------------------------------------------------------------------------

class HouseSuggestRequest(BaseModel):
    city: str = Field(..., min_length=1, max_length=255)
    street: str = Field(..., min_length=1, max_length=255)
    query: str = Field(..., min_length=1, max_length=255)


class HouseSuggestResponse(BaseModel):
    suggestions: list[SuggestionItem] = Field(default_factory=list)
