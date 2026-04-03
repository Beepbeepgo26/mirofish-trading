"""
Unit tests for configuration validation and .env fail-fast behavior.
"""
import pytest
import os
from unittest.mock import patch
from app.config import LLMConfig, SimConfig, AppConfig


class TestSimConfig:
    def test_default_values(self):
        with patch.dict(os.environ, {}, clear=True):
            config = SimConfig.from_env()
        assert config.max_rounds == 30
        assert config.agents_institutional == 3
        assert config.agents_retail == 5
        assert config.agents_market_maker == 1
        assert config.agents_noise == 5
        assert config.concurrency == 5

    def test_env_override(self):
        env = {"SIM_AGENTS_INSTITUTIONAL": "3", "SIM_AGENTS_RETAIL": "10"}
        with patch.dict(os.environ, env, clear=True):
            config = SimConfig.from_env()
        assert config.agents_institutional == 3
        assert config.agents_retail == 10


class TestLLMConfig:
    def test_primary_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            config = LLMConfig.primary()
        assert config.base_url == "https://api.openai.com/v1"
        assert config.model_name == "gpt-4o"
        assert config.api_key == ""

    def test_boost_defaults(self):
        with patch.dict(os.environ, {"LLM_API_KEY": "test-key"}, clear=True):
            config = LLMConfig.boost()
        # Boost should fall back to primary key if not set
        assert config.api_key == "test-key"
        assert config.model_name == "gpt-4o-mini"


class TestAppConfigValidation:
    def test_validate_missing_llm_key_raises(self):
        """AppConfig.validate() should raise if LLM_API_KEY is missing."""
        with patch.dict(os.environ, {}, clear=True):
            config = AppConfig.load()
            with pytest.raises(ValueError, match="LLM_API_KEY"):
                config.validate()

    def test_validate_with_llm_key_passes(self):
        """AppConfig.validate() should pass if LLM_API_KEY is set."""
        with patch.dict(os.environ, {"LLM_API_KEY": "sk-test"}, clear=True):
            config = AppConfig.load()
            config.validate()  # Should not raise

    def test_validate_agent_bounds(self):
        """Agent counts should be within reasonable bounds."""
        config = AppConfig.load()
        config.sim.agents_institutional = 100
        with pytest.raises(ValueError, match="institutional"):
            config.validate()
