"""Unit tests for the investigation engine."""

import pytest

from app.investigator import detect_intent, _clean_function_ref


# ── Intent detection tests ─────────────────────────────────────────────────────

class TestDetectIntent:
    def test_who_calls(self):
        intent, refs = detect_intent("Who calls process_order?")
        assert intent == "find_callers"
        assert "process_order" in refs[0]

    def test_what_calls(self):
        intent, refs = detect_intent("What calls compute_total?")
        assert intent == "find_callers"
        assert "compute_total" in refs[0]

    def test_callers_of(self):
        intent, refs = detect_intent("callers of save_order")
        assert intent == "find_callers"

    def test_what_does_call(self):
        intent, refs = detect_intent("What does handle_request call?")
        assert intent == "find_callees"
        assert "handle_request" in refs[0]

    def test_callees_of(self):
        intent, refs = detect_intent("callees of process_order")
        assert intent == "find_callees"

    def test_impact_of(self):
        intent, refs = detect_intent("What is the impact of changing get_unit_price?")
        assert intent == "find_impact"
        assert "get_unit_price" in refs[0]

    def test_affected_by(self):
        intent, refs = detect_intent("What is affected by changes to save_order?")
        assert intent == "find_impact"

    def test_path_from_to(self):
        intent, refs = detect_intent("path from handle_request to save_order")
        assert intent == "find_path"
        assert len(refs) >= 2

    def test_does_call(self):
        intent, refs = detect_intent("Does handle_request call save_order?")
        assert intent == "find_path"
        assert len(refs) >= 2

    def test_verify_calls(self):
        intent, refs = detect_intent("verify that process_order calls compute_total")
        assert intent == "verify_relationship"
        assert len(refs) >= 2

    def test_backtick_extraction(self):
        intent, refs = detect_intent("Tell me about `my_function`")
        assert len(refs) >= 1
        assert "my_function" in refs[0]

    def test_unknown_intent(self):
        intent, refs = detect_intent("How is the weather today?")
        assert intent == "unknown"


# ── Function ref cleaning ──────────────────────────────────────────────────────

class TestCleanFunctionRef:
    def test_strips_whitespace(self):
        assert _clean_function_ref("  my_func  ") == "my_func"

    def test_strips_quotes(self):
        assert _clean_function_ref("'my_func'") == "my_func"
        assert _clean_function_ref('"my_func"') == "my_func"

    def test_strips_backticks(self):
        assert _clean_function_ref("`my_func`") == "my_func"

    def test_strips_prefix_function(self):
        assert _clean_function_ref("function my_func") == "my_func"

    def test_strips_prefix_the(self):
        assert _clean_function_ref("the my_func") == "my_func"
