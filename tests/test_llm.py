import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx2
from openai import OpenAI

from mg_update_calendar.extractor import main
from mg_update_calendar.llm import LLMClient, LLMConfig, LLMError, LLMRequest
from test_extractor import ARTICLE, entry, wire_extraction


REQUEST = LLMRequest("Extract data", "Article text", {"type": "object"}, "result", 8192)


def completion(content=None, finish_reason="stop", refusal=None, choices=True):
    return {
        "id": "chatcmpl_test", "object": "chat.completion", "created": 1,
        "model": "deepseek-flash",
        "choices": [{"index": 0, "finish_reason": finish_reason,
                     "message": {"role": "assistant", "content": content, "refusal": refusal}}] if choices else [],
    }


class LLMTests(unittest.TestCase):
    def test_provider_specific_configuration_and_defaults(self):
        config = LLMConfig.from_env({"OPENAI_API_KEY": "openai-secret"})
        self.assertEqual((config.provider, config.model, config.api_key),
                         ("openai", "gpt-5.6-luna", "openai-secret"))
        config = LLMConfig.from_env({"LLM_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": "deepseek-secret",
                                     "OPENAI_API_KEY": "openai-secret", "OPENAI_MODEL": "other"})
        self.assertEqual((config.model, config.api_key), ("deepseek-flash", "deepseek-secret"))
        self.assertNotIn("deepseek-secret", repr(config))
        self.assertEqual(LLMConfig.from_env({"LLM_PROVIDER": "deepseek", "DEEPSEEK_MODEL": "custom"}).model,
                         "custom")

    def test_invalid_configuration_and_wrong_provider_key(self):
        for environment in ({"LLM_PROVIDER": "unknown"}, {"LLM_PROVIDER": ""},
                            {"OPENAI_MODEL": " "}, {"LLM_PROVIDER": "deepseek", "DEEPSEEK_MODEL": ""}):
            with self.subTest(environment=environment), self.assertRaises(ValueError):
                LLMConfig.from_env(environment)
        with self.assertRaisesRegex(ValueError, "DEEPSEEK_API_KEY"):
            LLMConfig.from_env({"LLM_PROVIDER": "deepseek", "OPENAI_API_KEY": "wrong-key"}).validate_credentials()

    def run_deepseek(self, payload, status_code=200):
        self.requests = []
        def handler(request):
            self.requests.append(request)
            return httpx2.Response(status_code, json=payload)
        sdk = OpenAI(api_key="deepseek-test", base_url="https://api.deepseek.com", max_retries=0,
                     http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
        with patch("mg_update_calendar.llm.OpenAI", return_value=sdk) as factory:
            with LLMClient(LLMConfig("deepseek", "deepseek-flash", "deepseek-test")) as client:
                factory.assert_called_once_with(api_key="deepseek-test", timeout=120.0, max_retries=2,
                                                base_url="https://api.deepseek.com")
                result = client.generate_json(REQUEST)
        self.assertTrue(sdk.is_closed())
        return result

    def test_deepseek_json_request_and_response_through_sdk(self):
        self.assertEqual(self.run_deepseek(completion('{"ok":true}')), '{"ok":true}')
        request = self.requests[0]
        self.assertEqual(str(request.url), "https://api.deepseek.com/chat/completions")
        self.assertEqual(request.headers["authorization"], "Bearer deepseek-test")
        body = json.loads(request.content)
        self.assertEqual(body["model"], "deepseek-flash")
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(body["max_tokens"], 8192)
        self.assertEqual(body["thinking"], {"type": "disabled"})
        self.assertIn(json.dumps(REQUEST.schema), body["messages"][0]["content"])
        self.assertEqual(body["messages"][1]["content"], REQUEST.input)
        self.assertNotIn("deepseek-test", json.dumps(body))

    def test_deepseek_refusal_truncation_and_missing_output(self):
        cases = [(completion("{}", "length"), "finish_reason_length"),
                 (completion("{}", "content_filter"), "refusal"),
                 (completion(refusal="blocked"), "refusal"),
                 (completion(" "), "missing_output"), (completion(), "missing_output"),
                 (completion(choices=False), "missing_output")]
        for payload, error in cases:
            with self.subTest(error=error), self.assertRaisesRegex(LLMError, "^" + error + "$"):
                self.run_deepseek(payload)

    def test_api_error_is_sanitized(self):
        with self.assertRaises(LLMError) as error:
            self.run_deepseek({"error": {"message": "secret-content", "type": "authentication_error"}}, 401)
        self.assertEqual(str(error.exception), "AuthenticationError")

    def test_cli_deepseek_shared_validation_and_failure_continuation(self):
        payloads = iter([
            completion(json.dumps(wire_extraction({"entries": [entry()], "cancellations": [], "review_notes": []}))),
            *[completion(json.dumps(wire_extraction({"entries": [entry(start="2026-02-30")], "cancellations": [], "review_notes": []}))) for _ in range(3)],
            *[completion("invalid json") for _ in range(3)],
            completion(json.dumps(wire_extraction({"entries": [], "cancellations": [], "review_notes": []}))),
        ])
        sdk = OpenAI(api_key="deepseek-test", base_url="https://api.deepseek.com", max_retries=0,
                     http_client=httpx2.Client(transport=httpx2.MockTransport(
                         lambda request: httpx2.Response(200, json=next(payloads)))))
        with tempfile.TemporaryDirectory() as directory, contextlib.chdir(directory):
            Path("news_all.json").write_text(json.dumps([ARTICLE | {"url": f"https://example.com/news/{i}"} for i in range(4)]), encoding="utf-8")
            Path(".env").write_text("LLM_PROVIDER=deepseek\nDEEPSEEK_API_KEY=deepseek-test\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True), patch("mg_update_calendar.llm.OpenAI", return_value=sdk), \
                 patch("mg_update_calendar.extractor.CONCURRENCY", 1), \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main([]), 1)
            output = Path("entries.json").read_text(encoding="utf-8")
            data = json.loads(output)
            self.assertEqual((data["provider"], data["model"]), ("deepseek", "deepseek-flash"))
            self.assertEqual([item["status"] for item in data["articles"]],
                             ["extracted", "failed", "failed", "extracted"])
            self.assertEqual(data["articles"][1]["error"], "invalid_structured_output")
            self.assertEqual(data["articles"][0]["entries"][0]["calendar_start"], "2026-09-25")
            self.assertNotIn("deepseek-test", output)
        self.assertTrue(sdk.is_closed())

    def test_invalid_provider_or_missing_selected_key_preserves_output(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.chdir(directory):
            Path("news_all.json").write_text(json.dumps([ARTICLE]), encoding="utf-8")
            Path("entries.json").write_text("keep", encoding="utf-8")
            for environment in ({"LLM_PROVIDER": "deepseek", "OPENAI_API_KEY": "wrong-key"},
                                {"LLM_PROVIDER": "invalid"}):
                with patch.dict(os.environ, environment, clear=True), \
                     contextlib.redirect_stderr(io.StringIO()), patch("mg_update_calendar.llm.OpenAI") as factory:
                    if environment["LLM_PROVIDER"] == "invalid":
                        with self.assertRaises(SystemExit):
                            main([])
                    else:
                        self.assertEqual(main([]), 2)
                    factory.assert_not_called()
                self.assertEqual(Path("entries.json").read_text(encoding="utf-8"), "keep")
