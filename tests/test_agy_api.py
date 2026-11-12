#!/usr/bin/env python3
"""
Unit and HTTP integration tests for antigravity/rootfs/usr/local/bin/agy-api-server.py.
Runs entirely using the Python standard library (unittest + asyncio + urllib).
"""

import asyncio
import importlib.util
import json
import os
import stat
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_SCRIPT = REPO_ROOT / "antigravity" / "rootfs" / "usr" / "local" / "bin" / "agy-api-server.py"


def load_server_module():
    spec = importlib.util.spec_from_file_location("agy_api_server", SERVER_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestAgyApiServer(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.mock_agy = self.temp_path / "mock-agy"

        # Create a mock agy CLI script that returns --output-format json structure
        # or simulates prefix noise / concurrency tracking / raw text fallback / slow timeout / failure
        self.mock_agy.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, pathlib, sys, time\n"
            "args = sys.argv[1:]\n"
            "prompt = args[args.index('-p') + 1] if '-p' in args else ''\n"
            "if 'SIMULATE_TIMEOUT' in prompt:\n"
            "    time.sleep(5)\n"
            "if 'SIMULATE_FAIL' in prompt:\n"
            "    sys.stderr.write('simulated agy cli failure\\n')\n"
            "    sys.exit(2)\n"
            "if 'SIMULATE_RAW_TEXT' in prompt:\n"
            "    print('raw non-json cli output')\n"
            "    sys.exit(0)\n"
            "if 'SIMULATE_PREFIX_NOISE' in prompt:\n"
            "    print('Warning: experimental flag enabled')\n"
            "    print(json.dumps({'response': 'clean response after banner', 'usage': {'tokens': 7}}))\n"
            "    sys.exit(0)\n"
            "if 'SIMULATE_CONCURRENCY' in prompt:\n"
            "    active_dir = pathlib.Path(os.environ['AGY_WORKSPACE']) / 'active_procs'\n"
            "    active_dir.mkdir(exist_ok=True)\n"
            "    marker = active_dir / str(os.getpid())\n"
            "    marker.write_text('1')\n"
            "    time.sleep(0.15)\n"
            "    current_active = len(list(active_dir.iterdir()))\n"
            "    time.sleep(0.15)\n"
            "    marker.unlink(missing_ok=True)\n"
            "    print(json.dumps({'response': str(current_active)}))\n"
            "    sys.exit(0)\n"
            "print(json.dumps({\n"
            "    'response': json.dumps({'args': args, 'prompt': prompt}),\n"
            "    'usage': {'input_tokens': 120, 'output_tokens': 45}\n"
            "}))\n",
            encoding="utf-8",
        )
        self.mock_agy.chmod(self.mock_agy.stat().st_mode | stat.S_IEXEC)

        os.environ["AGY_BIN"] = str(self.mock_agy)
        os.environ["AGY_WORKSPACE"] = str(self.temp_path)
        os.environ["AGY_DEFAULT_MODEL"] = "gemini-3.8-flash-low"
        os.environ["AGY_DEFAULT_TIMEOUT"] = "120"

        self.srv_mod = load_server_module()
        self.handler = self.srv_mod.AgyApiServer()
        self.server = await asyncio.start_server(self.handler.handle_client, "127.0.0.1", 0)
        sockets = self.server.sockets
        assert sockets
        self.port = sockets[0].getsockname()[1]
        self.base_url = f"http://127.0.0.1:{self.port}"

    async def asyncTearDown(self) -> None:
        self.server.close()
        await self.server.wait_closed()
        self.temp_dir.cleanup()

    async def _request(self, method: str, path: str, payload: dict | list | str | None = None) -> tuple[int, dict]:
        def _sync_req() -> tuple[int, dict]:
            if isinstance(payload, str):
                data = payload.encode("utf-8")
                headers = {"Content-Type": "application/json"}
            elif payload is not None:
                data = json.dumps(payload).encode("utf-8")
                headers = {"Content-Type": "application/json"}
            else:
                data = None
                headers = {}
            req = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    return resp.status, json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as err:
                try:
                    return err.code, json.loads(err.read().decode("utf-8"))
                finally:
                    err.close()

        return await asyncio.to_thread(_sync_req)

    def test_derive_effort_levels(self) -> None:
        derive = self.srv_mod._derive_effort
        self.assertEqual(derive("gemini-3.8-flash-low", None), "low")
        self.assertEqual(derive("gemini-4-argon-high", None), "high")
        self.assertEqual(derive("gemini-4-argon-medium", None), "medium")
        self.assertEqual(derive("gemini-4-argon-max", None), "max")
        self.assertEqual(derive("gemini-3.8-flash-low", "HIGH"), "high")
        self.assertEqual(derive("custom-model", None), "low")

    async def test_health_endpoint(self) -> None:
        status, body = await self._request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["service"], "agy-api")
        self.assertEqual(body["default_model"], "gemini-3.8-flash-low")
        self.assertEqual(body["default_timeout"], 120)

    async def test_generate_json_extraction_usage_and_multimodal_directive(self) -> None:
        status, body = await self._request(
            "POST",
            "/api/generate",
            {
                "prompt": "Describe doorbell clip",
                "files": ["/media/clip1.mp4", "/media/clip2.jpg"],
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["model"], "gemini-3.8-flash-low")
        self.assertEqual(body["usage"], {"input_tokens": 120, "output_tokens": 45})
        inner = json.loads(body["response"])
        self.assertIn("--model", inner["args"])
        self.assertIn("gemini-3.8-flash-low", inner["args"])
        self.assertIn("--effort", inner["args"])
        self.assertIn("low", inner["args"])
        self.assertIn("--dangerously-skip-permissions", inner["args"])
        self.assertIn("--output-format", inner["args"])
        self.assertIn("json", inner["args"])
        self.assertIn("- /media/clip1.mp4", inner["prompt"])
        self.assertIn("- /media/clip2.jpg", inner["prompt"])
        self.assertIn("Analyze the attached media files directly using native multimodal vision", inner["prompt"])
        self.assertIn("Describe doorbell clip", inner["prompt"])

    async def test_text_only_prompt_omits_multimodal_directive(self) -> None:
        status, body = await self._request(
            "POST",
            "/api/generate",
            {
                "prompt": "Summarize current energy usage",
                "files": ["", "   "],
            },
        )
        self.assertEqual(status, 200)
        inner = json.loads(body["response"])
        self.assertEqual(inner["prompt"], "Summarize current energy usage")
        self.assertNotIn("Attached media files", inner["prompt"])

    async def test_vision_alias_and_string_file_fallback(self) -> None:
        status, body = await self._request(
            "POST",
            "/api/v1/vision",
            {
                "prompt": "Check snapshot",
                "files": "/media/single.jpg",
                "model": "gemini-4-argon-high",
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["model"], "gemini-4-argon-high")
        inner = json.loads(body["response"])
        self.assertIn("high", inner["args"])
        self.assertIn("- /media/single.jpg", inner["prompt"])

    async def test_prefix_banner_noise_before_json_is_stripped(self) -> None:
        status, body = await self._request(
            "POST",
            "/api/generate",
            {"prompt": "SIMULATE_PREFIX_NOISE"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["response"], "clean response after banner")
        self.assertEqual(body["usage"], {"tokens": 7})

    async def test_raw_text_fallback_when_cli_not_json(self) -> None:
        status, body = await self._request(
            "POST",
            "/api/generate",
            {"prompt": "SIMULATE_RAW_TEXT"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["response"], "raw non-json cli output")
        self.assertNotIn("usage", body)

    async def test_invalid_json_or_non_dict_returns_400(self) -> None:
        status, body = await self._request("POST", "/api/generate", "{not-valid-json")
        self.assertEqual(status, 400)
        self.assertEqual(body["status"], "error")
        self.assertIn("Invalid JSON payload", body["message"])

        status2, body2 = await self._request("POST", "/api/generate", ["a", "list"])
        self.assertEqual(status2, 400)
        self.assertIn("must be an object", body2["message"])

    async def test_invalid_timeout_returns_400(self) -> None:
        status, body = await self._request("POST", "/api/generate", {"prompt": "Hello", "timeout": "abc"})
        self.assertEqual(status, 400)
        self.assertIn("Invalid 'timeout'", body["message"])

        status2, body2 = await self._request("POST", "/api/generate", {"prompt": "Hello", "timeout": -10})
        self.assertEqual(status2, 400)
        self.assertIn("Invalid 'timeout'", body2["message"])

    async def test_missing_prompt_returns_400(self) -> None:
        status, body = await self._request("POST", "/api/generate", {"prompt": "   "})
        self.assertEqual(status, 400)
        self.assertEqual(body["status"], "error")
        self.assertIn("Missing 'prompt'", body["message"])

    async def test_unknown_route_returns_404(self) -> None:
        status, body = await self._request("GET", "/api/unknown")
        self.assertEqual(status, 404)
        self.assertEqual(body["status"], "error")
        self.assertIn("/api/unknown", body["message"])

    async def test_timeout_enforcement_returns_504_and_kills_process(self) -> None:
        status, body = await self._request(
            "POST",
            "/api/generate",
            {"prompt": "SIMULATE_TIMEOUT", "timeout": 1},
        )
        self.assertEqual(status, 504)
        self.assertEqual(body["status"], "error")
        self.assertIn("timed out after 1 seconds", body["message"])

    async def test_nonzero_exit_code_returns_500(self) -> None:
        status, body = await self._request(
            "POST",
            "/api/generate",
            {"prompt": "SIMULATE_FAIL"},
        )
        self.assertEqual(status, 500)
        self.assertEqual(body["status"], "error")
        self.assertIn("simulated agy cli failure", body["message"])

    async def test_semaphore_limits_concurrency_to_two(self) -> None:
        results = await asyncio.gather(
            self._request("POST", "/api/generate", {"prompt": "SIMULATE_CONCURRENCY"}),
            self._request("POST", "/api/generate", {"prompt": "SIMULATE_CONCURRENCY"}),
            self._request("POST", "/api/generate", {"prompt": "SIMULATE_CONCURRENCY"}),
            self._request("POST", "/api/generate", {"prompt": "SIMULATE_CONCURRENCY"}),
        )
        for status, body in results:
            self.assertEqual(status, 200)
            active_count = int(body["response"])
            self.assertLessEqual(active_count, 2)


if __name__ == "__main__":
    unittest.main()
