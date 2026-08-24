from __future__ import annotations

import os

from dotenv import load_dotenv
from openai import OpenAI


class OpenAIEmbedder:
    def __init__(self, model: str):
        load_dotenv()
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is not set. Add it to .env or the environment.")
        self.model = model
        self.client = OpenAI()

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self.client.embeddings.create(model=self.model, input=texts)
        return [item.embedding for item in response.data]

