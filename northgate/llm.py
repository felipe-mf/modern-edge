"""The one place the system calls Claude.

Claude is used only to turn unstructured input (contract PDFs, scanned forms, free-text
call-outs) into a typed Pydantic object. It never decides pay, codes or billing; code does that
with the extracted fields.

Every answer is cached by a hash of (model, schema, instructions, input). Re-running the pipeline
on the same files therefore gives the same extraction, costs nothing, and works offline. Changing
the prompt or the schema changes the hash, so stale answers are never reused.
"""

import base64
import hashlib
import json
import logging
from pathlib import Path
from typing import Protocol, TypeVar

import anthropic
from pydantic import BaseModel

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class ExtractionFailed(Exception):
    """Claude could not produce a valid answer (refusal, truncated output, no API key...)."""


class Cache(Protocol):
    def get(self, key: str) -> str | None: ...
    def put(self, key: str, model: str, schema: str, value: str) -> None: ...


class MemoryCache:
    """Used in tests and when no database is configured."""

    def __init__(self) -> None:
        self.items: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.items.get(key)

    def put(self, key: str, model: str, schema: str, value: str) -> None:
        self.items[key] = value


def text_block(name: str, text: str) -> dict:
    return {"type": "text", "text": f'<document name="{name}">\n{text}\n</document>'}


def pdf_block(path: Path) -> dict:
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}}


class Extractor:
    def __init__(self, client: anthropic.Anthropic | None, model: str, cache: Cache):
        self.client = client
        self.model = model
        self.cache = cache

    def cache_key(self, schema: type[BaseModel], instructions: str, content: list[dict]) -> str:
        material = json.dumps(
            {
                "model": self.model,
                "schema": schema.model_json_schema(),
                "instructions": instructions,
                "content": content,
            },
            sort_keys=True,
        )
        return hashlib.sha256(material.encode()).hexdigest()

    def extract(self, schema: type[T], instructions: str, content: list[dict]) -> T:
        key = self.cache_key(schema, instructions, content)
        cached = self.cache.get(key)
        if cached is not None:
            return schema.model_validate_json(cached)

        if self.client is None:
            raise ExtractionFailed("ANTHROPIC_API_KEY is not set and this input is not in the cache")

        response = self.client.messages.parse(
            model=self.model,
            max_tokens=16000,
            output_config={"effort": "medium"},
            system=instructions,
            messages=[{"role": "user", "content": content}],
            output_format=schema,
        )
        if response.stop_reason != "end_turn" or response.parsed_output is None:
            raise ExtractionFailed(f"{schema.__name__}: stop_reason={response.stop_reason}")

        value = response.parsed_output.model_dump_json()
        self.cache.put(key, self.model, schema.__name__, value)
        log.info("Extracted %s (%s input tokens)", schema.__name__, response.usage.input_tokens)
        return response.parsed_output


def build_extractor(api_key: str | None, model: str, cache: Cache) -> Extractor:
    client = anthropic.Anthropic(api_key=api_key, max_retries=5) if api_key else None
    return Extractor(client, model, cache)
