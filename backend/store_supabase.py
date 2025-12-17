import os
import uuid
from supabase import create_client

class SupabaseStore:
    def __init__(self):
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]  # dev only
        self.sb = create_client(url, key)

    def list_items(self, search="", kinds=None, include_archived=False, include_reviewed=True, limit=200, offset=0):
        q = self.sb.table("diane_items").select("*").order("created_at", desc=True)

        if not include_archived:
            q = q.eq("archived", False)
        if not include_reviewed:
            q = q.eq("reviewed", False)
        if kinds:
            q = q.in_("kind", kinds)

        # simple keyword search fallback (db index works best later, but this is fine now)
        if search:
            # Supabase doesn't support plainto_tsquery via python client nicely without RPC.
            # Use ILIKE as a minimal, reliable start:
            q = q.or_(f"title.ilike.%{search}%,content.ilike.%{search}%")

        q = q.range(offset, offset + limit - 1)
        res = q.execute()
        return res.data or []

    def create_item(self, kind, content, source="api"):
        content = (content or "").strip()
        kind = (kind or "NOTE").strip().upper()

        title = (content.split("\n")[0][:90] or "Untitled").strip()
        if title.lower().startswith("diane "):
            title = title[6:]

        row = {
            "id": str(uuid.uuid4()),
            "kind": kind,
            "title": title,
            "content": content,
            "source": source,
            "reviewed": False,
            "archived": False,
        }
        res = self.sb.table("diane_items").insert(row).execute()
        return (res.data or [row])[0]

    def patch_item(self, item_id, patch):
        allowed = {k: patch[k] for k in patch.keys() if k in {"reviewed","archived","title","content","kind"}}
        if not allowed:
            return None
        if "kind" in allowed:
            allowed["kind"] = str(allowed["kind"]).strip().upper()

        res = self.sb.table("diane_items").update(allowed).eq("id", item_id).execute()
        data = res.data or []
        return data[0] if data else None

    def bulk(self, ids, action):
        if not ids:
            return 0
        if action == "review":
            res = self.sb.table("diane_items").update({"reviewed": True}).in_("id", ids).execute()
        elif action == "archive":
            res = self.sb.table("diane_items").update({"archived": True}).in_("id", ids).execute()
        else:
            return 0
        return len(res.data or [])
