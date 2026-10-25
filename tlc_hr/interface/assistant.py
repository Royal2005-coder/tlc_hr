"""Raven custom functions and authenticated HTTP use the same service and native permissions."""
import os

import frappe

from tlc_hr.application.assistant import AssistantService
from tlc_hr.contracts.assistant import AssistantQuery, LeaveDraft
from tlc_hr.domain.assistant import authorize
from tlc_hr.infrastructure.frappe.assistant import FrappeAssistantRepository
from tlc_hr.interface.errors import domain_errors

BOT_NAME = "TLC Demo HR Assistant"
FUNCTIONS = {"tlc_hr_query": "tlc_hr.interface.assistant.query",
             "tlc_hr_draft_leave": "tlc_hr.interface.assistant.draft_leave",
             "tlc_hr_agent": "tlc_hr.interface.agent_gateway.act"}


def _service():
    return AssistantService(FrappeAssistantRepository())


def _mistral_openai_compat():
    """Mistral's OpenAI-compatible API rejects OpenAI-only None fields on assistant messages."""
    try:
        from openai.resources.chat.completions import AsyncCompletions
    except Exception:
        return
    original = AsyncCompletions.create
    if getattr(original, "_tlc_mistral_compat", False):
        return

    async def create(self, *args, **kwargs):
        messages = kwargs.get("messages")
        if messages:
            for message in messages:
                if isinstance(message, dict):
                    for key in ("refusal", "annotations", "audio", "function_call"):
                        if message.get(key) is None:
                            message.pop(key, None)
        return await original(self, *args, **kwargs)

    create._tlc_mistral_compat = True
    AsyncCompletions.create = create


_mistral_openai_compat()


@frappe.whitelist(methods=["POST"])
def query(topic, employee=None):
    with domain_errors():
        return _service().query(AssistantQuery(topic=topic, employee=employee))


@frappe.whitelist(methods=["POST"])
def draft_leave(leave_type, from_date, to_date, reason, employee=None):
    with domain_errors():
        return _service().draft_leave(LeaveDraft(leave_type=leave_type, from_date=from_date, to_date=to_date,
                                                reason=reason, employee=employee))


def _assistant_channel(channel):
    if channel.get("thread_bot") == BOT_NAME:
        return True
    if channel.get("is_direct_message"):
        for user in (channel.get("dm_user_1"), channel.get("dm_user_2")):
            if user and frappe.db.get_value("Raven User", user, "bot") == BOT_NAME:
                return True
    return False


def guard_message(doc, method=None):
    """Called before Raven queues any provider work; forbid files and shared/misattributed chats."""
    channel = frappe.get_doc("Raven Channel", doc.channel_id)
    if not _assistant_channel(channel):
        return
    # The AI worker updates the user's message and writes the AI thread after guard_job has
    # already checked the persisted user message; internal messages of that job are trusted.
    job_message = frappe.flags.get("tlc_ai_job_message")
    if job_message and (doc.name == job_message
                        or (channel.get("is_ai_thread") and channel.get("channel_name") == job_message)):
        return
    channel.check_permission("read")
    if doc.get("is_bot_message"):
        return
    if os.environ.get("OPENAI_AGENTS_DISABLE_TRACING") != "1":
        frappe.throw("AI_DISABLED: Provider tracing must be disabled in backend and worker pods.", frappe.PermissionError)
    with domain_errors():
        authorize(FrappeAssistantRepository().identity(), None)
    if doc.owner != frappe.session.user or doc.get("message_type") != "Text" or doc.get("file"):
        frappe.throw("AI_DEMO_ONLY: Chỉ nhận văn bản demo từ chính người đăng nhập.", frappe.PermissionError)
    if channel.get("is_ai_thread"):
        # Raven records the root message ID in channel_name for a DM AI thread.
        root = frappe.get_doc("Raven Message", channel.channel_name)
        root.check_permission("read")
        parent = frappe.get_doc("Raven Channel", root.channel_id)
        if root.owner != frappe.session.user or not parent.is_direct_message or not _assistant_channel(parent):
            frappe.throw("AI_SCOPE_DENIED: Chỉ sử dụng hội thoại riêng của bạn.", frappe.PermissionError)
    elif not channel.get("is_direct_message"):
        frappe.throw("AI_SCOPE_DENIED: Không được dùng trợ lý trong kênh chung.", frappe.PermissionError)


def guard_job(method, kwargs, transaction_type=None):
    """Frappe restores the enqueueing user. Check persisted message rather than trusting job input."""
    if method not in {"raven.ai.ai.handle_bot_dm", "raven.ai.ai.handle_ai_thread_message"}:
        return
    message = kwargs.get("message")
    if message:
        persisted = frappe.get_doc("Raven Message", message.name)
        guard_message(persisted)
        frappe.flags.tlc_ai_job_message = persisted.name


def validate_bot(doc, method=None):
    if doc.bot_name != BOT_NAME and doc.name != BOT_NAME:
        return
    if doc.bot_name != BOT_NAME:
        frappe.throw("TLC assistant bot identity cannot be changed.", frappe.PermissionError)
    expected = set(FUNCTIONS)
    if set(row.function for row in doc.bot_functions) != expected or len(doc.bot_functions) != len(expected):
        frappe.throw("TLC assistant requires the exact read/draft tool whitelist.", frappe.PermissionError)
    if (doc.model_provider != "Local LLM" or doc.openai_assistant_id or doc.enable_code_interpreter
            or doc.enable_file_search or doc.dynamic_instructions or doc.use_google_document_parser or doc.file_sources):
        frappe.throw("TLC assistant supports only the demo OpenAI-compatible provider without file/code tools.", frappe.PermissionError)


def validate_function(doc, method=None):
    path = FUNCTIONS.get(doc.name) or FUNCTIONS.get(doc.function_name)
    if path and (doc.function_name not in FUNCTIONS or doc.type != "Custom Function" or doc.function_path != path):
        frappe.throw("TLC assistant function path is fixed by the application whitelist.", frappe.PermissionError)
