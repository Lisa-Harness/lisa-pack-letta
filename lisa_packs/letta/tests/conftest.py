"""Shared catalog fixture for letta-pack tests that need the workflow catalog.

Spawns the ``lisa-catalog`` MCP server with content roots that include
the letta pack (plus core/memory/search so dependencies resolve) and
registers it with the kernel so ``get_workflow_catalog()`` and
``get_operation_catalog()`` work in tests. Modeled on
``kernel/tests/conftest_catalog.py``.
"""

from __future__ import annotations

import os
import sys
import typing
from pathlib import Path

import pytest
from kernel.ipsar_fsm import (
    get_workflow_catalog,
    register_content_mcp,
    register_operation_callbacks,
)
from kernel.operations.registry import (
    execute_operation,
    get_operation_catalog,
    register_operation_mcp,
)
from kernel.tools.mcp_client import MCPClientConfig

# The framework repo checkout (this file lives at
# <pack>/lisa_packs/letta/tests/conftest.py → parents[3] = <pack>), which
# bundles core/memory/search under sdk/packs/<name>. Content roots must point
# at each pack's *package* dir (the one containing modes//operations//tools/),
# not the distribution checkout: resolve_content_roots scans `<root>/modes` at
# exactly one level of depth, so lisa_packs/ (which only nests the letta
# package) yields no mode roots — the pack's own tests then see only the
# core 'default' mode and the letta/letta-agent routing assertions fail.
_LISA_REPO: Path = (Path(__file__).resolve().parents[3] / "sdk" / "packs").resolve()
_CORE_ROOT: Path = (_LISA_REPO / "core" / "src" / "sdk" / "packs" / "core").resolve()
_MEMORY_ROOT: Path = (_LISA_REPO / "memory" / "src" / "sdk" / "packs" / "memory").resolve()
_SEARCH_ROOT: Path = (_LISA_REPO / "search" / "src" / "sdk" / "packs" / "search").resolve()
_LETTA_ROOT: Path = (Path(__file__).resolve().parents[1]).resolve()


def _make_catalog_mcp_config() -> MCPClientConfig:
    """Build an MCPClientConfig that spawns lisa-catalog with the needed packs."""
    return MCPClientConfig(
        server_id="lisa-catalog-letta-test",
        command=sys.executable,
        args=[
            "-m",
            "mcp_server.catalog.server",
            "--data-dir",
            str(_CORE_ROOT),
        ],
        env={
            # The catalog child splits SDK_CONTENT_ROOTS on os.pathsep (':'
            # on POSIX); a literal ';' makes the whole string one bogus path
            # that gets skipped, leaving only entry-point-discovered packs.
            "SDK_CONTENT_ROOTS": os.pathsep.join(
                str(root) for root in (_CORE_ROOT, _MEMORY_ROOT, _SEARCH_ROOT, _LETTA_ROOT)
            ),
            "LISA_SESSION_PROVIDER_SELECTIONS": '{"modes":{"default":"lisa-pack-core"}}',
        },
    )


@pytest.fixture(scope="module", autouse=True)
def _mcp_catalog_setup() -> typing.Iterator[None]:
    """Wire the catalog MCP and operation callbacks so the kernel can load catalogs.

    Order matters: operation MCP first, then operation callbacks, then content MCP.
    ``validate_workflow_catalog`` calls ``_validate_mode_operation_bindings`` which
    needs the operation callbacks registered before it can validate mode bindings.

    The catalog is eagerly loaded here during module setup (sync context) so async
    tests don't need to call ``asyncio.run()`` from inside a running event loop.
    """
    config = _make_catalog_mcp_config()
    register_operation_mcp(config)
    register_operation_callbacks(get_operation_catalog, execute_operation)
    register_content_mcp(config)
    # Eagerly load the workflow catalog now (sync context, before any async test runs)
    get_workflow_catalog()
    # The turn runner's routing vocabulary must be wired at "boot" time; the
    # kernel raises at first use otherwise. Mirror the minimal representative
    # vocabulary from kernel/tests/conftest.py.
    from kernel.routing_vocabulary import (
        register_routing_vocabulary,
        reset_routing_vocabulary,
    )

    reset_routing_vocabulary()
    register_routing_vocabulary(
        sequential_connectors=["then", "and then", "after that", "next", "followed by"],
        producer_intents=["research", "gather", "learn", "read", "analyze", "review", "architect"],
        consumer_intents=["code", "write", "implement", "review"],
        resume_phrases=["proceed", "continue", "go ahead", "go for it", "do it", "carry on", "pick up", "resume", "next step", "keep going"],
        topic_abandonment_markers=["side quest", "rewind", "never mind", "forget", "different topic", "not about"],
    )
    yield
    reset_routing_vocabulary()