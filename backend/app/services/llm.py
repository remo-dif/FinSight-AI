import json
from typing import Any

from openai import OpenAI

from app.core.config import settings


class LLMService:
    def __init__(self) -> None:
        self._client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
        self.model = settings.openai_model

    def synthesize_financial_answer(
        self,
        user_message: str,
        intent: str,
        tool_results: dict[str, Any],
        rag_chunks: list[dict[str, Any]] | None = None,
    ) -> str | None:
        if self._client is None:
            return None

        prompt = self._build_prompt(user_message, intent, tool_results, rag_chunks)
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a personal finance assistant. Answer user questions using only the provided "
                        "tool outputs and retrieved document excerpts. Do not hallucinate information. "
                        "Keep answers concise, factual, and grounded in the available data."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=450,
        )

        return self._extract_text(response)

    def _build_prompt(
        self,
        user_message: str,
        intent: str,
        tool_results: dict[str, Any],
        rag_chunks: list[dict[str, Any]] | None,
    ) -> str:
        tool_contents = json.dumps(tool_results, indent=2, default=str)
        rag_text = "No retrieved documents were available." if not rag_chunks else json.dumps(
            [
                {
                    "text": chunk.get("text"),
                    "source": chunk.get("metadata"),
                    "score": chunk.get("score"),
                }
                for chunk in rag_chunks
            ],
            indent=2,
            default=str,
        )

        return (
            "User message:\n"
            f"{user_message}\n\n"
            "Detected intent:\n"
            f"{intent}\n\n"
            "Tool outputs:\n"
            f"{tool_contents}\n\n"
            "Retrieved document excerpts:\n"
            f"{rag_text}\n\n"
            "Using only the information above, provide a single concise answer to the user. "
            "If the tool results do not support a direct answer, say that you need more information."
        )

    def _extract_text(self, response: Any) -> str:
        if hasattr(response, "output_text") and response.output_text:
            return response.output_text.strip()

        if hasattr(response, "choices") and response.choices:
            choice = response.choices[0]
            message = getattr(choice, "message", None)
            if message and isinstance(message, dict):
                return message.get("content", "").strip()
            if hasattr(choice, "message") and getattr(choice.message, "content", None):
                return choice.message.content.strip()

        output = getattr(response, "output", None)
        if isinstance(output, list):
            parts = []
            for item in output:
                if isinstance(item, dict):
                    for content in item.get("content", []):
                        if isinstance(content, dict) and content.get("type") == "output_text":
                            parts.append(content.get("text", ""))
            return " ".join(parts).strip()

        return str(response).strip()
