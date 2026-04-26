from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    property_id: str = Field(..., description="Property ID the user is chatting about")
    message: str = Field(..., min_length=1, description="User chat message")
    thread_id: str | None = Field(
        None,
        description="Optional thread identifier for conversation continuity",
    )


class ChatResponse(BaseModel):
    reply: str = Field(..., description="Assistant reply")
    thread_id: str = Field(..., description="Thread identifier used for this conversation")
