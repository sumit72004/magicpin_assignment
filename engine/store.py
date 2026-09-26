"""
Thread-safe context, suppression, and conversation store for the Vera Message Engine.
Enforces versioning, idempotency, and rapid lookup across the 4 context layers.
"""

from __future__ import annotations
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class ContextStore:
    def __init__(self):
        self._lock = threading.RLock()
        # Storage: (scope, context_id) -> {"version": int, "payload": dict, "stored_at": str}
        self._contexts: Dict[Tuple[str, str], Dict[str, Any]] = {}
        # Suppression registry: suppression_key -> timestamp
        self._suppressions: Dict[str, str] = {}
        # Conversation history: conversation_id -> list of turn dicts
        self._conversations: Dict[str, List[Dict[str, Any]]] = {}
        # Conversation metadata: conversation_id -> {status: "active"|"ended"|"waiting", wait_until: str, ...}
        self._conversation_meta: Dict[str, Dict[str, Any]] = {}
        # Start time
        self._start_time = datetime.now(timezone.utc)

    @property
    def uptime_seconds(self) -> int:
        return int((datetime.now(timezone.utc) - self._start_time).total_seconds())

    def get_counts(self) -> Dict[str, int]:
        with self._lock:
            counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
            for (scope, _), _ in self._contexts.items():
                if scope in counts:
                    counts[scope] += 1
            return counts

    def push_context(self, scope: str, context_id: str, version: int, payload: Dict[str, Any]) -> Tuple[bool, Optional[str], Optional[int], str]:
        """
        Idempotently store or replace context with version check.
        Returns: (accepted, reason_if_not, current_version, stored_at_or_err)
        """
        now_iso = datetime.now(timezone.utc).isoformat() + "Z"
        key = (scope, context_id)

        with self._lock:
            existing = self._contexts.get(key)
            if existing is not None:
                cur_ver = existing["version"]
                if cur_ver > version:
                    # Strictly stale version (already have higher version)
                    return False, "stale_version", cur_ver, now_iso
                elif cur_ver == version:
                    # Idempotent re-post of same version is a no-op
                    return True, None, cur_ver, existing.get("stored_at", now_iso)

            self._contexts[key] = {
                "version": version,
                "payload": payload,
                "stored_at": now_iso
            }
            return True, None, version, now_iso

    def get_context(self, scope: str, context_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            entry = self._contexts.get((scope, context_id))
            return entry["payload"] if entry else None

    def get_category(self, slug: str) -> Optional[Dict[str, Any]]:
        return self.get_context("category", slug)

    def get_merchant(self, merchant_id: str) -> Optional[Dict[str, Any]]:
        return self.get_context("merchant", merchant_id)

    def get_customer(self, customer_id: str) -> Optional[Dict[str, Any]]:
        return self.get_context("customer", customer_id)

    def get_trigger(self, trigger_id: str) -> Optional[Dict[str, Any]]:
        return self.get_context("trigger", trigger_id)

    def is_suppressed(self, suppression_key: str) -> bool:
        if not suppression_key:
            return False
        with self._lock:
            return suppression_key in self._suppressions

    def mark_suppressed(self, suppression_key: str):
        if suppression_key:
            with self._lock:
                self._suppressions[suppression_key] = datetime.now(timezone.utc).isoformat() + "Z"

    def record_turn(self, conversation_id: str, from_role: str, message: str, turn_number: int = 1) -> List[Dict[str, Any]]:
        with self._lock:
            history = self._conversations.setdefault(conversation_id, [])
            history.append({
                "from": from_role,
                "message": message,
                "turn_number": turn_number,
                "ts": datetime.now(timezone.utc).isoformat() + "Z"
            })
            return list(history)

    def get_conversation_history(self, conversation_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._conversations.get(conversation_id, []))

    def set_conversation_status(self, conversation_id: str, status: str, meta: Optional[Dict[str, Any]] = None):
        with self._lock:
            d = self._conversation_meta.setdefault(conversation_id, {})
            d["status"] = status
            if meta:
                d.update(meta)

    def get_conversation_status(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._conversation_meta.get(conversation_id)

    def clear(self):
        """Teardown state."""
        with self._lock:
            self._contexts.clear()
            self._suppressions.clear()
            self._conversations.clear()
            self._conversation_meta.clear()

    def preload_from_dataset(self, dataset_dir: Path):
        """Preload available base datasets from disk if present."""
        if not dataset_dir.exists():
            return

        cat_dir = dataset_dir / "categories"
        if cat_dir.exists():
            for f in cat_dir.glob("*.json"):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    slug = data.get("slug", f.stem)
                    self.push_context("category", slug, 1, data)
                except Exception:
                    pass

        # Check expanded merchants/customers/triggers first, else seed files
        expanded_dir = dataset_dir / "expanded"
        if expanded_dir.exists():
            for m_file in (expanded_dir / "merchants").glob("*.json"):
                try:
                    data = json.loads(m_file.read_text(encoding="utf-8"))
                    self.push_context("merchant", data["merchant_id"], 1, data)
                except Exception:
                    pass
            for c_file in (expanded_dir / "customers").glob("*.json"):
                try:
                    data = json.loads(c_file.read_text(encoding="utf-8"))
                    self.push_context("customer", data["customer_id"], 1, data)
                except Exception:
                    pass
            for t_file in (expanded_dir / "triggers").glob("*.json"):
                try:
                    data = json.loads(t_file.read_text(encoding="utf-8"))
                    self.push_context("trigger", data["id"], 1, data)
                except Exception:
                    pass

        # Also load from root seeds if not already loaded
        for name, scope, key in [
            ("merchants_seed.json", "merchant", "merchant_id"),
            ("customers_seed.json", "customer", "customer_id"),
            ("triggers_seed.json", "trigger", "id")
        ]:
            path = dataset_dir / name
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    items = data.get(scope + "s", data.get(scope, []))
                    for item in items:
                        if key in item:
                            self.push_context(scope, item[key], 1, item)
                except Exception:
                    pass


# Global singleton store instance
global_store = ContextStore()
