"""Scenes: placed objects as Python, compiled into plugin records (Phase 5)."""
from .compile import CompileResult, ExistingCell, NewInteriorCell, SceneLock, compile_scene
from .diff import SceneDiff, diff_scenes
from .graph import Blueprint, Link, Scene, SceneNode
from .spatial import Box, SpatialIndex
from .transform import Transform, euler_to_matrix, matrix_to_euler
from .capture import capture_cell, cell_references
from .runtime import ConversionReport, RuntimeCapture, RuntimeForm, RuntimeRef
