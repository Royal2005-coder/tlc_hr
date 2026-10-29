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


# Words a person uses for a kind of rest, against the words a Leave Type is allowed to contain.
LEAVE_TYPE_HINTS = {"ốm": ("ốm", "bệnh", "sick", "khám", "điều trị"), "năm": ("năm", "annual", "pappam", "hè")}


def _leave_type(given, *hints, employee=None):
    """Read the leave type off the company's own list instead of interrogating the person who said "nghỉ vì bệnh".

    Only types the person has a submitted allocation for are offered: a type nobody allocated would be refused by
    HRMS as outside the allocation period, and the person would hear "lỗi" where an HR officer would say "để tôi
    trừ vào phép năm".
    """
    names = frappe.get_all("Leave Type", pluck="name", order_by="name asc")
    if not names:
        return given
    employee = employee or frappe.db.get_value("Employee", {"user_id": frappe.session.user}, "name")
    allocated = set(frappe.get_all("Leave Allocation", filters={"employee": employee, "docstatus": 1},
                                   pluck="leave_type")) if employee else set()
    names = [name for name in names if name in allocated] or names
    wanted = (given or "").strip().casefold()
    for name in names:
        folded = name.casefold()
        if wanted and (folded == wanted or wanted in folded or folded in wanted):
            return name
    text = " ".join([wanted] + [str(hint or "").casefold() for hint in hints])
    for name in names:
        folded = name.casefold()
        for word, clues in LEAVE_TYPE_HINTS.items():
            if word in folded and any(clue in text for clue in clues):
                return name
    # the person named a type they cannot book here (no allocation); take the one they can and let the reply say so
    return given if given in names else names[0]


@frappe.whitelist(methods=["POST"])
def draft_leave(leave_type, from_date, to_date, reason, employee=None):
    with domain_errors():
        return _service().draft_leave(LeaveDraft(leave_type=_leave_type(leave_type, reason, employee=employee),
                                                from_date=from_date, to_date=to_date, reason=reason,
                                                employee=employee))



def answer_in_dm(doc, method=None):
    """Answer a person's message in the assistant's channel with the gateway's own words.

    Raven's AI bot rewrites a tool result before showing it, which is fine for prose and wrong for an HR system:
    the number, the state and the link a person reads have to be the ones the server actually produced.
    """
    if doc.is_bot_message or doc.message_type != "Text" or not (doc.text or "").strip():
        return
    if frappe.db.get_value("Raven Bot", BOT_NAME, "is_ai_bot"):
        # Raven's own AI bot is answering this channel; a second reply from here would be a duplicate
        return
    channel = frappe.db.get_value("Raven Channel", doc.channel_id,
                                  ["name", "is_direct_message", "dm_user_1", "dm_user_2", "thread_bot"], as_dict=1)
    if not channel or not _assistant_channel(channel):
        return
    frappe.enqueue("tlc_hr.interface.assistant.answer", queue="short", channel=doc.channel_id,
                   message=doc.text[:2000], user=doc.owner)


def answer(channel, message, user):
    """Run one chat turn as the person who asked, then post the answer as the bot."""
    from tlc_hr.interface import agent_gateway

    frappe.set_user(user)
    result = agent_gateway.act(message)
    text = (result.get("reply") or "").strip()
    if not text:
        return
    frappe.get_doc({"doctype": "Raven Message", "channel_id": channel, "message_type": "Text",
                    "is_bot_message": 1, "bot": BOT_NAME, "text": text}).insert(ignore_permissions=True)
    frappe.db.commit()


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
