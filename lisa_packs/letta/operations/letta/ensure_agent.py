"""Resolve or create the Letta agent for the current Lisa identity."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from kernel.models import OperationExecutionContext, OperationResult
from lisa_packs.letta.utils.client import LettaClient, LettaError
from lisa_packs.letta.utils.identity_map import IdentityEntry, IdentityMap, identity_key
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_DEFAULT_AGENT_NAME = "lisa-agent"


class Parameters(BaseModel):
    agent_name: str = Field(
        default_factory=lambda: os.getenv("LETTA_DEFAULT_AGENT_NAME", _DEFAULT_AGENT_NAME),
        description=(
            "Name for a newly created Letta agent. Ignored when an agent is already mapped."
        ),
    )


def _identity_map(runtime_data_dir: Any) -> IdentityMap:
    # Operations resolve the data dir from the environment; the host wires
    # the same data dir when launching the adapter MCP server.
    data_dir = os.getenv("LISA_DATA_DIR", str(runtime_data_dir or ""))
    return IdentityMap(Path(data_dir))


def _mapped_agent_result(
    identity: IdentityMap,
    key: str,
    agent_id: str,
    agent_name: str,
    *,
    output_text: str,
    extra: dict[str, Any] | None = None,
) -> OperationResult:
    """Persist the agent mapping and build the resolved-agent result."""
    identity.upsert(key, IdentityEntry(agent_id=agent_id, agent_name=agent_name))
    output_json: dict[str, Any] = {"agent_id": agent_id, "created": False, "key": key}
    if extra:
        output_json.update(extra)
    return OperationResult(output_text=output_text, output_json=output_json)


def _error_result(exc: Exception, base_url: str) -> OperationResult:
    """Build the failure result for a Letta call that could not complete.

    Catches transport-level failures (httpx.ConnectError,
    httpx.TimeoutException, and anything else) so the operation surfaces a
    clear "Letta not reachable" message instead of crashing the turn.
    """
    if isinstance(exc, LettaError):
        return OperationResult(
            output_text=f"⛔ Letta agent creation failed: {exc}",
            output_json={"error": str(exc)},
        )
    return OperationResult(
        output_text=(f"⛔ Letta is not reachable at {base_url}: {type(exc).__name__}: {exc}"),
        output_json={
            "error": str(exc),
            "error_type": type(exc).__name__,
            "base_url": base_url,
        },
    )


async def execute(ctx: OperationExecutionContext) -> OperationResult:
    """Return the Letta agent_id for this Lisa identity, creating one if needed."""
    agent_name = str(
        ctx.params.get("agent_name") or os.getenv("LETTA_DEFAULT_AGENT_NAME", _DEFAULT_AGENT_NAME)
    )
    key = identity_key(
        workspace_id=ctx.workspace_id,
        user_slug=ctx.user_slug,
        surface_id=ctx.surface_id,
        conversation_id=ctx.conversation_id,
    )
    identity = _identity_map(ctx.workspace_id)

    # If LETTA_AGENT_ID is set, use it directly — no lookup or creation.
    explicit_agent_id = os.getenv("LETTA_AGENT_ID", "").strip()
    if explicit_agent_id:
        return _mapped_agent_result(
            identity,
            key,
            explicit_agent_id,
            agent_name,
            output_text=f"Letta agent resolved (explicit): {explicit_agent_id}",
            extra={"explicit": True},
        )

    existing = identity.get(key)
    if existing is not None and existing.agent_id:
        return _mapped_agent_result(
            identity,
            key,
            existing.agent_id,
            agent_name,
            output_text=f"Letta agent resolved: {existing.agent_id}",
        )

    base_url = os.getenv("LETTA_BASE_URL", "http://localhost:8283")
    api_key = os.getenv("LETTA_API_KEY", "")
    try:
        async with LettaClient(base_url=base_url, api_key=api_key) as client:
            # Look up an existing agent by name before creating — Letta
            # Cloud's free plan allows only 3 agents, and creating a
            # duplicate may 402.
            found = await client.find_agent_by_name(agent_name)
            if found is not None and found.get("id"):
                return _mapped_agent_result(
                    identity,
                    key,
                    str(found["id"]),
                    str(found.get("name") or agent_name),
                    output_text=f"✅ Letta agent resolved (existing): {found['id']}",
                    extra={"found_by_name": True},
                )

            agent = await client.create_agent(name=agent_name)
    except (LettaError, Exception) as exc:  # pylint: disable=broad-except
        return _error_result(exc, base_url)
    agent_id = str(agent.get("id") or "")
    if not agent_id:
        return OperationResult(
            output_text="⛔ Letta create_agent returned no agent id",
            output_json={"error": "no agent id"},
        )
    identity.upsert(
        key,
        IdentityEntry(agent_id=agent_id, agent_name=str(agent.get("name") or agent_name)),
    )
    return OperationResult(
        output_text=f"✅ Letta agent created: {agent_id}",
        output_json={"agent_id": agent_id, "created": True, "key": key},
    )
