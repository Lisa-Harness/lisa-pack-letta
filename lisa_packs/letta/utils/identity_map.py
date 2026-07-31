"""Persistent Lisa-to-Letta identity mapping.

Maps a Lisa identity tuple ``(workspace_id, user_slug, surface_id,
conversation_id)`` to a Letta ``agent_id`` (plus optional core block ids,
source ids, and sync metadata) so the adapter server and operations can
resolve the right Letta agent without re-creating one each turn.

The map is persisted as a JSON file inside the ``lisa-storage`` files
sandbox (``<data_dir>/files/letta/identity-map.json``) via the
:class:`sdk.storage.StorageBackend` — the same sandboxed I/O backend the
``lisa-storage`` MCP server wraps. Direct pack-level filesystem writes
are intentionally disallowed so all persistence ownership remains in the
storage layer. Reads tolerate a missing file as an empty map.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sdk.storage import StorageBackend

logger = logging.getLogger(__name__)

__all__ = ["IdentityEntry", "IdentityMap", "identity_key"]

_IDENTITY_MAP_SUBDIR = "letta"
_IDENTITY_MAP_FILE = "identity-map.json"
#: Sandbox-relative path (forward slashes) to the identity-map file.
_IDENTITY_MAP_REL = f"{_IDENTITY_MAP_SUBDIR}/{_IDENTITY_MAP_FILE}"


def identity_key(
    *,
    workspace_id: str,
    user_slug: str,
    surface_id: str = "",
    conversation_id: str = "",
) -> str:
    """Build a stable composite key for one Lisa identity.

    The key is filesystem- and JSON-safe so it can be used as a dict key
    in the sidecar without escaping concerns.
    """
    return "|".join(
        (
            workspace_id or "default",
            user_slug or "default",
            surface_id or "",
            conversation_id or "",
        )
    )


@dataclass(slots=True)
class IdentityEntry:
    """One resolved Letta binding for one Lisa identity."""

    agent_id: str
    agent_name: str = ""
    core_block_ids: dict[str, str] = field(default_factory=dict)
    source_ids: list[str] = field(default_factory=list)
    last_sync_turn: int = 0
    last_sync_at: str = ""
    last_compact_turn: int = 0
    last_compact_at: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class IdentityMap:
    """Load/save the Lisa↔Letta identity sidecar.

    The map is deliberately a single JSON file under the owning data dir.
    It is NOT a kernel seam and holds no host runtime state.

    All file I/O is routed through :class:`sdk.storage.StorageBackend`,
    the sandboxed backend that ``lisa-storage`` wraps, so the pack never
    touches the filesystem directly.
    """

    def __init__(self, data_dir: Path) -> None:
        self._backend = StorageBackend(Path(data_dir))

    @property
    def path(self) -> Path:
        """The on-disk path of the identity-map file inside the storage sandbox.

        Provided for diagnostics and tests; reads/writes should go through
        :meth:`load` / :meth:`_write` (which route via the storage backend)
        rather than touching this path directly.
        """
        return self._backend.files_root() / _IDENTITY_MAP_SUBDIR / _IDENTITY_MAP_FILE

    def load(self) -> dict[str, dict[str, Any]]:
        """Return the raw mapping ``{identity_key: entry_dict}``.

        Tolerates a missing file (returns ``{}``) and a corrupt file
        (logs a warning, returns ``{}``).
        """
        result = self._backend.read_file(_IDENTITY_MAP_REL, encoding="utf-8")
        try:
            parsed = json.loads(result)
        except (json.JSONDecodeError, TypeError) as exc:
            # Corrupt / non-JSON content on disk.
            logger.warning("letta: identity map unreadable: %s", exc)
            return {}
        if not isinstance(parsed, dict):
            return {}
        # The storage backend returns ``{"error": "<str>"}`` on failure
        # (missing file, denied path, read error). A valid identity map
        # has dict values, so an ``error`` key with a string value is an
        # unambiguous backend error, not a user identity key.
        err = parsed.get("error")
        if isinstance(err, str):
            if "not found" not in err:
                logger.warning("letta: identity map read failed: %s", err)
            return {}
        return self._coerce(parsed)

    @staticmethod
    def _coerce(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            str(k): (v if isinstance(v, dict) else {})
            for k, v in raw.items()
        }

    def get(self, key: str) -> IdentityEntry | None:
        """Return one entry by composite key, or ``None``."""
        raw = self.load().get(key)
        if raw is None:
            return None
        try:
            return IdentityEntry(**raw)
        except TypeError:
            return None

    def upsert(self, key: str, entry: IdentityEntry) -> None:
        """Insert or replace one entry and persist atomically."""
        data = self.load()
        data[key] = asdict(entry)
        self._write(data)

    def update(self, key: str, **fields: Any) -> IdentityEntry | None:
        """Patch one entry's fields in place; returns the new entry or None."""
        current = self.get(key)
        if current is None:
            return None
        for name, value in fields.items():
            if hasattr(current, name):
                setattr(current, name, value)
        self.upsert(key, current)
        return current

    def all_entries(self) -> dict[str, IdentityEntry]:
        """Return all parsed entries keyed by composite identity key."""
        out: dict[str, IdentityEntry] = {}
        for key, raw in self.load().items():
            try:
                out[key] = IdentityEntry(**raw)
            except TypeError:
                continue
        return out

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
        """Persist the full mapping through the ``lisa-storage`` sandbox.

        The storage backend creates parent directories and applies the
        sandbox path policy. A JSON error object from the backend is
        raised as :class:`OSError` so callers' broad-except handlers
        still catch write failures.
        """
        payload = json.dumps(data, indent=2, sort_keys=True)
        result = self._backend.write_file(_IDENTITY_MAP_REL, payload)
        try:
            decoded = json.loads(result)
        except json.JSONDecodeError:
            return  # non-JSON is unexpected but not actionable here
        if isinstance(decoded, dict) and "error" in decoded:
            raise OSError(decoded["error"])
