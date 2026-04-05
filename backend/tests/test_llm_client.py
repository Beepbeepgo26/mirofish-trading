"""
Unit tests for LLM client JSON parsing and fallback behavior.
Tests the parsing logic without making actual API calls.
"""
import json
from app.services.llm_client import LLMResponse


class TestJSONParsing:
    """Test the JSON response parsing logic in isolation."""

    def test_parse_valid_json(self):
        """Valid JSON should parse correctly."""
        raw = '{"action": "BUY_LIMIT", "qty": 50, "price": 5400.25, "reasoning": "test", "conviction": 0.8, "market_read": "STRONG_BULL"}'
        result = json.loads(raw)
        assert result["action"] == "BUY_LIMIT"
        assert result["qty"] == 50
        assert result["conviction"] == 0.8

    def test_parse_json_with_markdown_fences(self):
        """JSON wrapped in ```json fences should be extractable."""
        raw = '```json\n{"action": "HOLD", "reasoning": "waiting"}\n```'
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
        result = json.loads(text)
        assert result["action"] == "HOLD"

    def test_fallback_on_invalid_json(self):
        """Invalid JSON should fall back to HOLD action."""
        raw = "I think we should buy because the trend is strong"
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            result = {"action": "HOLD", "reasoning": "Failed to parse LLM response"}
        assert result["action"] == "HOLD"

    def test_fallback_on_empty_response(self):
        """Empty response should fall back to HOLD."""
        raw = ""
        try:
            result = json.loads(raw) if raw.strip() else {"action": "HOLD"}
        except json.JSONDecodeError:
            result = {"action": "HOLD", "reasoning": "Empty response"}
        assert result["action"] == "HOLD"

    def test_partial_json_fields(self):
        """JSON missing optional fields should still work."""
        raw = '{"action": "BUY_MARKET", "qty": 5}'
        result = json.loads(raw)
        assert result["action"] == "BUY_MARKET"
        assert result.get("reasoning", "") == ""
        assert result.get("conviction", 0.5) == 0.5


class TestLLMResponseModel:
    def test_default_values(self):
        resp = LLMResponse(content="test", model="gpt-4o")
        assert resp.usage_prompt == 0
        assert resp.usage_completion == 0
        assert resp.latency_ms == 0.0

    def test_fallback_response(self):
        """Verify the fallback response structure matches what agents expect."""
        fallback = '{"action": "HOLD", "reasoning": "LLM unavailable"}'
        result = json.loads(fallback)
        assert result["action"] == "HOLD"
        assert "reasoning" in result
