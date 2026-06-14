from __future__ import annotations

import sys
import json
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from chat_client import anthropic_payload, normalize_anthropic_response, resolve_provider_runtime
from manage_provider_registry import build_profile, normalize_base_url, validate_profile


class Args:
    provider = "openai-compatible"
    base_url = "127.0.0.1:8000"
    model = "test-model"
    api_key_env = "TEST_API_KEY"
    stage = ["translate", "qc"]
    note = []


class ProviderRegistryTests(unittest.TestCase):
    def test_normalize_host_port_to_v1(self) -> None:
        self.assertEqual(normalize_base_url("127.0.0.1:8000"), "http://127.0.0.1:8000/v1")

    def test_build_profile_does_not_include_api_key(self) -> None:
        profile = build_profile(Args())
        self.assertEqual(profile["api_key_env"], "TEST_API_KEY")
        self.assertNotIn("api_key", profile)

    def test_reject_plaintext_api_key(self) -> None:
        profile = build_profile(Args())
        profile["api_key"] = "secret"
        with self.assertRaises(ValueError):
            validate_profile(profile)


class ChatClientTests(unittest.TestCase):
    def test_anthropic_payload_strips_openai_only_fields(self) -> None:
        payload = {
            "model": "ignored",
            "messages": [
                {"role": "system", "content": "system text"},
                {"role": "user", "content": "hello"},
            ],
            "temperature": 0,
            "max_tokens": 8,
            "chat_template_kwargs": {"enable_thinking": False},
            "thinking_budget": 0,
        }
        converted = anthropic_payload(payload, "claude-test")
        self.assertEqual(converted["model"], "claude-test")
        self.assertEqual(converted["system"], "system text")
        self.assertEqual(converted["messages"], [{"role": "user", "content": "hello"}])
        self.assertNotIn("chat_template_kwargs", converted)
        self.assertNotIn("thinking_budget", converted)

    def test_anthropic_response_normalizes_to_openai_like_shape(self) -> None:
        normalized = normalize_anthropic_response(
            {
                "id": "msg_1",
                "model": "claude-test",
                "content": [{"type": "text", "text": "OK"}],
                "stop_reason": "end_turn",
            }
        )
        self.assertEqual(normalized["choices"][0]["message"]["content"], "OK")

    def test_provider_profile_overrides_local_default_base_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = Path(tmp) / "providers.json"
            registry.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "profiles": {
                            "deepseek": {
                                "provider": "openai-compatible",
                                "base_url": "https://api.deepseek.com/v1",
                                "default_model": "deepseek-v4-flash",
                                "api_key_env": "DEEPSEEK_TEST_KEY",
                                "stages": ["translate", "qc"],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            os.environ["DEEPSEEK_TEST_KEY"] = "dummy"
            args = type(
                "RuntimeArgs",
                (),
                {
                    "provider": "openai-compatible",
                    "provider_profile": "deepseek",
                    "provider_registry": str(registry),
                    "base_url": "http://127.0.0.1:8000/v1",
                    "model": "",
                    "api_key": "",
                },
            )()
            runtime = resolve_provider_runtime(args, stage="translate")
            self.assertEqual(runtime["base_url"], "https://api.deepseek.com/v1")
            self.assertEqual(runtime["model"], "deepseek-v4-flash")


if __name__ == "__main__":
    unittest.main()
