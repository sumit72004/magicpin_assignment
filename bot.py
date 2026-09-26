"""
Vera Message Engine — Main Bot Application.
Exposes the 5 HTTP endpoints defined in challenge-testing-brief.md and the canonical compose() contract from challenge-brief.md §7.1.
"""

from __future__ import annotations
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.models import (
    ContextPushRequest, ContextPushResponse,
    HealthzResponse, MetadataResponse,
    TickRequest, TickResponse, ActionItem,
    ReplyRequest, ReplyResponse, ComposedMessage
)
from engine.store import global_store
from engine.composer import global_composer
from engine.conversation_handlers import global_conversation_manager

app = FastAPI(
    title="Vera Message Engine",
    description="Next-generation merchant & customer engagement engine for magicpin",
    version="1.0.0"
)


# =============================================================================
# 1. HEALTHZ & METADATA ENDPOINTS
# =============================================================================

@app.get("/v1/healthz", response_model=HealthzResponse)
async def healthz():
    """Liveness probe reporting uptime and context inventory."""
    return HealthzResponse(
        status="ok",
        uptime_seconds=global_store.uptime_seconds,
        contexts_loaded=global_store.get_counts()
    )


@app.get("/v1/metadata", response_model=MetadataResponse)
async def metadata():
    """Bot identity and architecture metadata."""
    return MetadataResponse(
        team_name="Vera Core AI",
        team_members=["Vera AI Engineering"],
        model="4-context-neural-composer-v1",
        approach="4-context composition framework with zero-hallucination factual grounding, intent state routing, and auto-reply suppression",
        contact_email="vera-challenge@magicpin.in",
        version="1.0.0",
        submitted_at="2026-04-26T10:00:00Z"
    )


# =============================================================================
# 2. CONTEXT PUSH ENDPOINT
# =============================================================================

@app.post("/v1/context")
async def push_context(body: ContextPushRequest):
    """
    Receive incremental or full context update across (category, merchant, customer, trigger).
    Enforces idempotency and atomic version replacement.
    """
    valid_scopes = {"category", "merchant", "customer", "trigger"}
    if body.scope not in valid_scopes:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"accepted": False, "reason": "invalid_scope", "details": f"Scope must be one of {valid_scopes}"}
        )

    accepted, reason, current_ver, stored_at = global_store.push_context(
        scope=body.scope,
        context_id=body.context_id,
        version=body.version,
        payload=body.payload
    )

    if not accepted:
        # Return HTTP 409 Conflict for stale version
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "accepted": False,
                "reason": "stale_version",
                "current_version": current_ver
            }
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "accepted": True,
            "ack_id": f"ack_{body.context_id}_v{body.version}",
            "stored_at": stored_at
        }
    )


# =============================================================================
# 3. TICK ENDPOINT (PROACTIVE COMPOSITION)
# =============================================================================

@app.post("/v1/tick", response_model=TickResponse)
async def tick(body: TickRequest):
    """
    Periodic wake-up for proactive engagement generation.
    Evaluates available triggers against merchant and category contexts.
    """
    actions: List[ActionItem] = []

    for trigger_id in body.available_triggers:
        trigger = global_store.get_trigger(trigger_id)
        if not trigger:
            continue

        suppression_key = trigger.get("suppression_key", "")
        # Prevent re-sending already handled triggers
        if suppression_key and global_store.is_suppressed(suppression_key):
            continue

        merchant_id = trigger.get("merchant_id")
        if not merchant_id and "payload" in trigger:
            merchant_id = trigger["payload"].get("merchant_id")
        if not merchant_id:
            continue

        merchant = global_store.get_merchant(merchant_id)
        if not merchant:
            continue

        cat_slug = merchant.get("category_slug")
        category = global_store.get_category(cat_slug) or {}

        customer_id = trigger.get("customer_id")
        customer = global_store.get_customer(customer_id) if customer_id else None

        # Compose message using the 4-context engine
        composed = compose(
            category=category,
            merchant=merchant,
            trigger=trigger,
            customer=customer
        )

        conv_id = f"conv_{merchant_id}_{trigger_id}"
        actions.append(ActionItem(
            conversation_id=conv_id,
            merchant_id=merchant_id,
            customer_id=customer_id,
            send_as=composed["send_as"],
            trigger_id=trigger_id,
            template_name=composed.get("template_name", "vera_generic_v1"),
            template_params=composed.get("template_params", []),
            body=composed["body"],
            cta=composed["cta"],
            suppression_key=composed["suppression_key"],
            rationale=composed["rationale"]
        ))

        # Mark suppressed to prevent duplicates in subsequent ticks
        global_store.mark_suppressed(composed["suppression_key"])

        # Cap at 20 actions per tick budget (§5)
        if len(actions) >= 20:
            break

    return TickResponse(actions=actions)


# =============================================================================
# 4. REPLY ENDPOINT (MULTI-TURN DIALOGUE)
# =============================================================================

@app.post("/v1/reply", response_model=ReplyResponse)
async def reply(body: ReplyRequest):
    """
    Handle inbound merchant/customer reply across multi-turn sessions.
    Classifies intent, suppresses auto-replies, and transitions to execution mode.
    """
    response_dict = global_conversation_manager.handle_reply(
        conversation_id=body.conversation_id,
        message=body.message,
        from_role=body.from_role,
        merchant_id=body.merchant_id,
        customer_id=body.customer_id,
        turn_number=body.turn_number
    )

    return ReplyResponse(
        action=response_dict.get("action", "send"),
        body=response_dict.get("body"),
        cta=response_dict.get("cta"),
        wait_seconds=response_dict.get("wait_seconds"),
        rationale=response_dict.get("rationale", "")
    )


@app.post("/v1/teardown")
async def teardown():
    """Wipe in-memory state at the end of a test run (§11)."""
    global_store.clear()
    return {"status": "ok", "cleared": True}


# =============================================================================
# 5. CANONICAL STANDALONE COMPOSE FUNCTION (§7.1)
# =============================================================================

def compose(
    category: Dict[str, Any],
    merchant: Dict[str, Any],
    trigger: Dict[str, Any],
    customer: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Canonical composition interface specified in challenge-brief.md §7.1:
        compose(category, merchant, trigger, customer?) -> dict

    Inputs:
        category: dict loaded from CategoryContext
        merchant: dict loaded from MerchantContext
        trigger:  dict loaded from TriggerContext
        customer: dict loaded from CustomerContext (optional)

    Returns:
        body: str (WhatsApp message body)
        cta: str (single primary call-to-action)
        send_as: "vera" or "merchant_on_behalf"
        suppression_key: str (dedup key)
        rationale: str (concise explanation of strategic choice)
        template_name: str (WhatsApp template name)
        template_params: list[str] (template placeholders)
    """
    return global_composer.compose(
        category=category,
        merchant=merchant,
        trigger=trigger,
        customer=customer
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("bot:app", host="0.0.0.0", port=port, reload=False)
