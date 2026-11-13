"""Helper audit log."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from core.models import AuditEntry
from core.repo.base import Repository


def _dump(obj: Any) -> str:
    if obj is None:
        return ""
    data = obj.model_dump(mode="json", exclude={"pin_hash"}) if isinstance(obj, BaseModel) else obj
    return json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)


def record(
    repo: Repository,
    now: datetime,
    actor: str,
    action: str,
    entity: str,
    entity_id: str,
    before: Any = None,
    after: Any = None,
    reason: str = "",
) -> None:
    repo.audit.add(
        AuditEntry(
            ts=now,
            actor=actor,
            action=action,
            entity=entity,
            entity_id=entity_id,
            before_json=_dump(before),
            after_json=_dump(after),
            reason=reason,
        )
    )
