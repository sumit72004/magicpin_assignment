"""
Standalone multi-turn conversation handler module matching challenge-brief.md §7.4.
"""

from __future__ import annotations
from typing import Any, Dict, Optional
from engine.conversation_handlers import (
    ConversationManager,
    global_conversation_manager,
    respond as engine_respond
)


def respond(conversation_id: str, merchant_message: str, from_role: str = "merchant", merchant_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Given conversation identifier / state + merchant's latest message, produce the next reply.
    Handles auto-reply detection, hostile opt-outs, and immediate intent action transitions.
    """
    return engine_respond(
        conversation_id=conversation_id,
        merchant_message=merchant_message,
        from_role=from_role,
        merchant_id=merchant_id
    )
