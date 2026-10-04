from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from typing import Any, Literal, Mapping, Protocol

from openai import APIError, OpenAI

Provider = Literal["openai", "deepseek"]
DEFAULT_MODELS = {"openai": "gpt-5.6-luna", "deepseek": "deepseek-flash"}


class LLMError(Exception):
    pass


@dataclass(frozen=True)
class LLMRequest:
    instructions: str
    input: str
    schema: dict[str, Any]
    schema_name: str
    max_output_tokens: int


@dataclass(frozen=True)
class LLMConfig:
    provider: Provider
    model: str
    api_key: str = field(repr=False)
    timeout: float = 120.0
    max_retries: int = 2

    def __post_init__(self) -> None:
        if self.provider not in DEFAULT_MODELS:
            raise ValueError("LLM_PROVIDERはopenaiまたはdeepseekを指定してください。")
        if not self.model.strip():
            raise ValueError(f"{self.provider.upper()}_MODELは空にできません。")

    @classmethod
    def from_env(cls, environment: Mapping[str, str] | None = None) -> LLMConfig:
        environment = os.environ if environment is None else environment
        provider = environment.get("LLM_PROVIDER", "openai").strip().lower()
        if provider not in DEFAULT_MODELS:
            raise ValueError("LLM_PROVIDERはopenaiまたはdeepseekを指定してください。")
        prefix = provider.upper()
        return cls(
            provider=provider,
            model=environment.get(f"{prefix}_MODEL", DEFAULT_MODELS[provider]).strip(),
            api_key=environment.get(f"{prefix}_API_KEY", "").strip(),
        )

    def validate_credentials(self) -> None:
        if not self.api_key:
            raise ValueError(f"{self.provider.upper()}_API_KEYを設定してください。")


class JSONGenerator(Protocol):
    def generate_json(self, request: LLMRequest) -> str: ...


class OpenAIProvider:
    def __init__(self, client: OpenAI, model: str):
        self.client = client
        self.model = model

    def generate_json(self, request: LLMRequest) -> str:
        response = self.client.responses.create(
            model=self.model,
            instructions=request.instructions,
            input=[{"role": "user", "content": request.input}],
            text={"format": {"type": "json_schema", "name": request.schema_name,
                             "strict": True, "schema": request.schema}},
            max_output_tokens=request.max_output_tokens,
            store=False,
        )
        for item in response.output:
            if item.type == "message":
                if any(content.type == "refusal" for content in item.content):
                    raise LLMError("refusal")
        if response.status != "completed":
            raise LLMError(f"response_{response.status}")
        if not response.output_text:
            raise LLMError("missing_output")
        return response.output_text


class DeepSeekProvider:
    def __init__(self, client: OpenAI, model: str):
        self.client = client
        self.model = model

    def generate_json(self, request: LLMRequest) -> str:
        # JSONモードはスキーマを強制しないため、形状を指示文にも含める。
        instructions = request.instructions + "\n以下のJSON Schemaに従うJSONオブジェクトのみを返してください。\n" + json.dumps(
            request.schema, ensure_ascii=False)
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": instructions},
                      {"role": "user", "content": request.input}],
            response_format={"type": "json_object"},
            max_tokens=request.max_output_tokens,
            # deepseek-flashは思考モードが既定で、思考トークンがmax_tokensを使い切ってしまう。
            extra_body={"thinking": {"type": "disabled"}},
        )
        if not response.choices:
            raise LLMError("missing_output")
        choice = response.choices[0]
        if choice.message.refusal or choice.finish_reason == "content_filter":
            raise LLMError("refusal")
        if choice.finish_reason != "stop":
            raise LLMError(f"finish_reason_{choice.finish_reason}")
        if not choice.message.content or not choice.message.content.strip():
            raise LLMError("missing_output")
        return choice.message.content


class LLMClient:
    def __init__(self, config: LLMConfig):
        config.validate_credentials()
        options = {"api_key": config.api_key, "timeout": config.timeout,
                   "max_retries": config.max_retries}
        if config.provider == "deepseek":
            options["base_url"] = "https://api.deepseek.com"
        self.client = OpenAI(**options)
        provider_class = OpenAIProvider if config.provider == "openai" else DeepSeekProvider
        self.provider: JSONGenerator = provider_class(self.client, config.model)

    def generate_json(self, request: LLMRequest) -> str:
        try:
            return self.provider.generate_json(request)
        except APIError as exc:
            # SDKのエラー本文には認証情報や記事内容が含まれる可能性がある。
            raise LLMError(type(exc).__name__) from exc

    def __enter__(self) -> LLMClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.client.close()
