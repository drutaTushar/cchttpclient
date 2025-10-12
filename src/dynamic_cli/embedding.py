"""Embedding store backed by SQLite with OpenAI-powered vectors."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import httpx
import numpy as np

from .config import MCPSettings


@dataclass
class EmbeddingRecord:
    section_id: str
    command: str
    subcommand: str
    description: str
    schema: Dict
    embedding: Optional[np.ndarray] = None
    description_hash: Optional[str] = None


class EmbeddingProvider:
    """Protocol-like base for embedding providers."""

    def embed(self, texts: Sequence[str]) -> List[np.ndarray]:
        raise NotImplementedError


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """Embedding provider that delegates to the OpenAI embeddings API."""

    def __init__(
        self,
        model: str,
        api_key: str,
        api_base: Optional[str] = None,
        timeout: float = 15.0,
    ) -> None:
        if not api_key:
            raise RuntimeError(
                "OpenAI API key missing – set the configured environment variable before starting the MCP server."
            )
        self.model = model
        self.api_key = api_key
        self.api_base = api_base.rstrip("/") if api_base else "https://api.openai.com/v1"
        self.timeout = timeout
        self._cache: Dict[str, np.ndarray] = {}

    def embed(self, texts: Sequence[str]) -> List[np.ndarray]:
        outputs: List[np.ndarray] = []
        to_request: List[Tuple[int, str]] = []

        for index, text in enumerate(texts):
            key = _hash_text(text)
            cached = self._cache.get(key)
            if cached is not None:
                outputs.append(cached)
            else:
                outputs.append(np.array([]))
                to_request.append((index, text))

        if to_request:
            order, payloads = zip(*to_request)
            response = httpx.post(
                f"{self.api_base}/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": self.model, "input": list(payloads)},
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()["data"]
            for offset, item in enumerate(data):
                vector = np.array(item["embedding"], dtype=np.float32)
                index = order[offset]
                key = _hash_text(texts[index])
                self._cache[key] = vector
                outputs[index] = vector

        return [vector if vector.size else self._cache[_hash_text(texts[idx])] for idx, vector in enumerate(outputs)]


class HashEmbeddingProvider(EmbeddingProvider):
    """Deterministic fallback provider used for testing without network access."""

    def embed(self, texts: Sequence[str]) -> List[np.ndarray]:
        vectors: List[np.ndarray] = []
        for text in texts:
            # Create a more stable hash-based embedding
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            # Convert to integers, then normalize to prevent overflow
            int_values = np.frombuffer(digest[:128], dtype=np.uint8)  # 128 bytes = 128 dimensions
            # Normalize to [-1, 1] range to prevent overflow
            floats = (int_values.astype(np.float32) - 127.5) / 127.5
            vectors.append(floats)
        return vectors


class EmbeddingStore:
    def __init__(self, path: Path, provider: EmbeddingProvider):
        self.path = Path(path)
        self.provider = provider
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @classmethod
    def from_settings(cls, settings: MCPSettings) -> "EmbeddingStore":
        api_key = os.getenv(settings.api_key_env, "")
        if os.getenv("DYNAMIC_CLI_USE_HASH_EMBEDDINGS") == "1":
            provider: EmbeddingProvider = HashEmbeddingProvider()
        else:
            provider = OpenAIEmbeddingProvider(
                model=settings.embedding_model,
                api_key=api_key,
                api_base=settings.api_base,
            )
        return cls(settings.persist_path, provider)

    def _initialize(self) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS command_embeddings (
                    section_id TEXT PRIMARY KEY,
                    command TEXT NOT NULL,
                    subcommand TEXT NOT NULL,
                    description TEXT NOT NULL,
                    schema_json TEXT NOT NULL,
                    description_hash TEXT NOT NULL,
                    embedding BLOB NOT NULL
                )
                """
            )
            
            # Query cache table for embedding cache
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS query_cache (
                    query_text TEXT PRIMARY KEY,
                    query_hash TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            
            # Validated queries table for exact matches
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS validated_queries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query_text TEXT NOT NULL,
                    command TEXT NOT NULL,
                    subcommand TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    validated_by TEXT DEFAULT 'user',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(query_text, command, subcommand)
                )
                """
            )

    def rebuild(self, records: Sequence[EmbeddingRecord]) -> None:
        target_hashes = {record.section_id: _hash_record(record) for record in records}

        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            existing_rows = {
                row["section_id"]: row
                for row in conn.execute(
                    "SELECT section_id, description_hash, embedding FROM command_embeddings"
                ).fetchall()
            }

        embeddings: Dict[str, np.ndarray] = {}
        to_embed: List[EmbeddingRecord] = []

        for record in records:
            record_hash = target_hashes[record.section_id]
            existing = existing_rows.get(record.section_id)
            if existing and existing["description_hash"] == record_hash:
                embeddings[record.section_id] = np.frombuffer(
                    existing["embedding"], dtype=np.float32
                )
            else:
                to_embed.append(record)

        if to_embed:
            vectors = self.provider.embed([rec.description for rec in to_embed])
            for record, vector in zip(to_embed, vectors):
                embeddings[record.section_id] = vector

        with sqlite3.connect(self.path) as conn:
            conn.execute("DELETE FROM command_embeddings")
            for record in records:
                vector = embeddings[record.section_id]
                conn.execute(
                    """
                    INSERT INTO command_embeddings(
                        section_id,
                        command,
                        subcommand,
                        description,
                        schema_json,
                        description_hash,
                        embedding
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.section_id,
                        record.command,
                        record.subcommand,
                        record.description,
                        json.dumps(record.schema, sort_keys=True),
                        target_hashes[record.section_id],
                        vector.astype(np.float32).tobytes(),
                    ),
                )

    def all(self) -> List[EmbeddingRecord]:
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT section_id, command, subcommand, description, schema_json, description_hash, embedding FROM command_embeddings"
            ).fetchall()

        records: List[EmbeddingRecord] = []
        for row in rows:
            records.append(
                EmbeddingRecord(
                    section_id=row["section_id"],
                    command=row["command"],
                    subcommand=row["subcommand"],
                    description=row["description"],
                    schema=json.loads(row["schema_json"]),
                    embedding=np.frombuffer(row["embedding"], dtype=np.float32),
                    description_hash=row["description_hash"],
                )
            )
        return records

    def query(self, text: str, top_k: int = 3) -> List[Tuple[EmbeddingRecord, float]]:
        # First check for validated exact matches
        validated_match = self.get_validated_query(text)
        if validated_match:
            command, subcommand, confidence = validated_match
            # Find the matching record
            records = self.all()
            for record in records:
                if record.command == command and record.subcommand == subcommand:
                    return [(record, confidence)]
        
        # Get or create query embedding with caching
        query_vector = self._get_cached_query_embedding(text)
        records = self.all()
        scored = [
            (record, _cosine_similarity(query_vector, record.embedding if record.embedding is not None else np.array([])))
            for record in records
        ]
        ranked = sorted(scored, key=lambda item: item[1], reverse=True)
        return ranked[:top_k]
    
    def _get_cached_query_embedding(self, text: str) -> np.ndarray:
        """Get query embedding from cache or compute and cache it."""
        query_hash = _hash_text(text)
        
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            cached = conn.execute(
                "SELECT embedding FROM query_cache WHERE query_hash = ?",
                (query_hash,)
            ).fetchone()
            
            if cached:
                return np.frombuffer(cached["embedding"], dtype=np.float32)
        
        # Compute new embedding
        query_vector = self.provider.embed([text])[0]
        
        # Cache it
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO query_cache (query_text, query_hash, embedding) VALUES (?, ?, ?)",
                (text, query_hash, query_vector.astype(np.float32).tobytes())
            )
        
        return query_vector
    
    def get_validated_query(self, text: str) -> Optional[Tuple[str, str, float]]:
        """Check if query has a validated exact match."""
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            result = conn.execute(
                "SELECT command, subcommand, confidence FROM validated_queries WHERE query_text = ?",
                (text,)
            ).fetchone()
            
            if result:
                return (result["command"], result["subcommand"], result["confidence"])
        return None
    
    def add_validated_query(self, query_text: str, command: str, subcommand: str, confidence: float = 1.0) -> bool:
        """Add a validated query mapping."""
        try:
            with sqlite3.connect(self.path) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO validated_queries (query_text, command, subcommand, confidence) VALUES (?, ?, ?, ?)",
                    (query_text, command, subcommand, confidence)
                )
            return True
        except sqlite3.Error:
            return False
    
    def get_all_validated_queries(self) -> List[Dict[str, Any]]:
        """Get all validated queries for admin interface."""
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            results = conn.execute(
                "SELECT * FROM validated_queries ORDER BY created_at DESC"
            ).fetchall()
            
            return [dict(row) for row in results]
    
    def remove_validated_query(self, query_id: int) -> bool:
        """Remove a validated query."""
        try:
            with sqlite3.connect(self.path) as conn:
                cursor = conn.execute(
                    "DELETE FROM validated_queries WHERE id = ?",
                    (query_id,)
                )
                return cursor.rowcount > 0
        except sqlite3.Error:
            return False


def _hash_record(record: EmbeddingRecord) -> str:
    payload = json.dumps(
        {
            "section": record.section_id,
            "command": record.command,
            "subcommand": record.subcommand,
            "description": record.description,
            "schema": record.schema,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _cosine_similarity(vector_a: np.ndarray, vector_b: np.ndarray) -> float:
    if vector_a.size == 0 or vector_b.size == 0:
        return 0.0
    denom = np.linalg.norm(vector_a) * np.linalg.norm(vector_b)
    if denom == 0:
        return 0.0
    return float(np.dot(vector_a, vector_b) / denom)
