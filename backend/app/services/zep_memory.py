"""
Zep Cloud Integration — Knowledge graph memory for trading agents.
Seeds the Al Brooks methodology as a knowledge graph.
Records agent trades and market events as temporal facts.
"""
import logging
import asyncio
from typing import Optional

logger = logging.getLogger(__name__)

# Zep import with graceful fallback
try:
    from zep_cloud.client import AsyncZep
    from zep_cloud import Message
    ZEP_AVAILABLE = True
except ImportError:
    ZEP_AVAILABLE = False
    logger.warning("zep-cloud not installed. Memory features disabled. "
                   "Install with: pip install zep-cloud")


class ZepMemoryService:
    """
    Manages Zep Cloud knowledge graph for trading simulation.
    
    Graph structure:
    - Entities: Market concepts (climax, trend, range, measured_move)
    - Entities: Agent identities with their trading style
    - Relationships: "detected_pattern", "entered_position", "exited_at"
    - Episodes: Each bar's market state + agent decisions
    """

    def __init__(self, api_key: str, group_id: str = "mirofish_trading"):
        self.api_key = api_key
        self.group_id = group_id
        self._client: Optional[object] = None
        self._enabled = bool(api_key) and ZEP_AVAILABLE

    async def initialize(self):
        """Connect to Zep and create the group if needed."""
        if not self._enabled:
            logger.info("Zep memory disabled (no API key or zep-cloud not installed).")
            return

        try:
            self._client = AsyncZep(api_key=self.api_key)
            # Create or get the group for this simulation
            try:
                await self._client.graph.add(
                    group_id=self.group_id,
                    type="json",
                    data='{"type": "initialization", "content": "MiroFish Trading Simulation group created."}',
                )
            except Exception:
                pass  # Group might already exist
            logger.info(f"Zep memory initialized. Group: {self.group_id}")
        except Exception as e:
            logger.error(f"Zep initialization failed: {e}")
            self._enabled = False

    async def seed_methodology(self, methodology_text: str):
        """Seed the Al Brooks methodology into the knowledge graph."""
        if not self._enabled:
            return

        try:
            # Break methodology into chunks for better graph extraction
            chunks = methodology_text.split("\n\n")
            for i, chunk in enumerate(chunks):
                if chunk.strip():
                    await self._client.graph.add(
                        group_id=self.group_id,
                        type="text",
                        data=chunk.strip(),
                    )
            logger.info(f"Seeded {len(chunks)} methodology chunks into Zep graph.")
        except Exception as e:
            logger.error(f"Zep seed failed: {e}")

    async def record_bar_event(self, bar_data: dict, market_state: dict,
                                agent_decisions: list[dict]):
        """Record a bar's market state and agent decisions as an episode."""
        if not self._enabled:
            return

        try:
            event_text = (
                f"Bar {bar_data['timestamp']}: "
                f"O={bar_data['open']:.2f} H={bar_data['high']:.2f} "
                f"L={bar_data['low']:.2f} C={bar_data['close']:.2f}. "
                f"Market cycle: {market_state.get('cycle', 'unknown')}. "
                f"Always-in: {market_state.get('always_in_dir', 'flat')}. "
            )

            # Add notable agent actions
            active_decisions = [d for d in agent_decisions
                                if d.get("action") not in ("HOLD", "N/A")]
            if active_decisions:
                inst_actions = [d for d in active_decisions if d.get("agent_type") == "INSTITUTIONAL"]
                retail_actions = [d for d in active_decisions if d.get("agent_type") == "RETAIL"]
                event_text += (
                    f"Institutional actions: {len(inst_actions)}. "
                    f"Retail actions: {len(retail_actions)}. "
                )
                for d in inst_actions[:3]:
                    event_text += f"{d['agent_id']}: {d['action']} ({d.get('reasoning', '')[:60]}). "

            await self._client.graph.add(
                group_id=self.group_id,
                type="text",
                data=event_text,
            )
        except Exception as e:
            logger.debug(f"Zep record failed: {e}")

    async def query_graph(self, query: str, limit: int = 5) -> list[str]:
        """Query the knowledge graph for relevant context."""
        if not self._enabled:
            return []

        try:
            results = await self._client.graph.search(
                group_id=self.group_id,
                query=query,
                limit=limit,
            )
            return [r.content for r in results if hasattr(r, 'content')]
        except Exception as e:
            logger.debug(f"Zep query failed: {e}")
            return []

    async def close(self):
        """Cleanup."""
        self._client = None
