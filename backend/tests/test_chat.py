import chat
from types import SimpleNamespace


def test_heuristic_turn_router_disables_tools_for_greeting():
    router = chat._heuristic_turn_router("hello")

    assert router == {
        "intent": "small_talk",
        "allow_tools": False,
        "response_mode": "direct_answer",
        "reason": "This is a short greeting or acknowledgment.",
    }


def test_tools_for_router_limits_profile_updates_to_memory_saves():
    tools = chat._tools_for_router({
        "intent": "profile_update",
        "allow_tools": True,
    })

    assert len(tools) == 1
    assert [declaration.name for declaration in tools[0].function_declarations] == [
        "save_user_context"
    ]


def test_running_status_payload_includes_stream_padding():
    payload = chat._status_payload(
        step_id="understanding_request",
        phase="understanding_request",
        label="Understanding request",
        state="running",
    )

    assert payload["state"] == "running"
    assert payload["_stream_padding"] == chat.STREAM_FLUSH_PADDING


def test_done_status_payload_omits_stream_padding():
    payload = chat._status_payload(
        step_id="understanding_request",
        phase="understanding_request",
        label="Understanding request",
        state="done",
    )

    assert payload["state"] == "done"
    assert "_stream_padding" not in payload


def test_upsert_activity_trace_replaces_existing_step_without_padding():
    trace: list[dict] = []

    chat._upsert_activity_trace(
        trace,
        chat._status_payload(
            step_id="read_job_posting",
            phase="read_job_posting",
            label="Reading job posting",
            state="running",
        ),
    )
    chat._upsert_activity_trace(
        trace,
        chat._status_payload(
            step_id="read_job_posting",
            phase="read_job_posting",
            label="Reading job posting",
            state="done",
            detail="Captured the job description.",
        ),
    )

    assert trace == [
        {
            "id": "read_job_posting",
            "phase": "read_job_posting",
            "label": "Reading job posting",
            "state": "done",
            "detail": "Captured the job description.",
        }
    ]


def test_document_progress_status_payload_formats_resume_subphases():
    payload = chat._document_progress_status_payload(
        {"doc_type": "resume"},
        {
            "phase": "repair",
            "state": "done",
            "detail": "Reduced bullet count to fit one page.",
            "meta": {
                "attempt_count": 2,
                "repair_actions": ["reduce_bullets"],
            },
        },
    )

    assert payload == {
        "id": "generate_document:resume:repair",
        "phase": "generate_resume_repair",
        "label": "Adjusting resume",
        "state": "done",
        "tool": "generate_document",
        "detail": "Reduced bullet count to fit one page.",
        "meta": {
            "doc_type": "resume",
            "attempt_count": 2,
            "repair_actions": ["reduce_bullets"],
        },
    }


def test_deterministic_tool_only_fallback_for_generated_documents():
    text = chat._deterministic_tool_only_fallback([
        {
            "name": "generate_document",
            "state": "done",
            "result": {
                "document_id": "resume-doc",
                "doc_type": "resume",
                "filename": "Aham-Sel-Resume.docx",
            },
        },
        {
            "name": "generate_document",
            "state": "done",
            "result": {
                "document_id": "cover-doc",
                "doc_type": "cover_letter",
                "filename": "Aham-Sel-Cover-Letter.docx",
            },
        },
    ])

    assert text == (
        "Your resume and cover letter are ready. The download cards are below. "
        "If you want any revisions, tell me what to change."
    )


def test_deterministic_tool_only_fallback_for_resume_variants_and_cover_letter():
    text = chat._deterministic_tool_only_fallback([
        {
            "name": "generate_document",
            "state": "done",
            "result": {
                "documents": [
                    {
                        "document_id": "resume-creative",
                        "doc_type": "resume",
                        "filename": "Jordan-Vale-Resume-Creative.docx",
                        "variant_label": "Creative-safe",
                    },
                    {
                        "document_id": "resume-ats",
                        "doc_type": "resume",
                        "filename": "Jordan-Vale-Resume-ATS.docx",
                        "variant_label": "ATS-safe",
                    },
                ],
            },
        },
        {
            "name": "generate_document",
            "state": "done",
            "result": {
                "document_id": "cover-doc",
                "doc_type": "cover_letter",
                "filename": "Jordan-Vale-Cover-Letter.docx",
            },
        },
    ])

    assert text == (
        "Your ATS-safe and Creative-safe resumes plus your cover letter are ready. "
        "The download cards are below. If you want revisions, tell me what to change."
    )


def test_generate_tool_only_followup_text_uses_model_reply(monkeypatch):
    captured = {}

    class _DummyModels:
        def generate_content(self, **kwargs):
            captured.update(kwargs)
            return type("Response", (), {"text": "Your tailored resume is ready."})()

    class _DummyClient:
        models = _DummyModels()

    monkeypatch.setattr(chat, "gemini_client", _DummyClient())

    reply = chat._generate_tool_only_followup_text(
        full_system="System prompt",
        contents=[],
        executed_tools=[
            {
                "name": "generate_document",
                "args": {"doc_type": "resume"},
                "state": "done",
                "result": {
                    "document_id": "resume-doc",
                    "doc_type": "resume",
                    "filename": "Aham-Sel-Resume.docx",
                },
            }
        ],
    )

    assert reply == "Your tailored resume is ready."
    assert "contents" in captured
    completion_prompt = captured["contents"][-1]
    assert "Tool execution for this turn is complete." in completion_prompt.parts[0].text
    assert "- generate_document: created resume file Aham-Sel-Resume.docx" in completion_prompt.parts[0].text


def test_generate_tool_only_followup_text_falls_back_when_model_is_empty(monkeypatch):
    class _DummyModels:
        def generate_content(self, **kwargs):
            return type("Response", (), {"text": ""})()

    class _DummyClient:
        models = _DummyModels()

    monkeypatch.setattr(chat, "gemini_client", _DummyClient())

    reply = chat._generate_tool_only_followup_text(
        full_system="System prompt",
        contents=[],
        executed_tools=[
            {
                "name": "save_user_context",
                "args": {"category": "skills"},
                "state": "done",
                "result": {"status": "saved", "category": "skills"},
            }
        ],
    )

    assert reply == (
        "I saved that information to your profile memory so I can use it in future applications."
    )


class _DummyJobsTable:
    def __init__(self):
        self.inserted = []

    def insert(self, payload):
        self.inserted.append(payload)
        return self

    def execute(self):
        return SimpleNamespace(data=[{"id": "job-synth-1"}])


class _DummySupabase:
    def __init__(self):
        self.jobs = _DummyJobsTable()

    def table(self, name: str):
        assert name == "jobs"
        return self.jobs


def test_ensure_document_job_record_builds_synthetic_job(monkeypatch):
    dummy_supabase = _DummySupabase()
    monkeypatch.setattr(chat, "supabase", dummy_supabase)

    job_id = chat._ensure_document_job_record(
        user_id="user-1",
        conversation_id="conv-1",
        args={
            "doc_type": "resume",
            "sections": {
                "title": "Product Designer",
                "company": "North Coast",
                "summary": "Design systems and interaction design across web and mobile.",
            },
        },
    )

    assert job_id == "job-synth-1"
    assert dummy_supabase.jobs.inserted == [
        {
            "conversation_id": "conv-1",
            "user_id": "user-1",
            "title": "Product Designer at North Coast",
            "company": "North Coast",
            "description_md": (
                "Direct resume generation request\n"
                "Role: Product Designer\n"
                "Company: North Coast\n"
                "Summary: Design systems and interaction design across web and mobile."
            ),
        }
    ]
