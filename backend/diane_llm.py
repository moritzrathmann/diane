# diane_llm.py
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Optional, Dict, Any

KINDS = ["DEV_TICKET", "CRM_ACTION", "DEMO_PREP", "BUSINESS_TODO", "NOTE"]

# Tag shortcuts you can speak/type in Telegram
TAG_TO_KIND = {
    "dev": "DEV_TICKET",
    "bug": "DEV_TICKET",
    "fix": "DEV_TICKET",

    "crm": "CRM_ACTION",
    "lead": "CRM_ACTION",
    "contact": "CRM_ACTION",

    "demo": "DEMO_PREP",
    "prep": "DEMO_PREP",

    "biz": "BUSINESS_TODO",
    "business": "BUSINESS_TODO",
    "ops": "BUSINESS_TODO",
    "finance": "BUSINESS_TODO",

    "note": "NOTE",
    "idea": "NOTE",
}

DEFAULT_OPENAI_MODEL = os.getenv("OPENAI_MODEL", "").strip()  # set this in env if you want
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()

@dataclass
class DianeDecision:
    kind: str
    title: str
    content: str
    confidence: float = 0.5
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "title": self.title,
            "content": self.content,
            "confidence": self.confidence,
            "reason": self.reason,
        }


def _derive_title(text: str, max_len: int = 90) -> str:
    first = (text or "").strip().splitlines()[0] if (text or "").strip() else "Untitled"
    first = re.sub(r"^\s*diane\s+", "", first, flags=re.I)
    first = first.strip()
    return (first[:max_len] if first else "Untitled")


def _extract_tags(text: str) -> list[str]:
    # matches: #dev, #crm, #demo, etc.
    return [t.lower() for t in re.findall(r"#([a-zA-Z0-9_]+)", text or "")]


def _tag_rule_classify(text: str) -> Optional[DianeDecision]:
    tags = _extract_tags(text)
    for t in tags:
        if t in TAG_TO_KIND:
            kind = TAG_TO_KIND[t]
            cleaned = _remove_tags(text).strip()
            return DianeDecision(
                kind=kind,
                title=_derive_title(cleaned),
                content=cleaned,
                confidence=0.95,
                reason=f"tag: #{t}",
            )
    return None


def _remove_tags(text: str) -> str:
    # remove hashtags but keep spacing readable
    out = re.sub(r"\s*#[a-zA-Z0-9_]+\b", "", text or "")
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out


def _heuristic_classify(text: str) -> DianeDecision:
    t = (text or "").lower()

    # quick signals
    if any(x in t for x in ["bug", "error", "stacktrace", "doesn't work", "does not work", "broken", "fix", "crash"]):
        kind = "DEV_TICKET"
        conf = 0.7
        reason = "heuristic: bug/fix terms"
    elif any(x in t for x in ["follow up", "follow-up", "reach out", "email", "dm", "linkedin", "prospect", "pipeline"]):
        kind = "BUSINESS_TODO"
        conf = 0.65
        reason = "heuristic: outreach terms"
    elif any(x in t for x in ["demo", "agenda", "deck", "pitch", "prep"]):
        kind = "DEMO_PREP"
        conf = 0.65
        reason = "heuristic: demo/prep terms"
    elif any(x in t for x in ["crm", "lead", "kontakt", "contact", "account", "opportunity"]):
        kind = "CRM_ACTION"
        conf = 0.65
        reason = "heuristic: crm/contact terms"
    else:
        kind = "NOTE"
        conf = 0.55
        reason = "heuristic: default"

    cleaned = _remove_tags(text).strip()
    return DianeDecision(kind=kind, title=_derive_title(cleaned), content=cleaned, confidence=conf, reason=reason)


def _openai_available() -> bool:
    if not OPENAI_API_KEY:
        return False
    try:
        import openai  # noqa: F401
        return True
    except Exception:
        return False


def _llm_classify_openai(text: str) -> DianeDecision:
    """
    Uses the installed `openai` python package (v1 style if available).
    Requires env:
      - OPENAI_API_KEY
      - OPENAI_MODEL (optional)
    """
    cleaned = _remove_tags(text).strip()
    title_guess = _derive_title(cleaned)

    prompt = f"""
You are DIANE. Your job: classify a note into exactly one of these kinds:
{", ".join(KINDS)}

Rules:
- Choose exactly one kind.
- If uncertain, choose NOTE.
- Do NOT invent details.
- Keep content as-is (you may remove hashtags).
- Create a short title (<= 90 chars) based on the first meaningful line.

Return STRICT JSON with keys: kind, title, content, confidence, reason.

NOTE:
\"\"\"{cleaned}\"\"\"
""".strip()

    # Try OpenAI SDK v1 first
    try:
        from openai import OpenAI  # type: ignore
        client = OpenAI(api_key=OPENAI_API_KEY)
        model = DEFAULT_OPENAI_MODEL or "gpt-4.1-mini"  # you can override via env

        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You output only valid JSON. No markdown."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
        )
        raw = resp.choices[0].message.content or ""
    except Exception:
        # Fallback to older style if present
        import openai  # type: ignore
        openai.api_key = OPENAI_API_KEY
        model = DEFAULT_OPENAI_MODEL or "gpt-4.1-mini"
        resp = openai.ChatCompletion.create(
            model=model,
            messages=[
                {"role": "system", "content": "You output only valid JSON. No markdown."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
        )
        raw = resp["choices"][0]["message"]["content"] or ""

    # Parse JSON safely
    try:
        data = json.loads(raw)
    except Exception:
        # If model replied with extra text, try to extract JSON object
        m = re.search(r"\{.*\}", raw, flags=re.S)
        data = json.loads(m.group(0)) if m else {}

    kind = str(data.get("kind") or "").strip().upper()
    if kind not in KINDS:
        kind = "NOTE"

    title = str(data.get("title") or "").strip()[:90] or title_guess
    content = str(data.get("content") or "").strip() or cleaned

    confidence = float(data.get("confidence") or 0.6)
    confidence = max(0.0, min(1.0, confidence))
    reason = str(data.get("reason") or "").strip()[:200]

    return DianeDecision(kind=kind, title=title, content=content, confidence=confidence, reason=reason)


def diane_decide(text: str) -> DianeDecision:
    """
    Main entry point.
    - tag-based decision wins (fast + deterministic)
    - else LLM (if configured)
    - else heuristic fallback
    """
    text = (text or "").strip()
    if not text:
        return DianeDecision(kind="NOTE", title="Untitled", content="", confidence=0.0, reason="empty")

    tagged = _tag_rule_classify(text)
    if tagged:
        return tagged

    if _openai_available():
        try:
            return _llm_classify_openai(text)
        except Exception as e:
            # Never break ingestion
            dec = _heuristic_classify(text)
            dec.reason = f"{dec.reason} | llm_error: {type(e).__name__}"
            return dec

    return _heuristic_classify(text)
