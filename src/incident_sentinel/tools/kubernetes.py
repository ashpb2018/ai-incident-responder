"""Kubernetes diagnostics via the ``kubectl`` binary.

Every argument that originates from the model is validated before it reaches
the argv: values must not begin with ``-`` (so they cannot be smuggled in as
kubectl flags such as ``--kubeconfig`` or ``--as``), and resource names are
restricted to the characters Kubernetes actually permits.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil

from ..settings import get_settings
from . import ToolSpec

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9.\-/:]*$", re.IGNORECASE)
_MAX_OUTPUT = 6000


class InvalidArgument(ValueError):
    pass


def _safe(value: str, *, field: str) -> str:
    value = str(value).strip()
    if not value:
        raise InvalidArgument(f"{field} is empty")
    if value.startswith("-"):
        raise InvalidArgument(f"{field} may not start with '-' (looks like a flag): {value!r}")
    if not _NAME_RE.match(value):
        raise InvalidArgument(f"{field} has invalid characters: {value!r}")
    return value


async def _kubectl(*args: str) -> str:
    if shutil.which("kubectl") is None:
        return "kubectl is not installed or not on PATH."

    settings = get_settings()
    # Preserve the caller's environment (needed for exec credential plugins on
    # EKS/GKE) and just pin KUBECONFIG on top.
    env = dict(os.environ)
    env["KUBECONFIG"] = settings.kubeconfig

    try:
        proc = await asyncio.create_subprocess_exec(
            "kubectl", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=settings.kubectl_timeout
        )
    except TimeoutError:
        return f"kubectl timed out after {settings.kubectl_timeout}s"
    except OSError as exc:
        return f"kubectl failed to start: {exc}"

    out = stdout.decode(errors="replace").strip()
    err = stderr.decode(errors="replace").strip()
    body = out or err or "(no output)"
    if len(body) > _MAX_OUTPUT:
        body = body[:_MAX_OUTPUT] + f"\n... (truncated, {len(body)} chars total)"
    return body


async def get_pods(namespace: str = "default") -> str:
    ns = _safe(namespace, field="namespace")
    return await _kubectl("get", "pods", "-n", ns, "-o", "wide")


async def describe_resource(kind: str, name: str, namespace: str = "default") -> str:
    return await _kubectl(
        "describe", _safe(kind, field="kind"), _safe(name, field="name"),
        "-n", _safe(namespace, field="namespace"),
    )


async def get_pod_logs(
    pod: str, namespace: str = "default", container: str = "", previous: bool = False
) -> str:
    args = ["logs", _safe(pod, field="pod"), "-n", _safe(namespace, field="namespace"), "--tail=200"]
    if container:
        args += ["-c", _safe(container, field="container")]
    if previous:
        args.append("--previous")
    return await _kubectl(*args)


async def get_events(namespace: str = "default") -> str:
    return await _kubectl(
        "get", "events", "-n", _safe(namespace, field="namespace"),
        "--sort-by=.lastTimestamp",
    )


async def get_resource_usage(namespace: str = "default") -> str:
    return await _kubectl("top", "pods", "-n", _safe(namespace, field="namespace"))


def _wrap(fn, *keys_with_defaults):
    """Build a handler that validates presence and forwards named args."""
    async def handler(a: dict) -> str:
        try:
            kwargs = {}
            for key, default in keys_with_defaults:
                if default is _REQUIRED:
                    if key not in a:
                        return f"Missing required argument: {key}"
                    kwargs[key] = a[key]
                elif key in a:
                    kwargs[key] = a[key]
            return await fn(**kwargs)
        except InvalidArgument as exc:
            return f"Refused: {exc}"
    return handler


_REQUIRED = object()


SPECS = [
    ToolSpec(
        name="get_kubernetes_pods",
        description="List pods in a namespace with status, restarts, node, and IP.",
        parameters={"namespace": {"type": "string", "description": "Namespace (default 'default')."}},
        handler=_wrap(get_pods, ("namespace", "default")),
    ),
    ToolSpec(
        name="describe_kubernetes_resource",
        description="Run 'kubectl describe' on a resource (pod, deployment, service, node, …).",
        parameters={
            "kind": {"type": "string", "description": "Resource kind, e.g. pod, deployment."},
            "name": {"type": "string", "description": "Resource name."},
            "namespace": {"type": "string", "description": "Namespace (default 'default')."},
        },
        required=("kind", "name"),
        handler=_wrap(describe_resource, ("kind", _REQUIRED), ("name", _REQUIRED), ("namespace", "default")),
    ),
    ToolSpec(
        name="get_pod_logs",
        description=(
            "Fetch recent logs from a pod. Set previous=true to read the last "
            "crashed container instance — essential for CrashLoopBackOff."
        ),
        parameters={
            "pod": {"type": "string", "description": "Pod name."},
            "namespace": {"type": "string", "description": "Namespace (default 'default')."},
            "container": {"type": "string", "description": "Container name (multi-container pods)."},
            "previous": {"type": "boolean", "description": "Read the previous crashed instance's logs."},
        },
        required=("pod",),
        handler=_wrap(
            get_pod_logs, ("pod", _REQUIRED), ("namespace", "default"),
            ("container", ""), ("previous", False),
        ),
    ),
    ToolSpec(
        name="get_kubernetes_events",
        description="List recent namespace events, newest last — good for scheduling/pull failures.",
        parameters={"namespace": {"type": "string", "description": "Namespace (default 'default')."}},
        handler=_wrap(get_events, ("namespace", "default")),
    ),
    ToolSpec(
        name="get_kubernetes_resource_usage",
        description="Show pod CPU/memory usage in a namespace (requires metrics-server).",
        parameters={"namespace": {"type": "string", "description": "Namespace (default 'default')."}},
        handler=_wrap(get_resource_usage, ("namespace", "default")),
    ),
]
