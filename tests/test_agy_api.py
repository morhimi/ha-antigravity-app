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

        # Create a mock agy CLI script that echoes its arguments as JSON or simulates slow/failing behavior
        self.mock_agy.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys, time\n"
            "args = sys.argv[1:]\n"
            "prompt = args[args.index('-p') + 1] if '-p' in args else ''\n"
            "if 'SIMULATE_TIMEOUT' in prompt:\n"
            "    time.sleep(5)\n"
            "if 'SIMULATE_FAIL' in prompt:\n"
            "    sys.stderr.write('simulated agy cli failure\\n')\n"
            "    sys.exit(2)\n"
            "print(json.dumps({'args': args, 'prompt': prompt}))\n",
            encoding="utf-8",
        )
        self.mock_agy.chmod(self.mock_agy.stat().st_mode | stat.S_IEXEC)

        os.environ["AGY_BIN"] = str(self.mock_agy)
        os.environ["AGY_WORKSPACE"] = str(self.temp_path)
        os.environ["AGY_DEFAULT_MODEL"] = "gemini-3.8-flash-low"
        os.environ["AGY_DEFAULT_TIMEOUT"] = "120"

        self.srv_mod = load_server_module()
        self.server = await asyncio.start_server(self.srv_mod.handle_client, "127.0.0.1", 0)
        sockets = self.server.sockets
        assert sockets
        self.port = sockets[0].getsockname()[1]
        self.base_url = f"http://127.0.0.1:{self.port}"

    async def asyncTearDown(self) -> None:
        self.server.close()
        await self.server.wait_closed()
        self.temp_dir.cleanup()

    async def _request(self, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
        def _sync_req() -> tuple[int, dict]:
            data = json.dumps(payload).encode("utf-8") if payload is not None else None
            headers = {"Content-Type": "application/json"} if payload is not None else {}
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
        self.assertEqual(derive("gemini-3.1-pro-high", None), "high")
        self.assertEqual(derive("gemini-3.1-pro-medium", None), "medium")
        self.assertEqual(derive("gemini-3.1-pro-max", None), "max")
        self.assertEqual(derive("gemini-3.8-flash-low", "HIGH"), "high")
        self.assertEqual(derive("custom-model", None), "low")

    async def test_health_endpoint(self) -> None:
        status, body = await self._request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["service"], "agy-api")
        self.assertEqual(body["default_model"], "gemini-3.8-flash-low")
        self.assertEqual(body["default_timeout"], 120)

    async def test_generate_default_model_and_files_list(self) -> None:
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
        inner = json.loads(body["response"])
        self.assertIn("--model", inner["args"])
        self.assertIn("gemini-3.8-flash-low", inner["args"])
        self.assertIn("--effort", inner["args"])
        self.assertIn("low", inner["args"])
        self.assertIn("--dangerously-skip-permissions", inner["args"])
        self.assertIn("- /media/clip1.mp4", inner["prompt"])
        self.assertIn("- /media/clip2.jpg", inner["prompt"])
        self.assertIn("Describe doorbell clip", inner["prompt"])

    async def test_vision_alias_and_string_file_fallback(self) -> None:
        status, body = await self._request(
            "POST",
            "/api/v1/vision",
            {
                "prompt": "Check snapshot",
                "files": "/media/single.jpg",
                "model": "gemini-3.1-pro-high",
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["model"], "gemini-3.1-pro-high")
        inner = json.loads(body["response"])
        self.assertIn("high", inner["args"])
        self.assertIn("- /media/single.jpg", inner["prompt"])

    async def test_missing_prompt_returns_400(self) -> None:
        status, body = await self._request("POST", "/api/generate", {"prompt": "   "})
        self.assertEqual(status, 400)
        self.assertEqual(body["status"], "error")
        self.assertIn("Missing 'prompt'", body["message"])

    async def test_unknown_route_returns_404(self) -> None:
        status, body = await self._request("GET", "/api/unknown")
        self.assertEqual(status, 404)
        self.assertEqual(body["status"], "error")

    async def test_timeout_enforcement_kills_process(self) -> None:
        status, body = await self._request(
            "POST",
            "/api/generate",
            {"prompt": "SIMULATE_TIMEOUT", "timeout": 1},
        )
        self.assertEqual(status, 500)
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


if __name__ == "__main__":
    unittest.main()
