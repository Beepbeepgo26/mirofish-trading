"""
Configuration management — loads from .env and provides typed access.
"""
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class LLMConfig:
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model_name: str = "gpt-4o"

    @classmethod
    def primary(cls) -> "LLMConfig":
        return cls(
            api_key=os.getenv("LLM_API_KEY", ""),
            base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
            model_name=os.getenv("LLM_MODEL_NAME", "gpt-4o"),
        )

    @classmethod
    def boost(cls) -> "LLMConfig":
        return cls(
            api_key=os.getenv("LLM_BOOST_API_KEY", os.getenv("LLM_API_KEY", "")),
            base_url=os.getenv("LLM_BOOST_BASE_URL", os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")),
            model_name=os.getenv("LLM_BOOST_MODEL_NAME", "gpt-4o-mini"),
        )


@dataclass
class SimConfig:
    max_rounds: int = 30
    agents_institutional: int = 3
    agents_retail: int = 5
    agents_market_maker: int = 1
    agents_noise: int = 5
    concurrency: int = 5

    @classmethod
    def from_env(cls) -> "SimConfig":
        return cls(
            max_rounds=int(os.getenv("SIM_MAX_ROUNDS", "30")),
            agents_institutional=int(os.getenv("SIM_AGENTS_INSTITUTIONAL", "3")),
            agents_retail=int(os.getenv("SIM_AGENTS_RETAIL", "5")),
            agents_market_maker=int(os.getenv("SIM_AGENTS_MARKET_MAKER", "1")),
            agents_noise=int(os.getenv("SIM_AGENTS_NOISE", "5")),
            concurrency=int(os.getenv("SIM_CONCURRENCY", "5")),
        )


@dataclass
class AppConfig:
    llm_primary: LLMConfig = field(default_factory=LLMConfig.primary)
    llm_boost: LLMConfig = field(default_factory=LLMConfig.boost)
    sim: SimConfig = field(default_factory=SimConfig.from_env)
    zep_api_key: str = ""
    databento_api_key: str = ""
    gcs_bucket: str = ""
    flask_port: int = 5001
    log_level: str = "INFO"
    log_dir: str = "./logs"

    @classmethod
    def load(cls) -> "AppConfig":
        return cls(
            llm_primary=LLMConfig.primary(),
            llm_boost=LLMConfig.boost(),
            sim=SimConfig.from_env(),
            zep_api_key=os.getenv("ZEP_API_KEY", ""),
            databento_api_key=os.getenv("DATABENTO_API_KEY", ""),
            gcs_bucket=os.getenv("GCS_BUCKET", ""),
            flask_port=int(os.getenv("FLASK_PORT", "5001")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            log_dir=os.getenv("LOG_DIR", "./logs"),
        )

    def validate(self):
        """Validate configuration. Raises ValueError on critical issues."""
        # LLM API key is required
        if not self.llm_primary.api_key:
            raise ValueError(
                "LLM_API_KEY is not set. Copy .env.example to .env and add your OpenAI API key. "
                "The simulation cannot run without an LLM provider."
            )

        # Agent count bounds
        MAX_AGENTS = {"institutional": 20, "retail": 100, "market_maker": 10, "noise": 50}
        for agent_type, max_count in MAX_AGENTS.items():
            count = getattr(self.sim, f"agents_{agent_type}", 0)
            if count < 0:
                raise ValueError(f"agents_{agent_type} cannot be negative (got {count})")
            if count > max_count:
                raise ValueError(
                    f"agents_{agent_type} exceeds maximum of {max_count} (got {count}). "
                    f"This would cost ~${count * 30 * 0.003:.0f} in LLM tokens per simulation."
                )

        # Concurrency bounds
        if self.sim.concurrency < 1 or self.sim.concurrency > 50:
            raise ValueError(f"SIM_CONCURRENCY must be 1-50 (got {self.sim.concurrency})")

        # Warn about optional services (don't raise)
        import logging
        logger = logging.getLogger(__name__)
        if not self.zep_api_key:
            logger.info("ZEP_API_KEY not set — knowledge graph memory disabled.")
        if not self.databento_api_key:
            logger.info("DATABENTO_API_KEY not set — Databento features disabled.")
        if not self.gcs_bucket:
            logger.info("GCS_BUCKET not set — using local disk storage (lost on Cloud Run restart).")


config = AppConfig.load()
