"""Game adapter protocol.

The generic core knows bytes, nodes and FormKeys. Everything a specific game decides is
supplied by a `GameAdapter`:

========================  ==========================================================
format                    FormatSpec: header sizes, signatures, compression
header                    HeaderScheme: masters, counts, author in the header record
groups                    GroupLayout: meaning of group kinds and labels
namespaces + flag fields  FormID namespaces and which header flags select them
native_group_order        top-level group order for inserted groups
record_header_tail        bytes after the common 16 in a new record header
capabilities              what is supported/validated (pyfield.capabilities)
schema_loader             callable returning the typed SchemaSet (optional)
========================  ==========================================================

Adapters register with `pyfield.games.register`, or are discovered from the
``pyfield.adapters`` entry-point group so they can ship as separate packages.
See docs/adapters.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..capabilities import CapabilitySet
from ..core.format import FormatSpec
from ..core.formids import FULL, MEDIUM, SMALL
from ..core.groups import GroupLayout
from ..core.header import HeaderScheme

ADAPTER_API_VERSION = 1      # bumped when the protocol below changes incompatibly


@dataclass
class GameAdapter:
    name: str                                  # registry key, e.g. 'starfield'
    title: str
    format: FormatSpec
    header: HeaderScheme
    groups: GroupLayout
    header_versions: tuple[float, ...]         # header versions accepted when sniffing files
    default_header_version: float = 1.0
    namespaces: frozenset = frozenset({FULL})
    master_flag: int = 0x1
    localized_flag: int | None = None
    small_flag: int | None = None
    medium_flag: int | None = None
    native_group_order: tuple[str, ...] = ()
    record_header_tail: bytes = b''            # padded with zeros to the record header size
    first_object_id: int = 0x800               # first local ID the editor assigns
    next_id_has_own_prefix: bool = False       # new headers store (own ordinal << 24) | next local ID
    capabilities: CapabilitySet = field(default_factory=CapabilitySet)
    schema_loader: object = None               # callable -> pyfield.schema.records.SchemaSet
    schema_version: str | None = None          # version of the schema package, for reports
    inventory_loader: object = None            # callable -> member inventory dict (e.g. from xEdit)
    formid_array_signatures: frozenset = frozenset()   # subrecords that are plain FormID arrays
    formid_locators: dict = field(default_factory=dict)  # sub sig -> fn(data, record_sig) -> offsets | None
    transplant_policy: dict = field(default_factory=dict)   # record signature -> 'copy' | 'rebuild'
    asset_rules: object = None                 # pyfield.assets.index.AssetRules
    name_signature: str = 'FULL'               # display-name subrecord (LoadOrder.display_name)
    asset_hooks: dict = field(default_factory=dict)  # record signature -> fn(view, assets, cache) -> paths
    rotation_convention: tuple = ('xyz', -1)  # Euler order and angle sign of placed references
    exterior_cell_size: float | None = None  # world units per exterior cell edge
    placeable_types: dict = field(default_factory=dict)   # base signature -> placed record signature
    override_strip: dict = field(default_factory=dict)    # signature -> fields only valid in the defining file
    api_version: int = ADAPTER_API_VERSION

    # -- flags ----------------------------------------------------------------------------------
    def master_kind(self, header_flags: int) -> str:
        if self.small_flag is not None and header_flags & self.small_flag:
            return SMALL
        if self.medium_flag is not None and header_flags & self.medium_flag:
            return MEDIUM
        return FULL

    def is_localized(self, header_flags: int) -> bool:
        return bool(self.localized_flag is not None and header_flags & self.localized_flag)

    # -- detection ------------------------------------------------------------------------------
    def sniff(self, head: bytes) -> bool:
        """True if the first bytes of a file look like this game's plugin header."""
        if head[:4] != self.format.plugin_header_signature:
            return False
        version = self.header.sniff(head, self.format.record_header_size)
        return version is not None and any(abs(version - v) < 1e-4 for v in self.header_versions)

    # -- records --------------------------------------------------------------------------------
    def header_tail(self) -> bytes:
        """Bytes 16.. of a new record header."""
        size = self.format.record_header_size - 16
        return (self.record_header_tail + bytes(size))[:size]

    @property
    def schemas(self):
        """Compiled typed record classes (None if this adapter has no schemas)."""
        if self.schema_loader is None:
            return None
        if '_schemas' not in self.__dict__:
            self.__dict__['_schemas'] = self.schema_loader()
        return self.__dict__['_schemas']

    def lstring_signatures(self, record_signature: str) -> frozenset:
        """Subrecord signatures that are localized strings anywhere in this record type."""
        return frozenset()

    def group_rank(self, signature: str) -> int:
        try:
            return self.native_group_order.index(signature)
        except ValueError:
            return len(self.native_group_order)

    def __repr__(self):
        return f'<GameAdapter {self.name}>'
