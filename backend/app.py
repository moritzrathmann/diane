from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

import tempfile, requests, os, json, base64
from faster_whisper import WhisperModel
from flask import Flask, jsonify, request
from store_supabase import SupabaseStore
from diane_llm import diane_decide

app = Flask(__name__)
store = SupabaseStore()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
_whisper = None

# In-memory pending confirmations (use Redis in production)
pending_confirmations = {}

def get_whisper():
    global _whisper
    if _whisper is None:
        _whisper = WhisperModel("tiny", device="cpu", compute_type="int8")
    return _whisper

def tg_api(method, params=None):
    """Send request to Telegram Bot API"""
    r = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}",
        json=params or {},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()

def send_message(chat_id: int, text: str, reply_markup=None):
    """Send a text message to Telegram chat"""
    params = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    if reply_markup:
        params["reply_markup"] = reply_markup
    return tg_api("sendMessage", params)

def download_telegram_file(file_id: str) -> bytes:
    """Download any file from Telegram"""
    meta = tg_api("getFile", {"file_id": file_id})
    path = meta["result"]["file_path"]
    r = requests.get(
        f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{path}",
        timeout=60,
    )
    r.raise_for_status()
    return r.content

def transcribe_bytes(audio: bytes) -> str:
    """Transcribe audio bytes to text using Whisper"""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as f:
        f.write(audio)
        p = f.name
    segments, _ = get_whisper().transcribe(p)
    return " ".join(s.text.strip() for s in segments).strip()

def create_confirmation_keyboard(confirmation_id: str):
    """Create inline keyboard for confirmation"""
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Confirm", "callback_data": f"confirm:{confirmation_id}"},
                {"text": "❌ Cancel", "callback_data": f"cancel:{confirmation_id}"}
            ],
            [
                {"text": "✏️ Edit Type", "callback_data": f"edit:{confirmation_id}"}
            ]
        ]
    }

def create_type_selection_keyboard(confirmation_id: str):
    """Create keyboard for selecting item type"""
    types = [
        ("🐛 Dev/Bug", "DEV_TICKET"),
        ("👤 CRM", "CRM_ACTION"),
        ("🎯 Demo Prep", "DEMO_PREP"),
        ("💼 Business", "BUSINESS_TODO"),
        ("📝 Note", "NOTE")
    ]
    
    keyboard = []
    for label, kind in types:
        keyboard.append([{
            "text": label,
            "callback_data": f"type:{confirmation_id}:{kind}"
        }])
    
    keyboard.append([{
        "text": "« Back",
        "callback_data": f"back:{confirmation_id}"
    }])
    
    return {"inline_keyboard": keyboard}

def format_confirmation_message(decision, source_type: str, has_file: bool = False) -> str:
    """Format the confirmation message to show to user"""
    emoji_map = {
        "DEV_TICKET": "🐛",
        "CRM_ACTION": "👤",
        "DEMO_PREP": "🎯",
        "BUSINESS_TODO": "💼",
        "NOTE": "📝"
    }
    
    emoji = emoji_map.get(decision.kind, "📝")
    
    msg = f"*New {source_type} received!*\n\n"
    msg += f"{emoji} *Type:* {decision.kind}\n"
    msg += f"📌 *Title:* {decision.title}\n\n"
    
    if has_file:
        msg += f"📎 *File attached*\n\n"
    
    # Truncate content for preview
    preview = decision.content[:200]
    if len(decision.content) > 200:
        preview += "..."
    
    msg += f"*Content:*\n{preview}\n\n"
    msg += f"_Confidence: {decision.confidence:.0%}_"
    
    if decision.reason:
        msg += f"\n_Reason: {decision.reason}_"
    
    msg += "\n\n*Confirm to save to DIANE dashboard?*"
    
    return msg


@app.route("/", methods=["GET"])
def root():
    return jsonify({
        "ok": True,
        "hint": "Use /health or /api/items. Frontend is served separately."
    })

@app.after_request
def add_cors_headers(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PATCH,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})

@app.route("/api/items", methods=["OPTIONS"])
def items_options():
    return ("", 204)

@app.route("/api/items", methods=["GET"])
def list_items():
    search = request.args.get("search", "")
    kinds_raw = request.args.get("kinds", "")
    kinds = [k for k in kinds_raw.split(",") if k.strip()] if kinds_raw else []
    include_archived = request.args.get("include_archived", "false").lower() == "true"
    include_reviewed = request.args.get("include_reviewed", "true").lower() == "true"
    limit = int(request.args.get("limit", "200"))
    offset = int(request.args.get("offset", "0"))

    items = store.list_items(
        search=search,
        kinds=kinds,
        include_archived=include_archived,
        include_reviewed=include_reviewed,
        limit=limit,
        offset=offset,
    )
    return jsonify({"items": items})

@app.route("/api/items", methods=["POST"])
def create_item():
    data = request.get_json(force=True, silent=True) or {}
    kind = (data.get("kind") or "NOTE").strip().upper()
    content = (data.get("content") or "").strip()
    source = (data.get("source") or "api").strip()

    if not content:
        return jsonify({"error": "content is required"}), 400

    item = store.create_item(kind=kind, content=content, source=source)
    return jsonify({"item": item}), 201

@app.route("/api/items/<item_id>", methods=["OPTIONS"])
def patch_options(item_id):
    return ("", 204)

@app.route("/api/items/<item_id>", methods=["PATCH"])
def patch_item(item_id):
    data = request.get_json(force=True, silent=True) or {}
    item = store.patch_item(item_id, data)
    if not item:
        return jsonify({"error": "not found"}), 404
    return jsonify({"item": item})

@app.route("/api/items/bulk", methods=["POST"])
def bulk():
    data = request.get_json(force=True, silent=True) or {}
    ids = data.get("ids") or []
    action = data.get("action") or ""

    if not isinstance(ids, list) or not action:
        return jsonify({"error": "ids(list) and action required"}), 400

    count = store.bulk(ids=ids, action=action)
    return jsonify({"updated": count})

@app.route("/api/telegram", methods=["POST"])
def telegram_webhook():
    """Handle incoming Telegram messages and callback queries"""
    data = request.get_json(force=True, silent=True) or {}
    
    # Handle callback queries (button presses)
    if data.get("callback_query"):
        return handle_callback_query(data["callback_query"])
    
    # Handle messages
    msg = data.get("message") or data.get("edited_message") or {}
    if not msg:
        return jsonify({"ok": True})
    
    chat_id = msg.get("chat", {}).get("id")
    if not chat_id:
        return jsonify({"ok": True})
    
    try:
        # TEXT MESSAGE
        if msg.get("text"):
            text = msg["text"]
            decision = diane_decide(text)
            
            # Store pending confirmation
            confirmation_id = f"{chat_id}_{msg['message_id']}"
            pending_confirmations[confirmation_id] = {
                "decision": decision.to_dict(),
                "source": "telegram_text",
                "chat_id": chat_id
            }
            
            # Send confirmation request
            confirmation_msg = format_confirmation_message(decision, "text message")
            send_message(
                chat_id,
                confirmation_msg,
                reply_markup=create_confirmation_keyboard(confirmation_id)
            )
        
        # VOICE MESSAGE
        elif msg.get("voice") and msg["voice"].get("file_id"):
            # Download and transcribe
            audio = download_telegram_file(msg["voice"]["file_id"])
            text = transcribe_bytes(audio)
            
            if not text:
                send_message(chat_id, "⚠️ Could not transcribe voice message. Please try again.")
                return jsonify({"ok": True})
            
            decision = diane_decide(text)
            
            # Store pending confirmation
            confirmation_id = f"{chat_id}_{msg['message_id']}"
            pending_confirmations[confirmation_id] = {
                "decision": decision.to_dict(),
                "source": "telegram_voice",
                "chat_id": chat_id
            }
            
            # Send confirmation request
            confirmation_msg = format_confirmation_message(decision, "voice note")
            send_message(
                chat_id,
                confirmation_msg,
                reply_markup=create_confirmation_keyboard(confirmation_id)
            )
        
        # DOCUMENT (PDF, DOCX, etc.)
        elif msg.get("document"):
            doc = msg["document"]
            file_id = doc.get("file_id")
            file_name = doc.get("file_name", "document")
            mime_type = doc.get("mime_type", "")
            
            if not file_id:
                return jsonify({"ok": True})
            
            # Download file
            file_bytes = download_telegram_file(file_id)
            
            # Create content with file info
            caption = msg.get("caption", "")
            content = f"📎 File: {file_name}\n"
            if caption:
                content += f"\n{caption}"
            
            # Store file as base64 (or upload to storage in production)
            file_b64 = base64.b64encode(file_bytes).decode()
            content += f"\n\n[File data: {len(file_bytes)} bytes, {mime_type}]"
            
            decision = diane_decide(caption or f"Document: {file_name}")
            decision.content = content
            
            # Store pending confirmation
            confirmation_id = f"{chat_id}_{msg['message_id']}"
            pending_confirmations[confirmation_id] = {
                "decision": decision.to_dict(),
                "source": "telegram_document",
                "chat_id": chat_id,
                "file_name": file_name,
                "file_data": file_b64[:1000]  # Store preview
            }
            
            # Send confirmation
            confirmation_msg = format_confirmation_message(decision, "document", has_file=True)
            send_message(
                chat_id,
                confirmation_msg,
                reply_markup=create_confirmation_keyboard(confirmation_id)
            )
        
        # PHOTO
        elif msg.get("photo"):
            # Get largest photo
            photos = msg["photo"]
            largest = max(photos, key=lambda p: p.get("file_size", 0))
            file_id = largest.get("file_id")
            
            if not file_id:
                return jsonify({"ok": True})
            
            # Download image
            img_bytes = download_telegram_file(file_id)
            
            # Create content with image info
            caption = msg.get("caption", "")
            content = f"🖼️ Image attached\n"
            if caption:
                content += f"\n{caption}"
            
            # Store image as base64
            img_b64 = base64.b64encode(img_bytes).decode()
            content += f"\n\n[Image data: {len(img_bytes)} bytes]"
            
            decision = diane_decide(caption or "Image")
            decision.content = content
            
            # Store pending confirmation
            confirmation_id = f"{chat_id}_{msg['message_id']}"
            pending_confirmations[confirmation_id] = {
                "decision": decision.to_dict(),
                "source": "telegram_image",
                "chat_id": chat_id,
                "image_data": img_b64[:1000]  # Store preview
            }
            
            # Send confirmation
            confirmation_msg = format_confirmation_message(decision, "image", has_file=True)
            send_message(
                chat_id,
                confirmation_msg,
                reply_markup=create_confirmation_keyboard(confirmation_id)
            )
        
        else:
            send_message(chat_id, "ℹ️ Supported: text, voice notes, documents, and images.")
    
    except Exception as e:
        print(f"Error processing message: {e}")
        if chat_id:
            send_message(chat_id, f"❌ Error: {str(e)}")
    
    return jsonify({"ok": True})

def handle_callback_query(callback):
    """Handle button presses from inline keyboards"""
    callback_id = callback.get("id")
    data = callback.get("data", "")
    message = callback.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    message_id = message.get("message_id")
    
    if not chat_id or not data:
        return jsonify({"ok": True})
    
    try:
        parts = data.split(":", 2)
        action = parts[0]
        confirmation_id = parts[1] if len(parts) > 1 else ""
        
        # Answer callback to remove loading state
        tg_api("answerCallbackQuery", {"callback_query_id": callback_id})
        
        if action == "confirm":
            # Create the item
            pending = pending_confirmations.get(confirmation_id)
            if not pending:
                send_message(chat_id, "⚠️ Confirmation expired. Please send again.")
                return jsonify({"ok": True})
            
            decision_dict = pending["decision"]
            item = store.create_item(
                kind=decision_dict["kind"],
                content=decision_dict["content"],
                source=pending["source"]
            )
            
            # Clean up
            del pending_confirmations[confirmation_id]
            
            # Update message
            tg_api("editMessageText", {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": f"✅ *Saved to DIANE!*\n\n{decision_dict['kind']}: {decision_dict['title']}",
                "parse_mode": "Markdown"
            })
        
        elif action == "cancel":
            # Clean up
            if confirmation_id in pending_confirmations:
                del pending_confirmations[confirmation_id]
            
            # Update message
            tg_api("editMessageText", {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": "❌ Cancelled. Nothing was saved.",
                "parse_mode": "Markdown"
            })
        
        elif action == "edit":
            # Show type selection keyboard
            pending = pending_confirmations.get(confirmation_id)
            if not pending:
                send_message(chat_id, "⚠️ Confirmation expired. Please send again.")
                return jsonify({"ok": True})
            
            tg_api("editMessageReplyMarkup", {
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": create_type_selection_keyboard(confirmation_id)
            })
        
        elif action == "type":
            # User selected a new type
            new_kind = parts[2] if len(parts) > 2 else "NOTE"
            pending = pending_confirmations.get(confirmation_id)
            
            if not pending:
                send_message(chat_id, "⚠️ Confirmation expired. Please send again.")
                return jsonify({"ok": True})
            
            # Update the pending decision
            pending["decision"]["kind"] = new_kind
            
            # Recreate decision for formatting
            from diane_llm import DianeDecision
            decision = DianeDecision(**pending["decision"])
            
            # Update message with new type
            has_file = "file_name" in pending or "image_data" in pending
            source_type = pending["source"].replace("telegram_", "")
            confirmation_msg = format_confirmation_message(decision, source_type, has_file)
            
            tg_api("editMessageText", {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": confirmation_msg,
                "parse_mode": "Markdown",
                "reply_markup": create_confirmation_keyboard(confirmation_id)
            })
        
        elif action == "back":
            # Go back to confirmation
            pending = pending_confirmations.get(confirmation_id)
            if pending:
                tg_api("editMessageReplyMarkup", {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "reply_markup": create_confirmation_keyboard(confirmation_id)
                })
    
    except Exception as e:
        print(f"Error handling callback: {e}")
        send_message(chat_id, f"❌ Error: {str(e)}")
    
    return jsonify({"ok": True})

# Füge diese Route am Ende von app.py hinzu:

@app.route("/set-webhook", methods=["GET"])
def set_webhook():
    """Set Telegram webhook - call this once after deploy"""
    webhook_url = request.args.get("url")  # deine Render URL
    
    if not webhook_url:
        return jsonify({"error": "Pass ?url=https://your-app.onrender.com/api/telegram"}), 400
    
    result = tg_api("setWebhook", {"url": webhook_url})
    return jsonify(result)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)