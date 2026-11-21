"""
Unit and HTTP integration tests for antigravity/rootfs/usr/local/bin/agy-api-server.py.
Runs entirely using the Python standard library (unittest + asyncio + urllib).
"""

import asyncio
import importlib.util
import json
import os
import sqlite3
import stat
import tempfile
import unittest
import urllib.error
import urllib.request
import uuid
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
        self.media_dir = self.temp_path / "media"
        self.media_dir.mkdir()
        self.cli_data_dir = self.temp_path / "cli_data"
        self.cli_data_dir.mkdir()
        self.state_file = self.cli_data_dir / "antigravity_state.pbtxt"
        self.mock_agy = self.temp_path / "mock-agy"

        self.received_events: list[tuple[str, str, dict]] = []
        self.event_received = asyncio.Event()

        # Mock Home Assistant Supervisor event sink for async callback testing
        async def _handle_ha_event(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            req_line = (await reader.readline()).decode("utf-8", errors="replace").strip()
            path = req_line.split()[1] if len(req_line.split()) >= 2 else ""
            headers: dict[str, str] = {}
            while True:
                hline = await reader.readline()
                if hline in (b"\r\n", b"\n", b""):
                    break
                if b":" in hline:
                    k, v = hline.decode("utf-8", errors="replace").split(":", 1)
                    headers[k.strip().lower()] = v.strip()
            length = int(headers.get("content-length", "0"))
            raw_body = await reader.readexactly(length) if length > 0 else b"{}"
            self.received_events.append((path, headers.get("authorization", ""), json.loads(raw_body.decode())))
            self.event_received.set()
            resp_body = b'{"message":"Event fired."}'
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                + f"Content-Length: {len(resp_body)}\r\nConnection: close\r\n\r\n".encode()
                + resp_body
            )
            await writer.drain()
            writer.close()

        self.ha_server = await asyncio.start_server(_handle_ha_event, "127.0.0.1", 0)
        ha_port = self.ha_server.sockets[0].getsockname()[1]

        self.mock_agy.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, pathlib, sys, time\n"
            "args = sys.argv[1:]\n"
            "if args == ['--version']:\n"
            "    print('1.5.7')\n"
            "    sys.exit(0)\n"
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
            "if 'SIMULATE_STRUCTURED_FALLBACK' in prompt:\n"
            "    print(json.dumps({'response': json.dumps({'person_detected': True})}))\n"
            "    sys.exit(0)\n"
            "if 'SIMULATE_EPHEMERAL_ARTIFACTS' in prompt:\n"
            "    import sqlite3, uuid\n"
            "    cid = args[args.index('--conversation') + 1] if '--conversation' in args else str(uuid.uuid4())\n"
            "    base = pathlib.Path(os.environ['AGY_CLI_DATA_DIR'])\n"
            "    for sub in ('conversations', 'brain', 'annotations'):\n"
            "        (base / sub).mkdir(parents=True, exist_ok=True)\n"
            "    for suf in ('.db', '.db-wal', '.db-shm'):\n"
            "        (base / 'conversations' / f'{cid}{suf}').write_text('data')\n"
            "    (base / 'brain' / cid).mkdir(parents=True, exist_ok=True)\n"
            "    (base / 'brain' / cid / 'notes.md').write_text('artifact')\n"
            "    (base / 'annotations' / f'{cid}.pbtxt').write_text('ann')\n"
            "    conn = sqlite3.connect(str(base / 'conversation_summaries.db'))\n"
            "    conn.execute('CREATE TABLE IF NOT EXISTS conversation_summaries (conversation_id TEXT, title TEXT)')\n"
            "    conn.execute('CREATE TABLE IF NOT EXISTS conversations_fts (conversation_id TEXT, body TEXT)')\n"
            "    conn.execute(\n"
            "        'CREATE TABLE IF NOT EXISTS conversation_parents (conversation_id TEXT, parent_id TEXT)'\n"
            "    )\n"
            "    conn.execute('INSERT INTO conversation_summaries VALUES (?, ?)', (cid, 'title'))\n"
            "    conn.execute('INSERT INTO conversations_fts VALUES (?, ?)', (cid, 'body'))\n"
            "    conn.execute('INSERT INTO conversation_parents VALUES (?, ?)', (cid, ''))\n"
            "    conn.commit()\n"
            "    conn.close()\n"
            "    print(json.dumps({'conversation_id': cid, 'response': 'artifact-ok'}))\n"
            "    sys.exit(0)\n"
            "payload = {\n"
            "    'conversation_id': 'conv-test-123',\n"
            "    'response': json.dumps({'args': args, 'prompt': prompt}),\n"
            "    'usage': {'input_tokens': 120, 'output_tokens': 45},\n"
            "}\n"
            "if '--json-schema' in args:\n"
            "    payload['structured_output'] = {'person_detected': True, 'count': 2}\n"
            "print(json.dumps(payload))\n",
            encoding="utf-8",
        )
        self.mock_agy.chmod(self.mock_agy.stat().st_mode | stat.S_IEXEC)

        os.environ["AGY_BIN"] = str(self.mock_agy)
        os.environ["AGY_WORKSPACE"] = str(self.temp_path)
        os.environ["AGY_MEDIA_DIR"] = str(self.media_dir)
        os.environ["AGY_STATE_FILE"] = str(self.state_file)
        os.environ["AGY_CLI_DATA_DIR"] = str(self.cli_data_dir)
        os.environ["AGY_DEFAULT_EPHEMERAL"] = "true"
        os.environ["AGY_HA_API_URL"] = f"http://127.0.0.1:{ha_port}/api"
        os.environ["SUPERVISOR_TOKEN"] = "test-supervisor-token"
        os.environ.pop("GEMINI_API_KEY", None)
        os.environ["AGY_DEFAULT_MODEL"] = "gemini-4-hydrogen-low"
        os.environ["AGY_DEFAULT_TIMEOUT"] = "180"
        os.environ["AGY_MAX_BODY_BYTES"] = "2048"
        os.environ["AGY_HTTP_READ_TIMEOUT"] = "1.0"

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
        self.ha_server.close()
        await self.ha_server.wait_closed()
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

    async def _raw_http(self, raw_bytes: bytes, close_writer_early: bool = True) -> tuple[int, dict]:
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        writer.write(raw_bytes)
        await writer.drain()
        if close_writer_early and writer.can_write_eof():
            writer.write_eof()
        response_bytes = await reader.read()
        writer.close()
        await writer.wait_closed()
        header_part, body_part = response_bytes.split(b"\r\n\r\n", 1)
        status_code = int(header_part.splitlines()[0].split()[1])
        return status_code, json.loads(body_part.decode("utf-8"))

    def test_derive_effort_levels(self) -> None:
        derive = self.srv_mod._derive_effort
        self.assertEqual(derive("gemini-4-hydrogen-low", None), "low")
        self.assertEqual(derive("gemini-4-hydrogen-xhigh", None), "xhigh")
        self.assertEqual(derive("gemini-4-argon-high", None), "high")
        self.assertEqual(derive("gemini-4-argon-medium", None), "medium")
        self.assertEqual(derive("gemini-4-argon-max", None), "max")
        self.assertEqual(derive("gemini-4-hydrogen-low", "HIGH"), "high")
        self.assertEqual(derive("custom-model", None), "low")

    async def test_health_endpoint_auth_state_and_version(self) -> None:
        status, body = await self._request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["service"], "agy-api")
        self.assertEqual(body["default_model"], "gemini-4-hydrogen-low")
        self.assertEqual(body["default_timeout"], 180)
        self.assertTrue(body["default_ephemeral"])
        self.assertFalse(body["authenticated"])
        self.assertEqual(body["agy_version"], "1.5.7")

        self.state_file.write_text("signed-in", encoding="utf-8")
        status2, body2 = await self._request("GET", "/health")
        self.assertEqual(status2, 200)
        self.assertTrue(body2["authenticated"])

    async def test_generate_json_extraction_usage_conversation_and_multimodal_directive(self) -> None:
        status, body = await self._request(
            "POST",
            "/api/generate",
            {
                "prompt": "Describe doorbell clip",
                "files": ["/media/clip1.mp4", "/media/clip2.jpg"],
                "conversation_id": "prev-conv-42",
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["model"], "gemini-4-hydrogen-low")
        self.assertEqual(body["conversation_id"], "conv-test-123")
        self.assertEqual(body["usage"], {"input_tokens": 120, "output_tokens": 45})
        inner = json.loads(body["response"])
        self.assertIn("--model", inner["args"])
        self.assertIn("gemini-4-hydrogen-low", inner["args"])
        self.assertIn("--effort", inner["args"])
        self.assertIn("low", inner["args"])
        self.assertIn("--dangerously-skip-permissions", inner["args"])
        self.assertIn("--output-format", inner["args"])
        self.assertIn("json", inner["args"])
        self.assertIn("--add-dir", inner["args"])
        self.assertIn(str(self.media_dir), inner["args"])
        self.assertIn("--conversation", inner["args"])
        self.assertIn("prev-conv-42", inner["args"])
        self.assertIn("- /media/clip1.mp4", inner["prompt"])
        self.assertIn("- /media/clip2.jpg", inner["prompt"])
        self.assertIn("Analyze the attached media files directly using native multimodal vision", inner["prompt"])
        self.assertIn("Describe doorbell clip", inner["prompt"])

    async def test_structured_json_schema_and_fallback(self) -> None:
        schema = {
            "type": "object",
            "properties": {"person_detected": {"type": "boolean"}},
            "required": ["person_detected"],
        }
        status, body = await self._request(
            "POST",
            "/api/generate",
            {"prompt": "Analyze motion", "json_schema": schema},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["structured"], {"person_detected": True, "count": 2})
        inner = json.loads(body["response"])
        self.assertIn("--json-schema", inner["args"])

        # Fallback when CLI omits structured_output field and encodes JSON in response
        status2, body2 = await self._request(
            "POST",
            "/api/generate",
            {"prompt": "SIMULATE_STRUCTURED_FALLBACK", "json_schema": json.dumps(schema)},
        )
        self.assertEqual(status2, 200)
        self.assertEqual(body2["structured"], {"person_detected": True})

        # Invalid schema -> 400
        status3, body3 = await self._request(
            "POST",
            "/api/generate",
            {"prompt": "Test", "json_schema": "{bad-json"},
        )
        self.assertEqual(status3, 400)
        self.assertIn("Invalid 'json_schema'", body3["message"])

    async def test_async_mode_returns_202_and_fires_ha_event(self) -> None:
        status, body = await self._request(
            "POST",
            "/api/generate",
            {
                "prompt": "Analyze backyard clip",
                "async": True,
                "event_type": "agy_camera_done",
                "request_id": "req-abc-1",
                "metadata": {"camera": "backyard"},
            },
        )
        self.assertEqual(status, 202)
        self.assertEqual(body["status"], "accepted")
        self.assertTrue(body["async"])
        self.assertEqual(body["event_type"], "agy_camera_done")
        self.assertEqual(body["request_id"], "req-abc-1")

        await asyncio.wait_for(self.event_received.wait(), timeout=5)
        self.assertEqual(len(self.received_events), 1)
        ev_path, ev_auth, ev_body = self.received_events[0]
        self.assertEqual(ev_path, "/api/events/agy_camera_done")
        self.assertEqual(ev_auth, "Bearer test-supervisor-token")
        self.assertEqual(ev_body["status"], "success")
        self.assertEqual(ev_body["request_id"], "req-abc-1")
        self.assertEqual(ev_body["metadata"], {"camera": "backyard"})
        self.assertTrue(ev_body["ephemeral"])
        self.assertNotIn("conversation_id", ev_body)

        # Async with ephemeral=False preserves conversation_id
        self.event_received.clear()
        status_persist, body_persist = await self._request(
            "POST",
            "/api/generate",
            {
                "prompt": "Analyze backyard clip persistent",
                "async": True,
                "ephemeral": False,
                "event_type": "agy_camera_done",
                "request_id": "req-abc-2",
            },
        )
        self.assertEqual(status_persist, 202)
        self.assertFalse(body_persist["ephemeral"])
        await asyncio.wait_for(self.event_received.wait(), timeout=5)
        self.assertEqual(self.received_events[1][2]["conversation_id"], "conv-test-123")
        self.assertNotIn("ephemeral", self.received_events[1][2])

        # Unsafe event_type rejected with 400
        status_bad, body_bad = await self._request(
            "POST",
            "/api/generate",
            {"prompt": "Test", "async": True, "event_type": "../services/restart"},
        )
        self.assertEqual(status_bad, 400)
        self.assertIn("Invalid 'event_type'", body_bad["message"])

    async def test_text_only_prompt_omits_multimodal_directive_and_add_dir(self) -> None:
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
        self.assertNotIn("--add-dir", inner["args"])

    async def test_vision_alias_explicit_effort_and_string_file_fallback(self) -> None:
        status, body = await self._request(
            "POST",
            "/api/v1/vision",
            {
                "prompt": "Check snapshot",
                "files": "/media/single.jpg",
                "model": "gemini-4-argon-high",
                "effort": "xhigh",
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["model"], "gemini-4-argon-high")
        inner = json.loads(body["response"])
        self.assertIn("xhigh", inner["args"])
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

    async def test_http_content_length_and_timeout_guards(self) -> None:
        status, body = await self._raw_http(
            b"POST /api/generate HTTP/1.1\r\nHost: localhost\r\nContent-Length: nope\r\n\r\n"
        )
        self.assertEqual(status, 400)
        self.assertIn("Invalid Content-Length", body["message"])

        status, body = await self._raw_http(
            b"POST /api/generate HTTP/1.1\r\nHost: localhost\r\nContent-Length: -5\r\n\r\n"
        )
        self.assertEqual(status, 400)
        self.assertIn("Negative Content-Length", body["message"])

        status, body = await self._raw_http(
            b"POST /api/generate HTTP/1.1\r\nHost: localhost\r\nContent-Length: 99999\r\n\r\n"
        )
        self.assertEqual(status, 413)
        self.assertIn("exceeds maximum allowed size", body["message"])

        status, body = await self._raw_http(
            b'POST /api/generate HTTP/1.1\r\nHost: localhost\r\nContent-Length: 50\r\n\r\n{"prompt":"hi"',
            close_writer_early=True,
        )
        self.assertEqual(status, 400)
        self.assertIn("Incomplete request body", body["message"])

        status, body = await self._raw_http(
            b"POST /api/generate HTTP/1.1\r\nHost: localhost\r\n",
            close_writer_early=False,
        )
        self.assertEqual(status, 408)
        self.assertIn("Timed out reading", body["message"])

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

    def _seed_conversation(self, cid: str, create_db: bool = True, create_annotation: bool = True) -> None:
        for sub in ("conversations", "brain", "annotations"):
            (self.cli_data_dir / sub).mkdir(parents=True, exist_ok=True)
        if create_db:
            for suf in (".db", ".db-wal", ".db-shm"):
                (self.cli_data_dir / "conversations" / f"{cid}{suf}").write_text("db", encoding="utf-8")
            (self.cli_data_dir / "brain" / cid).mkdir(parents=True, exist_ok=True)
            (self.cli_data_dir / "brain" / cid / "plan.md").write_text("plan", encoding="utf-8")
        if create_annotation:
            (self.cli_data_dir / "annotations" / f"{cid}.pbtxt").write_text("ann", encoding="utf-8")
        conn = sqlite3.connect(str(self.cli_data_dir / "conversation_summaries.db"))
        conn.execute("CREATE TABLE IF NOT EXISTS conversation_summaries (conversation_id TEXT, title TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS conversations_fts (conversation_id TEXT, body TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS conversation_parents (conversation_id TEXT, parent_id TEXT)")
        conn.execute("INSERT INTO conversation_summaries VALUES (?, ?)", (cid, f"title-{cid}"))
        conn.execute("INSERT INTO conversations_fts VALUES (?, ?)", (cid, f"body-{cid}"))
        conn.execute("INSERT INTO conversation_parents VALUES (?, ?)", (cid, ""))
        conn.commit()
        conn.close()

    def _summary_ids(self, table: str) -> set[str]:
        conn = sqlite3.connect(str(self.cli_data_dir / "conversation_summaries.db"))
        try:
            return {row[0] for row in conn.execute(f"SELECT conversation_id FROM {table}").fetchall()}
        finally:
            conn.close()

    async def test_ephemeral_cleanup_removes_files_and_sqlite_rows_for_sync_and_vision(self) -> None:
        keep_cid = str(uuid.uuid4())
        self._seed_conversation(keep_cid)

        for route in ("/api/generate", "/api/v1/vision"):
            status, body = await self._request(
                "POST",
                route,
                {"prompt": "SIMULATE_EPHEMERAL_ARTIFACTS"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(body["response"], "artifact-ok")
            self.assertTrue(body["ephemeral"])
            self.assertNotIn("conversation_id", body)

        # Only the pre-existing interactive conversation should remain
        remaining_dbs = sorted(p.name for p in (self.cli_data_dir / "conversations").iterdir())
        self.assertEqual(remaining_dbs, [f"{keep_cid}.db", f"{keep_cid}.db-shm", f"{keep_cid}.db-wal"])
        self.assertEqual([p.name for p in (self.cli_data_dir / "brain").iterdir()], [keep_cid])
        self.assertEqual([p.name for p in (self.cli_data_dir / "annotations").iterdir()], [f"{keep_cid}.pbtxt"])
        for table in ("conversation_summaries", "conversations_fts", "conversation_parents"):
            self.assertEqual(self._summary_ids(table), {keep_cid})

    async def test_ephemeral_guard_and_validation(self) -> None:
        # 1. Explicit conversation_id is NEVER treated as ephemeral even when ephemeral=True
        resumed_cid = str(uuid.uuid4())
        status, body = await self._request(
            "POST",
            "/api/generate",
            {"prompt": "SIMULATE_EPHEMERAL_ARTIFACTS", "conversation_id": resumed_cid, "ephemeral": True},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["conversation_id"], resumed_cid)
        self.assertNotIn("ephemeral", body)
        self.assertTrue((self.cli_data_dir / "conversations" / f"{resumed_cid}.db").exists())
        self.assertIn(resumed_cid, self._summary_ids("conversation_summaries"))

        # 2. Explicit ephemeral=False persists a new conversation and returns conversation_id
        status2, body2 = await self._request(
            "POST",
            "/api/generate",
            {"prompt": "SIMULATE_EPHEMERAL_ARTIFACTS", "ephemeral": "false"},
        )
        self.assertEqual(status2, 200)
        new_cid = body2["conversation_id"]
        self.assertNotIn("ephemeral", body2)
        self.assertTrue((self.cli_data_dir / "conversations" / f"{new_cid}.db").exists())

        # 3. Invalid ephemeral value -> 400
        status3, body3 = await self._request(
            "POST",
            "/api/generate",
            {"prompt": "Hello", "ephemeral": "maybe"},
        )
        self.assertEqual(status3, 400)
        self.assertIn("Invalid 'ephemeral'", body3["message"])

        # 4. Non-UUID / path traversal IDs are rejected by cleanup helper
        self.assertFalse(self.srv_mod._cleanup_ephemeral_conversation_sync("../escape", str(self.cli_data_dir)))
        self.assertFalse(self.srv_mod._cleanup_ephemeral_conversation_sync("conv-test-123", str(self.cli_data_dir)))

    async def test_cleanup_orphans_endpoint_prunes_ghost_summaries_and_annotations(self) -> None:
        live_cid = str(uuid.uuid4())
        ghost_cid_1 = str(uuid.uuid4())
        ghost_cid_2 = str(uuid.uuid4())
        self._seed_conversation(live_cid, create_db=True, create_annotation=True)
        self._seed_conversation(ghost_cid_1, create_db=False, create_annotation=True)
        self._seed_conversation(ghost_cid_2, create_db=False, create_annotation=False)

        status, body = await self._request("POST", "/api/cleanup-orphans")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["orphaned_conversations"], 2)
        self.assertEqual(body["removed_rows"], 6)
        self.assertEqual(body["removed_annotations"], 1)

        self.assertTrue((self.cli_data_dir / "conversations" / f"{live_cid}.db").exists())
        self.assertTrue((self.cli_data_dir / "annotations" / f"{live_cid}.pbtxt").exists())
        self.assertFalse((self.cli_data_dir / "annotations" / f"{ghost_cid_1}.pbtxt").exists())
        for table in ("conversation_summaries", "conversations_fts", "conversation_parents"):
            self.assertEqual(self._summary_ids(table), {live_cid})

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
