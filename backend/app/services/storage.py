"""
Google Cloud Storage Persistence — Saves simulation results durably.
Results survive Cloud Run scale-to-zero and instance recycling.

Storage structure:
  gs://{bucket}/simulations/{sim_id}/results.json
  gs://{bucket}/simulations/{sim_id}/decision_log.jsonl
  gs://{bucket}/simulations/{sim_id}/summary.txt
  gs://{bucket}/simulations/{sim_id}/metadata.json
"""
import json
import logging
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from google.cloud import storage as gcs
    GCS_AVAILABLE = True
except ImportError:
    GCS_AVAILABLE = False
    logger.warning("google-cloud-storage not installed. Run: pip install google-cloud-storage")


class StorageService:
    """
    Persists simulation results to Google Cloud Storage.
    Falls back to local disk if GCS is not configured.
    """

    def __init__(self, bucket_name: Optional[str] = None, local_fallback: str = "./output"):
        self.bucket_name = bucket_name or os.getenv("GCS_BUCKET", "")
        self.local_fallback = local_fallback
        self._client = None
        self._bucket = None
        self._enabled = bool(self.bucket_name) and GCS_AVAILABLE

        if not GCS_AVAILABLE:
            logger.warning("GCS SDK not available. Using local storage only.")
        elif not self.bucket_name:
            logger.warning("GCS_BUCKET not set. Using local storage only.")

    def _get_bucket(self):
        if self._bucket is None and self._enabled:
            try:
                self._client = gcs.Client()
                self._bucket = self._client.bucket(self.bucket_name)
                # Check if bucket exists, create if not
                if not self._bucket.exists():
                    self._bucket = self._client.create_bucket(
                        self.bucket_name,
                        location="us-west2",
                    )
                    logger.info(f"Created GCS bucket: {self.bucket_name}")
                else:
                    logger.info(f"Connected to GCS bucket: {self.bucket_name}")
            except Exception as e:
                logger.error(f"GCS connection failed: {e}. Falling back to local storage.")
                self._enabled = False
        return self._bucket

    def save_results(self, sim_id: str, results: dict) -> dict:
        """
        Save full simulation results. Returns paths where files were stored.
        """
        paths = {}

        # results.json — the full structured output
        results_json = json.dumps(results, indent=2, default=str)
        paths["results"] = self._write(f"simulations/{sim_id}/results.json", results_json)

        # decision_log.jsonl — one decision per line for easy streaming/parsing
        decisions = results.get("decisions", [])
        if decisions:
            lines = [json.dumps(d, default=str) for d in decisions]
            paths["decision_log"] = self._write(
                f"simulations/{sim_id}/decision_log.jsonl",
                "\n".join(lines)
            )

        # summary.txt — human-readable
        summary = self._build_summary(sim_id, results)
        paths["summary"] = self._write(f"simulations/{sim_id}/summary.txt", summary)

        # metadata.json — lightweight index entry for listing simulations
        metadata = {
            "sim_id": sim_id,
            "scenario": results.get("scenario", "unknown"),
            "source": results.get("source", "synthetic"),
            "created_at": datetime.utcnow().isoformat() + "Z",
            "total_bars": results.get("total_bars", 0),
            "total_decisions": results.get("total_decisions", 0),
            "pnl_by_type": results.get("pnl_by_type", {}),
            "validation": results.get("validation"),
            "llm_stats": results.get("llm_stats"),
        }
        paths["metadata"] = self._write(
            f"simulations/{sim_id}/metadata.json",
            json.dumps(metadata, indent=2, default=str)
        )

        storage_type = "GCS" if self._enabled else "local"
        logger.info(f"Saved simulation {sim_id} to {storage_type}: {list(paths.keys())}")
        return paths

    def load_results(self, sim_id: str) -> Optional[dict]:
        """Load full results for a simulation."""
        content = self._read(f"simulations/{sim_id}/results.json")
        if content:
            return json.loads(content)
        return None

    def load_decisions(self, sim_id: str) -> list[dict]:
        """Load decision log for a simulation."""
        content = self._read(f"simulations/{sim_id}/decision_log.jsonl")
        if content:
            return [json.loads(line) for line in content.strip().split("\n") if line]
        return []

    def load_summary(self, sim_id: str) -> Optional[str]:
        """Load human-readable summary."""
        return self._read(f"simulations/{sim_id}/summary.txt")

    def list_simulations(self, limit: int = 50) -> list[dict]:
        """List all saved simulations with metadata."""
        simulations = []

        if self._enabled:
            try:
                bucket = self._get_bucket()
                if bucket:
                    blobs = bucket.list_blobs(prefix="simulations/", delimiter="/")
                    # Get prefixes (simulation directories)
                    prefixes = list(blobs.prefixes) if hasattr(blobs, 'prefixes') else []

                    # Also iterate through blobs to trigger prefix collection
                    for _ in blobs:
                        pass
                    prefixes = list(blobs.prefixes) if hasattr(blobs, 'prefixes') else prefixes

                    for prefix in sorted(prefixes, reverse=True)[:limit]:
                        sim_id = prefix.strip("/").split("/")[-1]
                        meta_content = self._read(f"simulations/{sim_id}/metadata.json")
                        if meta_content:
                            simulations.append(json.loads(meta_content))
                        else:
                            simulations.append({"sim_id": sim_id})
            except Exception as e:
                logger.error(f"GCS list failed: {e}")

        else:
            # Local fallback
            sim_dir = os.path.join(self.local_fallback, "")
            if os.path.exists(self.local_fallback):
                for entry in sorted(os.listdir(self.local_fallback), reverse=True)[:limit]:
                    meta_path = os.path.join(self.local_fallback, entry, "metadata.json")
                    if os.path.exists(meta_path):
                        with open(meta_path) as f:
                            simulations.append(json.loads(f.read()))
                    else:
                        simulations.append({"sim_id": entry})

        return simulations

    def delete_simulation(self, sim_id: str) -> bool:
        """Delete all files for a simulation."""
        prefix = f"simulations/{sim_id}/"

        if self._enabled:
            try:
                bucket = self._get_bucket()
                if bucket:
                    blobs = list(bucket.list_blobs(prefix=prefix))
                    for blob in blobs:
                        blob.delete()
                    logger.info(f"Deleted {len(blobs)} files for simulation {sim_id}")
                    return True
            except Exception as e:
                logger.error(f"GCS delete failed: {e}")
                return False
        else:
            import shutil
            local_path = os.path.join(self.local_fallback, sim_id)
            if os.path.exists(local_path):
                shutil.rmtree(local_path)
                return True
        return False

    def _write(self, path: str, content: str) -> str:
        """Write content to GCS or local disk. Returns the storage path."""
        if self._enabled:
            try:
                bucket = self._get_bucket()
                if bucket:
                    blob = bucket.blob(path)
                    blob.upload_from_string(content, content_type="application/json")
                    return f"gs://{self.bucket_name}/{path}"
            except Exception as e:
                logger.error(f"GCS write failed for {path}: {e}")
                # Fall through to local

        # Local fallback
        local_path = os.path.join(self.local_fallback, path.replace("simulations/", ""))
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "w") as f:
            f.write(content)
        return local_path

    def _read(self, path: str) -> Optional[str]:
        """Read content from GCS or local disk."""
        if self._enabled:
            try:
                bucket = self._get_bucket()
                if bucket:
                    blob = bucket.blob(path)
                    if blob.exists():
                        return blob.download_as_text()
            except Exception as e:
                logger.error(f"GCS read failed for {path}: {e}")

        # Local fallback
        local_path = os.path.join(self.local_fallback, path.replace("simulations/", ""))
        if os.path.exists(local_path):
            with open(local_path) as f:
                return f.read()
        return None

    def _build_summary(self, sim_id: str, results: dict) -> str:
        """Build human-readable summary text."""
        lines = []
        lines.append("=" * 70)
        lines.append(f"  SIMULATION SUMMARY: {results.get('scenario', 'Unknown')}")
        lines.append(f"  ID: {sim_id}")
        lines.append(f"  Source: {results.get('source', 'synthetic')}")
        lines.append("=" * 70)
        lines.append("")
        lines.append(f"  Total bars: {results.get('total_bars', 0)}")
        lines.append(f"  Total decisions: {results.get('total_decisions', 0)}")
        lines.append("")

        # P&L
        pnl = results.get("pnl_by_type", {})
        lines.append("  P&L BY AGENT TYPE:")
        lines.append(f"  {'Type':<15} {'N':>5} {'Realized':>12} {'Unrealized':>12} {'W':>4} {'L':>4}")
        lines.append(f"  {'-' * 55}")
        for atype, stats in sorted(pnl.items()):
            lines.append(
                f"  {atype:<15} {stats.get('agents', 0):>5} "
                f"${stats.get('total_realized', 0):>10,.0f} "
                f"${stats.get('total_unrealized', 0):>10,.0f} "
                f"{stats.get('winners', 0):>4} {stats.get('losers', 0):>4}"
            )

        # LLM stats
        llm = results.get("llm_stats", {})
        lines.append("")
        lines.append("  LLM Usage:")
        for tier, stats in llm.items():
            lines.append(f"    {tier}: {stats.get('total_calls', 0)} calls, "
                         f"{stats.get('total_tokens', 0)} tokens, "
                         f"{stats.get('errors', 0)} errors")

        # Validation
        val = results.get("validation")
        if val and val.get("comparison_available"):
            lines.append("")
            lines.append("  PREDICTION vs ACTUAL:")
            lines.append(f"    Predicted direction: {val.get('predicted_direction')}")
            lines.append(f"    Actual direction:    {val.get('actual_direction')}")
            lines.append(f"    Direction correct:   {'YES' if val.get('direction_correct') else 'NO'}")
            lines.append(f"    Price error:         {val.get('price_error_points', 'N/A')} points")
            lines.append(f"    Inst. consensus:     {val.get('institutional_consensus')}")

        return "\n".join(lines)
