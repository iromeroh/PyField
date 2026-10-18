"""PyField: Bethesda game worlds as structured, persistent, validated content.

Stable public API (covered by tests/test_public_api.py; see docs/api.md):

    open_plugin, create_plugin, open_load_order
    Plugin, LoadOrder, Query, Transaction, FormKey, Unresolved
    RecordNode, GroupNode, Subrecord, TypedRecord
    validate_plugin, Report, diff_plugins, Diff
    games (adapter registry), Capability/Status
    errors: PyFieldError and subclasses

Everything else (including attributes starting with "_") may change between minor versions.
"""
from .capabilities import Capability, CapabilitySet, Status
from .core.formids import FormKey, Unresolved
from .core.loadorder import LoadOrder, Query
from .core.nodes import GroupNode, RecordNode
from .core.plugin import Plugin
from .core.subrecords import Subrecord
from .diff import Diff, diff_plugins
from .edit import Transaction
from .errors import (FormatError, PyFieldError, ResolutionError, SchemaError, TransactionError,
                     UnsupportedOperation, ValidationError)
from .schema.records import TypedRecord
from .validate import Report, validate_plugin
from . import games

__version__ = '0.3.0'

__all__ = [
    'open_plugin', 'create_plugin', 'open_load_order',
    'Plugin', 'LoadOrder', 'Query', 'Transaction', 'FormKey', 'Unresolved',
    'RecordNode', 'GroupNode', 'Subrecord', 'TypedRecord',
    'validate_plugin', 'Report', 'diff_plugins', 'Diff',
    'games', 'Capability', 'CapabilitySet', 'Status',
    'PyFieldError', 'FormatError', 'ResolutionError', 'SchemaError', 'TransactionError',
    'UnsupportedOperation', 'ValidationError', '__version__',
]


def open_plugin(path, game=None, **kwargs) -> Plugin:
    """Open one plugin file; the game is detected from its header unless given."""
    return Plugin.open(path, game, **kwargs)


def create_plugin(name: str, game: str, masters=(), *, flags: int = 0, author: str = '',
                  description: str = '', master_kinds: dict | None = None) -> Plugin:
    """A new empty plugin. Pass master_kinds (name -> 'full'|'medium'|'small') when the
    masters are not on disk next to where it will be saved."""
    plugin = Plugin.create(name, game, masters, flags=flags, author=author, description=description)
    if master_kinds:
        plugin.set_master_kinds(master_kinds)
    return plugin


def open_load_order(data_dir, plugins, game=None, with_masters: bool = True) -> LoadOrder:
    """Open plugins from a data folder (masters added first, recursively)."""
    return LoadOrder.open(data_dir, plugins, game, with_masters)
