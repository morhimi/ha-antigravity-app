#!/usr/bin/env python3
"""
Lightweight REST API bridge exposing Antigravity CLI (agy)
to Home Assistant automations over internal HTTP.
"""

import asyncio
import json
import logging
import os
import shutil
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("agy-api")

PORT = int(os.environ.get("AGY_API_PORT", "8120"))
DEFAULT_MODEL = os.environ.get("AGY_DEFAULT_MODEL", "gemini-3.8-flash-low")
WORKSPACE = os.environ.get("AGY_WORKSPACE", "/homeassistant")
AGY_BIN = os.environ.get("AGY_BIN") or (
    "/data/bin/agy" if os.path.exists("/data/bin/agy") else (shutil.which("agy") or "/usr/local/bin/agy")
)

# Limit concurrent heavy LLM tasks to 2
SEMAPHORE = asyncio.Semaphore(2)


def _derive_effort(model: str, explicit_effort: str | None) -> str:
    if explicit_effort:
        return str(explicit_effort).strip().lower()
    for suffix in ("low", "medium", "high", "xhigh", "max"):
        if model.endswith(f"-{suffix}"):
            return suffix
    return "low"


async def run_agy_inference(
    prompt: str,
    files: list[str],
    model: str,
    effort: str,
    timeout: int,
) -> dict:
    start_time = time.time()

    clean_files = [str(f).strip() for f in files if str(f).strip()]
    if clean_files:
        file_list = "\n".join(f"- {f}" for f in clean_files)
        full_prompt = (
            f"Please inspect and analyze the following media files:\n{file_list}\n\n"
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
        "-p",
        full_prompt,
    ]

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
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise TimeoutError(f"agy process timed out after {timeout} seconds")

    elapsed = round(time.time() - start_time, 2)
    output_text = stdout.decode("utf-8", errors="replace").strip()
    err_text = stderr.decode("utf-8", errors="replace").strip()

    if proc.returncode != 0:
        raise RuntimeError(f"agy exited with code {proc.returncode}: {err_text or output_text}")

    return {
        "status": "success",
        "response": output_text,
        "model": model,
        "duration_seconds": elapsed,
    }


async def _send_json(writer: asyncio.StreamWriter, status_line: str, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    header = (
        f"HTTP/1.1 {status_line}\r\n"
        "Content-Type: application/json; charset=utf-8\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("utf-8")
    writer.write(header + body)
    await writer.drain()


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        line = await reader.readline()
        if not line:
            return

        parts = line.decode("utf-8", errors="replace").strip().split()
        if len(parts) < 2:
            return
        method, raw_path = parts[0].upper(), parts[1]
        path = raw_path.split("?", 1)[0]

        headers: dict[str, str] = {}
        while True:
            header_line = await reader.readline()
            if header_line in (b"\r\n", b"\n", b""):
                break
            decoded = header_line.decode("utf-8", errors="replace")
            if ":" in decoded:
                key, val = decoded.split(":", 1)
                headers[key.strip().lower()] = val.strip()

        content_length = int(headers.get("content-length", "0"))
        body = await reader.readexactly(content_length) if content_length > 0 else b"{}"

        # Route: Healthcheck
        if path == "/health" and method == "GET":
            await _send_json(
                writer,
                "200 OK",
                {
                    "status": "ok",
                    "service": "agy-api",
                    "default_model": DEFAULT_MODEL,
                },
            )
            return

        # Route: /api/generate (and /api/v1/vision alias)
        if path in ("/api/generate", "/api/v1/vision") and method == "POST":
            data = json.loads(body.decode("utf-8", errors="replace"))
            prompt = str(data.get("prompt", "")).strip()
            raw_files = data.get("files", [])
            if isinstance(raw_files, str):
                files = [raw_files]
            elif isinstance(raw_files, list):
                files = raw_files
            else:
                files = []

            model = str(data.get("model") or DEFAULT_MODEL).strip()
            effort = _derive_effort(model, data.get("effort"))
            timeout = int(data.get("timeout", 60))

            if not prompt:
                await _send_json(
                    writer,
                    "400 Bad Request",
                    {"status": "error", "message": "Missing 'prompt'"},
                )
                return

            logger.info(
                "Running inference (model=%s, effort=%s, files=%d, timeout=%ds)...",
                model,
                effort,
                len(files),
                timeout,
            )
            result = await run_agy_inference(prompt, files, model, effort, timeout)
            logger.info(
                "Inference completed in %.2fs (model=%s)",
                result["duration_seconds"],
                model,
            )
            await _send_json(writer, "200 OK", result)
            return

        # 404 Not Found
        await _send_json(
            writer,
            "404 Not Found",
            {"status": "error", "message": f"Route not found: {method} {path}"},
        )

    except Exception as exc:
        logger.error("Error handling request: %s", exc)
        try:
            await _send_json(
                writer,
                "500 Internal Server Error",
                {"status": "error", "message": str(exc)},
            )
        except Exception:
            pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def main() -> None:
    server = await asyncio.start_server(handle_client, "0.0.0.0", PORT)
    logger.info(
        "Antigravity API bridge listening on port %d (default model: %s)...",
        PORT,
        DEFAULT_MODEL,
    )
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
