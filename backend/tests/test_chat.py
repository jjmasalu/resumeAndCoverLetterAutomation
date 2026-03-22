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
