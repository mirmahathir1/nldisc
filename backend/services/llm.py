from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Generic, TypeVar

from pydantic import BaseModel

from backend.services.openai_cache import OpenAICache


T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    pass


class LLMRefusal(LLMError):
    pass


class LLMParseError(LLMError):
    pass


@dataclass(frozen=True)
class LLMResult(Generic[T]):
    parsed: T
    cache_key: str
    cache_hit: bool


Requester = Callable[..., BaseModel | dict[str, Any]]


class OpenAIResponsesLLM:
    def __init__(
        self,
        cache: OpenAICache,
        model: str,
        *,
        temperature: float = 0.0,
        requester: Requester | None = None,
        schema_version: str = "phase2-v1",
    ) -> None:
        self.cache = cache
        self.model = model
        self.temperature = temperature
        self.requester = requester
        self.schema_version = schema_version

    def parse_structured(
        self,
        *,
        datalake: str,
        task_type: str,
        instructions: str,
        input_payload: dict[str, Any],
        response_model: type[T],
        temperature: float | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> LLMResult[T]:
        temp = self.temperature if temperature is None else temperature
        payload = self._stable_payload(
            task_type=task_type,
            instructions=instructions,
            input_payload=input_payload,
            response_model=response_model,
            temperature=temp,
            parameters=parameters or {},
        )
        cache_key = self.cache.cache_key(payload)
        cached = self.cache.read(datalake, payload)
        if cached is not None:
            print(
                f"[LLM] cache HIT  datalake={datalake} task={task_type} "
                f"model={self.model} temperature={temp} cache_key={cache_key[:12]}",
                flush=True,
            )
            return LLMResult(
                parsed=response_model.model_validate(cached["parsed"]),
                cache_key=cache_key,
                cache_hit=True,
            )

        print(
            f"[LLM] cache MISS datalake={datalake} task={task_type} "
            f"model={self.model} temperature={temp} cache_key={cache_key[:12]} "
            f"-> calling OpenAI",
            flush=True,
        )
        parsed = self._request_structured(
            response_model=response_model,
            instructions=instructions,
            input_payload=input_payload,
            temperature=temp,
        )
        parsed_model = response_model.model_validate(parsed)
        self.cache.write(
            datalake,
            payload,
            parsed_model.model_dump(mode="json"),
            metadata={"task_type": task_type, "model": self.model},
        )
        print(
            f"[LLM] OpenAI response stored  datalake={datalake} task={task_type} "
            f"cache_key={cache_key[:12]}",
            flush=True,
        )
        return LLMResult(parsed=parsed_model, cache_key=cache_key, cache_hit=False)

    def _stable_payload(
        self,
        *,
        task_type: str,
        instructions: str,
        input_payload: dict[str, Any],
        response_model: type[BaseModel],
        temperature: float,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "task_type": task_type,
            "model": self.model,
            "temperature": temperature,
            "instructions": instructions,
            "input": input_payload,
            "response_schema": response_model.model_json_schema(),
            "parameters": parameters,
        }

    def _request_structured(
        self,
        *,
        response_model: type[T],
        instructions: str,
        input_payload: dict[str, Any],
        temperature: float,
    ) -> T | dict[str, Any]:
        if self.requester is not None:
            return self.requester(
                response_model=response_model,
                model=self.model,
                instructions=instructions,
                input_payload=input_payload,
                temperature=temperature,
            )

        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - dependency is installed in backend env
            raise LLMError("The openai package is not installed") from exc

        client = OpenAI()
        response = client.responses.parse(
            model=self.model,
            input=[
                {"role": "system", "content": instructions},
                {"role": "user", "content": json.dumps(input_payload, sort_keys=True)},
            ],
            text_format=response_model,
            temperature=temperature,
        )
        return self._extract_parsed(response, response_model)

    def _extract_parsed(self, response: Any, response_model: type[T]) -> T:
        for output in getattr(response, "output", []) or []:
            if getattr(output, "type", None) != "message":
                continue
            for item in getattr(output, "content", []) or []:
                if getattr(item, "type", None) == "refusal":
                    raise LLMRefusal(getattr(item, "refusal", "Model refused the request"))
                parsed = getattr(item, "parsed", None)
                if parsed is not None:
                    return response_model.model_validate(parsed)

        output_text = getattr(response, "output_text", None)
        if output_text:
            return response_model.model_validate_json(output_text)

        raise LLMParseError("No parsed structured output found in OpenAI response")

