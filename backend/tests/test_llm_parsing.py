"""Verify LLM response parsing hardening."""
from app.agents.llm_agent import _parse_llm_decision, VALID_ACTIONS


def test_valid_decision_passes_through():
    r = _parse_llm_decision(
        {"action": "BUY_LIMIT", "qty": 2, "price": 5400.25,
         "conviction": 0.7, "reasoning": "test", "market_read": "STRONG_BULL"},
        max_position=5, current_price=5400.0, agent_id="test",
    )
    assert r["action"] == "BUY_LIMIT"
    assert r["qty"] == 2
    assert r["price"] == 5400.25
    assert r["conviction"] == 0.7


def test_invalid_action_defaults_to_hold():
    r = _parse_llm_decision(
        {"action": "BUY", "qty": 2, "price": 5400.0},
        max_position=5, current_price=5400.0, agent_id="test",
    )
    assert r["action"] == "HOLD"
    assert r["qty"] == 0  # HOLD forces qty=0


def test_string_qty_coerced():
    r = _parse_llm_decision(
        {"action": "BUY_LIMIT", "qty": "2", "price": 5400.0},
        max_position=5, current_price=5400.0, agent_id="test",
    )
    assert r["qty"] == 2


def test_non_numeric_qty_falls_back_to_zero():
    r = _parse_llm_decision(
        {"action": "BUY_LIMIT", "qty": "two", "price": 5400.0},
        max_position=5, current_price=5400.0, agent_id="test",
    )
    assert r["qty"] == 0


def test_negative_qty_clamped_to_zero():
    r = _parse_llm_decision(
        {"action": "BUY_MARKET", "qty": -5, "price": 5400.0},
        max_position=5, current_price=5400.0, agent_id="test",
    )
    assert r["qty"] == 0


def test_qty_above_max_clamped():
    r = _parse_llm_decision(
        {"action": "BUY_LIMIT", "qty": 100, "price": 5400.0},
        max_position=5, current_price=5400.0, agent_id="test",
    )
    assert r["qty"] == 5


def test_float_qty_truncated():
    r = _parse_llm_decision(
        {"action": "BUY_LIMIT", "qty": 2.7, "price": 5400.0},
        max_position=5, current_price=5400.0, agent_id="test",
    )
    assert r["qty"] == 2


def test_invalid_price_uses_current():
    r = _parse_llm_decision(
        {"action": "BUY_LIMIT", "qty": 1, "price": "market"},
        max_position=5, current_price=5400.0, agent_id="test",
    )
    assert r["price"] == 5400.0


def test_negative_price_uses_current():
    r = _parse_llm_decision(
        {"action": "BUY_LIMIT", "qty": 1, "price": -100},
        max_position=5, current_price=5400.0, agent_id="test",
    )
    assert r["price"] == 5400.0


def test_conviction_clamped_high():
    r = _parse_llm_decision(
        {"action": "HOLD", "conviction": 1.5},
        max_position=5, current_price=5400.0, agent_id="test",
    )
    assert r["conviction"] == 1.0


def test_conviction_clamped_low():
    r = _parse_llm_decision(
        {"action": "HOLD", "conviction": -0.3},
        max_position=5, current_price=5400.0, agent_id="test",
    )
    assert r["conviction"] == 0.0


def test_missing_fields_use_defaults():
    r = _parse_llm_decision(
        {}, max_position=5, current_price=5400.0, agent_id="test",
    )
    assert r["action"] == "HOLD"
    assert r["qty"] == 0
    assert r["price"] == 5400.0
    assert r["conviction"] == 0.5


def test_hold_forces_qty_zero():
    """HOLD action should always have qty=0 even if LLM returns nonzero."""
    r = _parse_llm_decision(
        {"action": "HOLD", "qty": 5},
        max_position=5, current_price=5400.0, agent_id="test",
    )
    assert r["qty"] == 0


def test_exit_long_forces_qty_zero():
    """EXIT_LONG should have qty=0."""
    r = _parse_llm_decision(
        {"action": "EXIT_LONG", "qty": 3},
        max_position=5, current_price=5400.0, agent_id="test",
    )
    assert r["qty"] == 0
