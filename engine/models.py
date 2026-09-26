"""
Data models and schemas for the Vera Message Engine.
Conforms strictly to the 4-context specification in challenge-brief.md and challenge-testing-brief.md.
"""

from __future__ import annotations
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field


# =============================================================================
# CONTEXT API SCHEMAS (POST /v1/context)
# =============================================================================

class ContextPushRequest(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: Dict[str, Any]
    delivered_at: Optional[str] = None


class ContextPushResponse(BaseModel):
    accepted: bool
    ack_id: Optional[str] = None
    stored_at: Optional[str] = None
    reason: Optional[str] = None
    current_version: Optional[int] = None
    details: Optional[str] = None


# =============================================================================
# HEALTH & METADATA SCHEMAS
# =============================================================================

class HealthzResponse(BaseModel):
    status: str = "ok"
    uptime_seconds: int
    contexts_loaded: Dict[str, int]


class MetadataResponse(BaseModel):
    team_name: str
    team_members: List[str]
    model: str
    approach: str
    contact_email: str
    version: str
    submitted_at: str


# =============================================================================
# TICK API SCHEMAS (POST /v1/tick)
# =============================================================================

class TickRequest(BaseModel):
    now: str
    available_triggers: List[str] = Field(default_factory=list)


class ActionItem(BaseModel):
    conversation_id: str
    merchant_id: str
    customer_id: Optional[str] = None
    send_as: Literal["vera", "merchant_on_behalf"]
    trigger_id: str
    template_name: Optional[str] = None
    template_params: Optional[List[str]] = None
    body: str
    cta: str
    suppression_key: str
    rationale: str


class TickResponse(BaseModel):
    actions: List[ActionItem] = Field(default_factory=list)


# =============================================================================
# REPLY API SCHEMAS (POST /v1/reply)
# =============================================================================

class ReplyRequest(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str
    message: str
    received_at: Optional[str] = None
    turn_number: int = 1


class ReplyResponse(BaseModel):
    action: Literal["send", "wait", "end"]
    body: Optional[str] = None
    cta: Optional[str] = None
    wait_seconds: Optional[int] = None
    rationale: str


# =============================================================================
# COMPOSED MESSAGE (Internal & Standalone compose())
# =============================================================================

class ComposedMessage(BaseModel):
    body: str
    cta: str
    send_as: Literal["vera", "merchant_on_behalf"]
    suppression_key: str
    rationale: str
    template_name: Optional[str] = None
    template_params: Optional[List[str]] = None
