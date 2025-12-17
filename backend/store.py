from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional
import uuid

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

@dataclass
class Item:
    id: str
    kind: str
    title: str
    content: str
    source: str
    created_at: str
    reviewed: bool = False
    archived: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

class InMemoryStore:
    def __init__(self):
        self._items: Dict[str, Item] = {}

    def list_items(
        self,
        search: str = "",
        kinds: Optional[List[str]] = None,
        include_archived: bool = False,
        include_reviewed: bool = True,
        limit: int = 200,
        offset: int = 0,
    ) -> List[dict]:
        q = (search or "").strip().lower()
        kinds_set = set([k.strip() for k in (kinds or []) if k.strip()])

        def matches(it: Item) -> bool:
            if not include_archived and it.archived:
                return False
            if not include_reviewed and it.reviewed:
                return False
            if kinds_set and it.kind not in kinds_set:
                return False
            if not q:
                return True
            hay = f"{it.title}\n{it.content}\n{it.kind}\n{it.source}".lower()
            parts = [p for p in q.split() if p]
            return all(p in hay for p in parts)

        items = [it for it in self._items.values() if matches(it)]
        items.sort(key=lambda x: x.created_at, reverse=True)
        sliced = items[offset: offset + limit]
        return [it.to_dict() for it in sliced]

    def create_item(self, kind: str, content: str, source: str = "api") -> dict:
        content = (content or "").strip()
        kind = (kind or "NOTE").strip().upper()
        title = self._derive_title(kind, content)

        item = Item(
            id=str(uuid.uuid4()),
            kind=kind,
            title=title,
            content=content,
            source=source,
            created_at=now_iso(),
            reviewed=False,
            archived=False,
        )
        self._items[item.id] = item
        return item.to_dict()

    def patch_item(self, item_id: str, patch: dict) -> Optional[dict]:
        it = self._items.get(item_id)
        if not it:
            return None

        allowed = {"reviewed", "archived", "title", "content", "kind"}
        for k, v in (patch or {}).items():
            if k not in allowed:
                continue
            if k in ("reviewed", "archived"):
                setattr(it, k, bool(v))
            elif k == "kind":
                setattr(it, k, str(v).strip().upper())
            elif k in ("title", "content"):
                setattr(it, k, str(v))

        if not it.title.strip():
            it.title = self._derive_title(it.kind, it.content)

        self._items[item_id] = it
        return it.to_dict()

    def bulk(self, ids: List[str], action: str) -> int:
        action = (action or "").strip().lower()
        count = 0
        for _id in ids or []:
            it = self._items.get(_id)
            if not it:
                continue
            if action == "review":
                it.reviewed = True
                count += 1
            elif action == "archive":
                it.archived = True
                count += 1
            self._items[_id] = it
        return count

    def seed_demo(self) -> None:
        if self._items:
            return
        self.create_item("DEV_TICKET",
                         "diane gitlab voice agent pitch bug workspace switch\nRepro: nur wenn Funktion direkt im Devtool gecallt wird.",
                         source="telegram_voice")
        self.create_item("DEMO_PREP",
                         "diane demo agenda sales titans\nFokus: Onboarding Story, Playbooks, keine Feature-Tour.",
                         source="telegram_text")
        self.create_item("CRM_ACTION",
                         "diane crm new contact tuukka teppola valuelab\nNotiz: interessiert an Playbooks.",
                         source="telegram_text")
        self.create_item("BUSINESS_TODO",
                         "diane followup hörer flamme januar\nkurz update + 2 optionen für next steps.",
                         source="telegram_voice")

    @staticmethod
    def _derive_title(kind: str, content: str) -> str:
        first = (content or "").strip().split("\n")[0][:90]
        if not first:
            return f"{kind}: Untitled"
        if first.lower().startswith("diane "):
            first = first[6:]
        return first or f"{kind}: Untitled"
