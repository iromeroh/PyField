"""Game-agnostic binary core: format specs, lazy nodes, index, FormKeys, plugin container."""
from .format import FormatSpec
from .groups import GroupLayout
from .header import HeaderScheme
from .formids import FormIdCodec, FormKey, MasterRef, Unresolved
from .index import RecordIndex
from .nodes import GroupNode, RecordNode
from .plugin import Plugin
from .subrecords import Subrecord
