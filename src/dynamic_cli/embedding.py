"""Local embedding store built on SQLite."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List
import json
import sqlite3

import numpy as np
from sentence_transformers import SentenceTransformer


@dataclass
class EmbeddingRecord:
    section_id: str
    command: str
    subcommand: str
    description: str
    schema: Dict
    embedding: np.ndarray


class EmbeddingStore:
    def __init__(self, path: Path, model_name: str):
        self.path = Path(path)
        self.model_name = model_name
        self.model = SentenceTransformer(model_name)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

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
                    embedding BLOB NOT NULL
                )
                """
            )

    def rebuild(self, records: Sequence[EmbeddingRecord]) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute("DELETE FROM command_embeddings")
            for record in records:
                conn.execute(
                    """
                    INSERT INTO command_embeddings(section_id, command, subcommand, description, schema_json, embedding)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.section_id,
                        record.command,
                        record.subcommand,
                        record.description,
                        json.dumps(record.schema),
                        record.embedding.astype(np.float32).tobytes(),
                    ),
                )

    def all(self) -> List[EmbeddingRecord]:
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute(
                "SELECT section_id, command, subcommand, description, schema_json, embedding FROM command_embeddings"
            )
            rows = cursor.fetchall()

        records: List[EmbeddingRecord] = []
        for section_id, command, subcommand, description, schema_json, embedding_blob in rows:
            embedding = np.frombuffer(embedding_blob, dtype=np.float32)
            record = EmbeddingRecord(
                section_id=section_id,
                command=command,
                subcommand=subcommand,
                description=description,
                schema=json.loads(schema_json),
                embedding=embedding,
            )
            records.append(record)
        return records

    def query(self, text: str, top_k: int = 3) -> List[tuple[EmbeddingRecord, float]]:
        query_vector = self.model.encode(text, convert_to_numpy=True)
        records = self.all()
        scored = [
            (record, _cosine_similarity(query_vector, record.embedding))
            for record in records
        ]
        ranked = sorted(scored, key=lambda item: item[1], reverse=True)
        return ranked[:top_k]

    def embed_descriptions(self, descriptions: Iterable[str]) -> List[np.ndarray]:
        return list(self.model.encode(list(descriptions), convert_to_numpy=True))


def _cosine_similarity(vector_a: np.ndarray, vector_b: np.ndarray) -> float:
    denom = np.linalg.norm(vector_a) * np.linalg.norm(vector_b)
    if denom == 0:
        return 0.0
    return float(np.dot(vector_a, vector_b) / denom)
