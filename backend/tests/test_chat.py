import chat


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
