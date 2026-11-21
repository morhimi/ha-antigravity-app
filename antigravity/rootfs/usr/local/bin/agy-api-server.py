#!/usr/bin/env python3
"""
Antigravity Local REST API Server (agy-api) for Home Assistant.
Supervised by S6-overlay to provide asynchronous local LLM inference over HTTP.
"""

import asyncio
import json
import logging
import os
import re
import shutil
import sqlite3
import time
import urllib.error
import urllib.request
import uuid

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("agy-api")


def _parse_bool_flag(raw: object, default: bool = False) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        val = raw.strip().lower()
        if val in ("true", "1", "yes", "on"):
            return True
        if val in ("false", "0", "no", "off"):
            return False
    raise ValueError(f"Invalid boolean value: {raw!r}")


PORT = int(os.environ.get("AGY_API_PORT", "8120"))
DEFAULT_MODEL = os.environ.get("AGY_DEFAULT_MODEL", "gemini-4-hydrogen-low")
DEFAULT_TIMEOUT = int(os.environ.get("AGY_DEFAULT_TIMEOUT", "120"))
DEFAULT_EPHEMERAL = _parse_bool_flag(os.environ.get("AGY_DEFAULT_EPHEMERAL", "true"), default=True)
WORKSPACE = os.environ.get("AGY_WORKSPACE", "/homeassistant")
MEDIA_DIR = os.environ.get("AGY_MEDIA_DIR", "/media")
STATE_FILE = os.environ.get("AGY_STATE_FILE", "/data/.gemini/antigravity-cli/antigravity_state.pbtxt")
CLI_DATA_DIR = os.environ.get("AGY_CLI_DATA_DIR") or os.path.dirname(STATE_FILE) or "/data/.gemini/antigravity-cli"
HA_API_URL = os.environ.get("AGY_HA_API_URL", "http://supervisor/core/api").rstrip("/")
MAX_BODY_BYTES = int(os.environ.get("AGY_MAX_BODY_BYTES", str(1024 * 1024)))
HTTP_READ_TIMEOUT = float(os.environ.get("AGY_HTTP_READ_TIMEOUT", "10"))
AGY_BIN = os.environ.get("AGY_BIN") or (
    "/data/bin/agy" if os.path.exists("/data/bin/agy") else (shutil.which("agy") or "/usr/local/bin/agy")
)

# Limit concurrent heavy LLM tasks to avoid starving container resources
SEMAPHORE = asyncio.Semaphore(2)
BACKGROUND_TASKS: set[asyncio.Task] = set()
EVENT_TYPE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
SUMMARY_TABLES = ("conversation_summaries", "conversations_fts", "conversation_parents")
_VERSION_CACHE: tuple[str, float, str] | None = None


class HttpClientError(Exception):
    """Exception mapped directly to a specific HTTP 4xx response."""

    def __init__(self, status_line: str, message: str) -> None:
        super().__init__(message)
        self.status_line = status_line
        self.message = message


def _derive_effort(model: str, explicit_effort: str | None) -> str:
    if explicit_effort:
        return str(explicit_effort).strip().lower()
    for suffix in ("low", "medium", "high", "xhigh", "max"):
        if model.endswith(f"-{suffix}"):
            return suffix
    return "low"


def _is_authenticated() -> bool:
    return os.path.exists(STATE_FILE) or bool(os.environ.get("GEMINI_API_KEY"))


async def _get_agy_version() -> str:
    global _VERSION_CACHE
    try:
        mtime = os.path.getmtime(AGY_BIN)
    except OSError:
        return "unknown"

    if _VERSION_CACHE and _VERSION_CACHE[0] == AGY_BIN and _VERSION_CACHE[1] == mtime:
        return _VERSION_CACHE[2]

    try:
        proc = await asyncio.create_subprocess_exec(
            AGY_BIN,
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=2.0)
        version = stdout.decode("utf-8", errors="replace").strip() or "unknown"
    except (OSError, TimeoutError):
        version = "unknown"

    _VERSION_CACHE = (AGY_BIN, mtime, version)
    return version


def _parse_cli_json_output(raw_stdout: str, expect_structured: bool = False) -> tuple[str, dict, dict]:
    """Extract response text, usage dict, and metadata from CLI JSON stdout."""
    candidates = [raw_stdout]
    start_idx = raw_stdout.find("{")
    end_idx = raw_stdout.rfind("}")
    if start_idx != -1 and end_idx > start_idx:
        sliced = raw_stdout[start_idx : end_idx + 1]
        if sliced != raw_stdout:
            candidates.append(sliced)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                response_text = str(parsed.get("response", raw_stdout)).strip()
                usage = parsed.get("usage")
                usage_data = usage if isinstance(usage, dict) else {}
                extra: dict = {}
                if parsed.get("conversation_id"):
                    extra["conversation_id"] = str(parsed["conversation_id"])
                if parsed.get("structured_output") is not None:
                    extra["structured"] = parsed["structured_output"]
                elif expect_structured and response_text:
                    try:
                        extra["structured"] = json.loads(response_text)
                    except json.JSONDecodeError:
                        pass
                return response_text, usage_data, extra
        except json.JSONDecodeError:
            continue

    return raw_stdout.strip(), {}, {}


def _cleanup_ephemeral_conversation_sync(conversation_id: str, cli_data_dir: str = CLI_DATA_DIR) -> bool:
    """Remove all on-disk and SQLite traces of an ephemeral single-shot conversation."""
    if not UUID_RE.match(conversation_id):
        logger.warning("Skipping ephemeral cleanup for non-UUID conversation_id: %r", conversation_id)
        return False

    conv_dir = os.path.join(cli_data_dir, "conversations")
    for suffix in (".db", ".db-wal", ".db-shm"):
        path = os.path.join(conv_dir, f"{conversation_id}{suffix}")
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        except OSError as err:
            logger.warning("Failed to remove ephemeral file %s: %s", path, err)

    brain_dir = os.path.join(cli_data_dir, "brain", conversation_id)
    if os.path.isdir(brain_dir):
        shutil.rmtree(brain_dir, ignore_errors=True)

    annotation_path = os.path.join(cli_data_dir, "annotations", f"{conversation_id}.pbtxt")
    try:
        os.unlink(annotation_path)
    except FileNotFoundError:
        pass
    except OSError as err:
        logger.warning("Failed to remove ephemeral annotation %s: %s", annotation_path, err)

    summaries_db = os.path.join(cli_data_dir, "conversation_summaries.db")
    if os.path.isfile(summaries_db):
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(summaries_db, timeout=5.0)
            for table in SUMMARY_TABLES:
                try:
                    conn.execute(f"DELETE FROM {table} WHERE conversation_id = ?", (conversation_id,))
                except sqlite3.OperationalError as err:
                    if "no such table" not in str(err).lower():
                        logger.warning("Failed deleting %s from %s: %s", conversation_id, table, err)
            conn.commit()
        except sqlite3.Error as err:
            logger.warning("SQLite error cleaning ephemeral conversation %s: %s", conversation_id, err)
        finally:
            if conn is not None:
                conn.close()

    return True


def _prune_orphaned_summaries_sync(cli_data_dir: str = CLI_DATA_DIR) -> dict:
    """Remove ghost summary rows and annotations whose conversations/<id>.db no longer exists."""
    conv_dir = os.path.join(cli_data_dir, "conversations")
    if not os.path.isdir(conv_dir):
        return {"orphaned_conversations": 0, "removed_rows": 0, "removed_annotations": 0}

    existing_ids: set[str] = set()
    try:
        for entry in os.scandir(conv_dir):
            if entry.is_file() and entry.name.endswith(".db"):
                cid = entry.name[:-3]
                if UUID_RE.match(cid):
                    existing_ids.add(cid)
    except OSError as err:
        logger.warning("Failed scanning conversations directory %s: %s", conv_dir, err)
        return {"orphaned_conversations": 0, "removed_rows": 0, "removed_annotations": 0}

    removed_annotations = 0
    ann_dir = os.path.join(cli_data_dir, "annotations")
    if os.path.isdir(ann_dir):
        try:
            for entry in os.scandir(ann_dir):
                if entry.is_file() and entry.name.endswith(".pbtxt"):
                    cid = entry.name[:-6]
                    if UUID_RE.match(cid) and cid not in existing_ids:
                        try:
                            os.unlink(entry.path)
                            removed_annotations += 1
                        except OSError as err:
                            logger.warning("Failed removing orphan annotation %s: %s", entry.path, err)
        except OSError as err:
            logger.warning("Failed scanning annotations directory %s: %s", ann_dir, err)

    orphan_ids: set[str] = set()
    removed_rows = 0
    summaries_db = os.path.join(cli_data_dir, "conversation_summaries.db")
    if os.path.isfile(summaries_db):
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(summaries_db, timeout=5.0)
            present_tables: list[str] = []
            for table in SUMMARY_TABLES:
                try:
                    rows = conn.execute(f"SELECT DISTINCT conversation_id FROM {table}").fetchall()
                    present_tables.append(table)
                    for (cid,) in rows:
                        if isinstance(cid, str) and UUID_RE.match(cid) and cid not in existing_ids:
                            orphan_ids.add(cid)
                except sqlite3.OperationalError as err:
                    if "no such table" not in str(err).lower():
                        logger.warning("Failed scanning %s for orphans: %s", table, err)

            if orphan_ids and present_tables:
                orphan_list = sorted(orphan_ids)
                chunk_size = 400
                for start in range(0, len(orphan_list), chunk_size):
                    chunk = orphan_list[start : start + chunk_size]
                    placeholders = ",".join("?" for _ in chunk)
                    for table in present_tables:
                        cur = conn.execute(
                            f"DELETE FROM {table} WHERE conversation_id IN ({placeholders})",
                            chunk,
                        )
                        if cur.rowcount and cur.rowcount > 0:
                            removed_rows += cur.rowcount
                conn.commit()
        except sqlite3.Error as err:
            logger.warning("SQLite error pruning orphaned summaries: %s", err)
        finally:
            if conn is not None:
                conn.close()

    return {
        "orphaned_conversations": len(orphan_ids),
        "removed_rows": removed_rows,
        "removed_annotations": removed_annotations,
    }


async def run_agy_inference(
    prompt: str,
    files: list[str],
    model: str,
    effort: str,
    timeout: int,
    json_schema: str | None = None,
    conversation_id: str | None = None,
    ephemeral: bool = False,
) -> dict:
    start_time = time.time()
    effective_ephemeral = bool(ephemeral) and not bool(conversation_id)

    clean_files = [str(f).strip() for f in files if str(f).strip()]
    if clean_files:
        file_list = "\n".join(f"- {f}" for f in clean_files)
        full_prompt = (
            f"Attached media files for analysis:\n{file_list}\n\n"
            f"Directive: Analyze the attached media files directly using native multimodal vision. "
            f"Do not invoke terminal tools, ffmpeg, or background processes unless explicitly requested.\n\n"
            f"Instructions:\n{prompt}"
        )
    else:
        full_prompt = prompt

    cmd = [
        AGY_BIN,
        "--model",
        model,
        "--effort",
        effort,
        "--dangerously-skip-permissions",
        "--output-format",
        "json",
    ]
    if clean_files and MEDIA_DIR and os.path.isdir(MEDIA_DIR):
        cmd.extend(["--add-dir", MEDIA_DIR])
    if json_schema:
        cmd.extend(["--json-schema", json_schema])
    if conversation_id:
        cmd.extend(["--conversation", conversation_id])
    cmd.extend(["-p", full_prompt])

    env = os.environ.copy()
    env["HOME"] = "/root"

    cwd = WORKSPACE if os.path.isdir(WORKSPACE) else "/root"

    async with SEMAPHORE:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError as err:
            proc.kill()
            await proc.wait()
            raise TimeoutError(f"agy process timed out after {timeout} seconds") from err

    elapsed = round(time.time() - start_time, 2)
    raw_stdout = stdout.decode("utf-8", errors="replace").strip()
    err_text = stderr.decode("utf-8", errors="replace").strip()

    if proc.returncode != 0:
        if effective_ephemeral and raw_stdout:
            _, _, err_extra = _parse_cli_json_output(raw_stdout)
            err_cid = err_extra.get("conversation_id")
            if err_cid:
                await asyncio.to_thread(_cleanup_ephemeral_conversation_sync, err_cid)
        raise RuntimeError(f"agy exited with code {proc.returncode}: {err_text or raw_stdout}")

    response_text, usage_data, extra = _parse_cli_json_output(raw_stdout, expect_structured=bool(json_schema))

    if effective_ephemeral:
        created_cid = extra.pop("conversation_id", None)
        if created_cid:
            await asyncio.to_thread(_cleanup_ephemeral_conversation_sync, created_cid)

    result: dict = {
        "status": "success",
        "response": response_text,
        "model": model,
        "duration_seconds": elapsed,
    }
    result.update(extra)
    if effective_ephemeral:
        result["ephemeral"] = True
    if usage_data:
        result["usage"] = usage_data

    return result


def _post_ha_event_sync(event_type: str, payload: dict) -> None:
    token = os.environ.get("SUPERVISOR_TOKEN", "").strip()
    if not token:
        logger.warning("Skipping HA event '%s' callback: SUPERVISOR_TOKEN is not set", event_type)
        return

    url = f"{HA_API_URL}/events/{event_type}"
    data = json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except (urllib.error.URLError, OSError):
        logger.exception("Failed to fire Home Assistant event '%s'", event_type)


async def _run_async_and_emit(
    event_type: str,
    request_id: str,
    prompt: str,
    files: list[str],
    model: str,
    effort: str,
    timeout: int,
    json_schema: str | None,
    conversation_id: str | None,
    metadata: dict | None,
    ephemeral: bool = False,
) -> None:
    try:
        result = await run_agy_inference(
            prompt,
            files,
            model,
            effort,
            timeout,
            json_schema=json_schema,
            conversation_id=conversation_id,
            ephemeral=ephemeral,
        )
        event_payload = {**result, "request_id": request_id}
    except (RuntimeError, TimeoutError, OSError, ValueError) as err:
        logger.exception("Async inference '%s' failed", request_id)
        event_payload = {
            "status": "error",
            "request_id": request_id,
            "model": model,
            "message": str(err),
        }

    if metadata:
        event_payload["metadata"] = metadata

    await asyncio.to_thread(_post_ha_event_sync, event_type, event_payload)


async def _send_json(writer: asyncio.StreamWriter, status_line: str, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode()
    header = (
        f"HTTP/1.1 {status_line}\r\n"
        "Content-Type: application/json; charset=utf-8\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode()
    writer.write(header + body)
    await writer.drain()


async def _read_http_request(reader: asyncio.StreamReader) -> tuple[str, str, bytes] | None:
    try:
        line = await asyncio.wait_for(reader.readline(), timeout=HTTP_READ_TIMEOUT)
    except TimeoutError as err:
        raise HttpClientError("408 Request Timeout", "Timed out reading HTTP request line") from err

    if not line:
        return None

    parts = line.decode("utf-8", errors="replace").strip().split()
    if len(parts) < 2:
        return None
    method, raw_path = parts[0].upper(), parts[1]
    path = raw_path.split("?", 1)[0]

    headers: dict[str, str] = {}
    while True:
        try:
            header_line = await asyncio.wait_for(reader.readline(), timeout=HTTP_READ_TIMEOUT)
        except TimeoutError as err:
            raise HttpClientError("408 Request Timeout", "Timed out reading HTTP headers") from err
        if header_line in (b"\r\n", b"\n", b""):
            break
        decoded = header_line.decode("utf-8", errors="replace")
        if ":" in decoded:
            key, val = decoded.split(":", 1)
            headers[key.strip().lower()] = val.strip()

    raw_length = headers.get("content-length", "0").strip()
    try:
        content_length = int(raw_length)
    except ValueError as err:
        raise HttpClientError("400 Bad Request", f"Invalid Content-Length header: {raw_length!r}") from err

    if content_length < 0:
        raise HttpClientError("400 Bad Request", "Negative Content-Length is not allowed")
    if content_length > MAX_BODY_BYTES:
        raise HttpClientError(
            "413 Payload Too Large",
            f"Request body exceeds maximum allowed size of {MAX_BODY_BYTES} bytes",
        )

    if content_length == 0:
        return method, path, b"{}"

    try:
        body = await asyncio.wait_for(reader.readexactly(content_length), timeout=HTTP_READ_TIMEOUT)
    except TimeoutError as err:
        raise HttpClientError("408 Request Timeout", "Timed out reading request body") from err
    except asyncio.IncompleteReadError as err:
        raise HttpClientError("400 Bad Request", "Incomplete request body received") from err

    return method, path, body


class AgyApiServer:
    async def handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            parsed_req = await _read_http_request(reader)
            if parsed_req is None:
                return
            method, path, body = parsed_req

            # Route: Healthcheck
            if path == "/health" and method == "GET":
                agy_version = await _get_agy_version()
                await _send_json(
                    writer,
                    "200 OK",
                    {
                        "status": "ok",
                        "service": "agy-api",
                        "default_model": DEFAULT_MODEL,
                        "default_timeout": DEFAULT_TIMEOUT,
                        "default_ephemeral": DEFAULT_EPHEMERAL,
                        "authenticated": _is_authenticated(),
                        "agy_version": agy_version,
                    },
                )
                return

            # Route: Prune orphaned ghost summaries & annotations
            if path == "/api/cleanup-orphans" and method == "POST":
                summary = await asyncio.to_thread(_prune_orphaned_summaries_sync)
                await _send_json(writer, "200 OK", {"status": "ok", **summary})
                return

            # Route: /api/generate
            if path in ("/api/generate", "/api/v1/vision") and method == "POST":
                try:
                    data = json.loads(body.decode("utf-8", errors="replace"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    await _send_json(writer, "400 Bad Request", {"status": "error", "message": "Invalid JSON payload"})
                    return

                if not isinstance(data, dict):
                    await _send_json(
                        writer,
                        "400 Bad Request",
                        {"status": "error", "message": "JSON payload must be an object"},
                    )
                    return

                prompt = str(data.get("prompt", "")).strip()
                raw_files = data.get("files", [])
                files = [raw_files] if isinstance(raw_files, str) else (raw_files if isinstance(raw_files, list) else [])

                model = str(data.get("model") or DEFAULT_MODEL).strip()
                effort = _derive_effort(model, data.get("effort"))

                raw_schema = data.get("json_schema")
                json_schema: str | None = None
                if raw_schema is not None:
                    if isinstance(raw_schema, dict):
                        json_schema = json.dumps(raw_schema, separators=(",", ":"))
                    elif isinstance(raw_schema, str) and raw_schema.strip():
                        try:
                            json.loads(raw_schema)
                        except json.JSONDecodeError:
                            await _send_json(
                                writer,
                                "400 Bad Request",
                                {"status": "error", "message": "Invalid 'json_schema': must be valid JSON"},
                            )
                            return
                        json_schema = raw_schema.strip()
                    else:
                        await _send_json(
                            writer,
                            "400 Bad Request",
                            {"status": "error", "message": "Invalid 'json_schema': must be an object or JSON string"},
                        )
                        return

                raw_conv = data.get("conversation_id")
                conversation_id = str(raw_conv).strip() if raw_conv else None

                try:
                    requested_ephemeral = _parse_bool_flag(data.get("ephemeral"), default=DEFAULT_EPHEMERAL)
                except ValueError:
                    await _send_json(
                        writer,
                        "400 Bad Request",
                        {"status": "error", "message": "Invalid 'ephemeral': must be a boolean"},
                    )
                    return
                # Safety guard: never clean up an explicitly resumed conversation
                ephemeral = False if conversation_id else requested_ephemeral

                try:
                    timeout = int(data.get("timeout") or DEFAULT_TIMEOUT)
                    if timeout <= 0:
                        raise ValueError("timeout must be positive")
                except (ValueError, TypeError):
                    await _send_json(
                        writer,
                        "400 Bad Request",
                        {"status": "error", "message": "Invalid 'timeout': must be a positive integer"},
                    )
                    return

                if not prompt:
                    await _send_json(
                        writer,
                        "400 Bad Request",
                        {"status": "error", "message": "Missing 'prompt'"},
                    )
                    return

                is_async = bool(data.get("async", False)) or bool(data.get("event_type"))
                if is_async:
                    event_type = str(data.get("event_type") or "agy_generate_complete").strip()
                    if not EVENT_TYPE_RE.match(event_type):
                        await _send_json(
                            writer,
                            "400 Bad Request",
                            {"status": "error", "message": "Invalid 'event_type': alphanumeric/._- only"},
                        )
                        return
                    raw_meta = data.get("metadata")
                    if raw_meta is not None and not isinstance(raw_meta, dict):
                        await _send_json(
                            writer,
                            "400 Bad Request",
                            {"status": "error", "message": "Invalid 'metadata': must be a JSON object"},
                        )
                        return
                    request_id = str(data.get("request_id") or uuid.uuid4().hex)
                    task = asyncio.create_task(
                        _run_async_and_emit(
                            event_type=event_type,
                            request_id=request_id,
                            prompt=prompt,
                            files=files,
                            model=model,
                            effort=effort,
                            timeout=timeout,
                            json_schema=json_schema,
                            conversation_id=conversation_id,
                            metadata=raw_meta,
                            ephemeral=ephemeral,
                        )
                    )
                    BACKGROUND_TASKS.add(task)
                    task.add_done_callback(BACKGROUND_TASKS.discard)
                    await _send_json(
                        writer,
                        "202 Accepted",
                        {
                            "status": "accepted",
                            "async": True,
                            "event_type": event_type,
                            "request_id": request_id,
                            "model": model,
                            "ephemeral": ephemeral,
                        },
                    )
                    return

                logger.info(
                    "Running inference (model=%s, effort=%s, files=%d, timeout=%ds, structured=%s, ephemeral=%s)...",
                    model,
                    effort,
                    len(files),
                    timeout,
                    bool(json_schema),
                    ephemeral,
                )
                result = await run_agy_inference(
                    prompt,
                    files,
                    model,
                    effort,
                    timeout,
                    json_schema=json_schema,
                    conversation_id=conversation_id,
                    ephemeral=ephemeral,
                )
                logger.info(
                    "Inference completed in %.2fs (model=%s)",
                    result["duration_seconds"],
                    model,
                )
                await _send_json(writer, "200 OK", result)
                return

            await _send_json(
                writer,
                "404 Not Found",
                {"status": "error", "message": f"Path '{path}' not found"},
            )
        except HttpClientError as err:
            logger.warning("Client error (%s): %s", err.status_line, err.message)
            await _send_json(
                writer,
                err.status_line,
                {"status": "error", "message": err.message},
            )
        except TimeoutError as err:
            logger.error("Request timed out: %s", err)
            await _send_json(
                writer,
                "504 Gateway Timeout",
                {"status": "error", "message": str(err)},
            )
        except Exception as err:
            logger.exception("Unhandled error handling request")
            await _send_json(
                writer,
                "500 Internal Server Error",
                {"status": "error", "message": str(err)},
            )
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                logger.debug("Socket close failed cleanly", exc_info=True)


async def main() -> None:
    try:
        prune_stats = await asyncio.to_thread(_prune_orphaned_summaries_sync)
        if prune_stats["orphaned_conversations"] or prune_stats["removed_annotations"]:
            logger.info(
                "Pruned %d orphaned conversation summaries (%d rows) and %d orphan annotations on startup.",
                prune_stats["orphaned_conversations"],
                prune_stats["removed_rows"],
                prune_stats["removed_annotations"],
            )
    except Exception:
        logger.warning("Startup orphan summary pruning failed cleanly", exc_info=True)

    server_handler = AgyApiServer()
    server = await asyncio.start_server(
        server_handler.handle_client,
        "0.0.0.0",
        PORT,
    )
    logger.info(
        "Antigravity API bridge listening on port %d (model: %s, timeout: %ds, ephemeral: %s)...",
        PORT,
        DEFAULT_MODEL,
        DEFAULT_TIMEOUT,
        DEFAULT_EPHEMERAL,
    )
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
