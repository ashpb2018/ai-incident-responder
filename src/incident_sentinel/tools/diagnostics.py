"""Host-level diagnostics: safe shell probes, HTTP checks, and DNS lookups."""

from __future__ import annotations

import asyncio
import socket
import time

import httpx

from . import ToolSpec
from .netguard import BlockedTarget, assert_public_url

_CMD_TIMEOUT = 20
_HTTP_TIMEOUT = 15
_MAX_OUTPUT = 3000

# Read-only network/host probes only. Notably absent: curl/wget (data
# exfiltration + SSRF), and any file-reading command (cat/tail/grep), which
# would let the agent read arbitrary files off the host.
_SAFE_COMMANDS: dict[str, str] = {
    "ping": "ping",
    "nslookup": "nslookup",
    "dig": "dig",
    "host": "host",
    "netstat": "netstat",
    "ss": "ss",
    "traceroute": "traceroute",
    "ps": "ps",
    "df": "df",
    "free": "free",
    "uptime": "uptime",
    "hostname": "hostname",
}

_FORBIDDEN_ARG_CHARS = frozenset(";&|`$()<>\n\r")


async def run_shell_command(command: str, args: list[str]) -> str:
    if command not in _SAFE_COMMANDS:
        return f"Command '{command}' is not allowed. Allowed: {', '.join(sorted(_SAFE_COMMANDS))}."

    cleaned: list[str] = []
    for raw in args[:20]:
        arg = str(raw).strip()
        if any(ch in arg for ch in _FORBIDDEN_ARG_CHARS):
            return f"Argument contains disallowed characters: {arg!r}"
        cleaned.append(arg)

    argv = [_SAFE_COMMANDS[command], *cleaned]
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_CMD_TIMEOUT)
    except TimeoutError:
        return f"Command timed out after {_CMD_TIMEOUT}s: {' '.join(argv)}"
    except FileNotFoundError:
        return f"Command not installed on this host: {command}"
    except OSError as exc:
        return f"Command failed to start: {exc}"

    body = (stdout.decode(errors="replace").strip() or stderr.decode(errors="replace").strip())
    body = body or "(no output)"
    if len(body) > _MAX_OUTPUT:
        body = body[:_MAX_OUTPUT] + f"\n... (truncated, {len(body)} chars total)"
    return f"$ {' '.join(argv)}\n{body}"


async def check_http_endpoint(url: str, method: str = "GET", timeout: int = 10) -> str:
    method = method.upper()
    if method not in ("GET", "HEAD"):
        return f"Method {method!r} not allowed. Use GET or HEAD."
    try:
        assert_public_url(url)
    except BlockedTarget as exc:
        return f"Refused: {exc}"

    try:
        start = time.monotonic()
        # follow_redirects is off so a 3xx to an internal host cannot bypass the guard.
        async with httpx.AsyncClient(follow_redirects=False) as client:
            resp = await client.request(method, url, timeout=min(timeout, _HTTP_TIMEOUT))
        elapsed_ms = (time.monotonic() - start) * 1000
    except httpx.TimeoutException:
        return f"Request timed out: {url}"
    except httpx.HTTPError as exc:
        return f"Request failed: {url} — {exc}"

    lines = [
        f"HTTP {method} {url}",
        f"Status: {resp.status_code} {resp.reason_phrase}",
        f"Latency: {elapsed_ms:.1f}ms",
    ]
    if 300 <= resp.status_code < 400 and "location" in resp.headers:
        lines.append(f"Redirect -> {resp.headers['location']}")
    if resp.status_code >= 400:
        snippet = resp.text[:500].strip()
        if snippet:
            lines.append(f"Body: {snippet}")
    for header in ("content-type", "x-request-id", "server"):
        if header in resp.headers:
            lines.append(f"{header}: {resp.headers[header]}")
    return "\n".join(lines)


async def dns_lookup(hostname: str) -> str:
    hostname = hostname.replace("https://", "").replace("http://", "").split("/")[0].strip()
    if not hostname:
        return "No hostname provided."
    try:
        loop = asyncio.get_running_loop()
        infos = await loop.run_in_executor(None, socket.getaddrinfo, hostname, None)
    except OSError as exc:
        return f"DNS lookup failed for {hostname}: {exc}"
    addresses = sorted({info[4][0] for info in infos})
    if not addresses:
        return f"No DNS records for {hostname}."
    return f"DNS for {hostname}:\n" + "\n".join(f"  {a}" for a in addresses)


SPECS = [
    ToolSpec(
        name="run_shell_command",
        description=(
            "Run a read-only diagnostic command on the agent host: connectivity "
            "(ping/traceroute), DNS (dig/nslookup/host), sockets (netstat/ss), "
            "processes (ps), and host stats (df/free/uptime). "
            f"Allowed: {', '.join(sorted(_SAFE_COMMANDS))}."
        ),
        parameters={
            "command": {"type": "string", "description": "One of the allowed commands."},
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Arguments, e.g. ['-c', '3', 'api.example.com'] for ping.",
            },
        },
        required=("command", "args"),
        handler=lambda a: run_shell_command(a["command"], a.get("args", [])),
    ),
    ToolSpec(
        name="check_http_endpoint",
        description=(
            "Make an HTTP GET/HEAD request to a public URL and report status, "
            "latency, and headers. Private, loopback, and link-local addresses "
            "are refused."
        ),
        parameters={
            "url": {"type": "string", "description": "Full public URL, e.g. https://api.example.com/health"},
            "method": {"type": "string", "description": "GET or HEAD (default GET)."},
            "timeout": {"type": "integer", "description": "Seconds, max 15 (default 10)."},
        },
        required=("url",),
        handler=lambda a: check_http_endpoint(a["url"], a.get("method", "GET"), a.get("timeout", 10)),
    ),
    ToolSpec(
        name="dns_lookup",
        description="Resolve a hostname to IP addresses to diagnose DNS/service discovery.",
        parameters={"hostname": {"type": "string", "description": "Hostname to resolve."}},
        required=("hostname",),
        handler=lambda a: dns_lookup(a["hostname"]),
    ),
]
