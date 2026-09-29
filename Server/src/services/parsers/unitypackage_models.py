"""
UnityPackage Data Models

Defines the core data structures for representing .unitypackage contents:
asset types, individual asset metadata, and package-level summary information.

All models are zero-dependency (standard library only), using dataclasses
and enums to align with the existing codebase style.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class AssetType(Enum):
    """Classification of an asset found inside a .unitypackage.

    Detection strategy (dual-path):
        1. Extension hint from ``pathname`` (e.g. .mat → MATERIAL)
        2. Magic-byte / content-prefix verification on ``asset`` bytes
    """

    YAML_ASSET = auto()       # .mat / .asset / .unity / .prefab  (starts with %YAML)
    SHADER = auto()           # .shader  (UTF-8 BOM + "Shader "...)
    CSHARP_SCRIPT = auto()    # .cs  (UTF-8 BOM + using/namespace/class)
    TEXTURE = auto()          # .png / .jpg / .tga  (PNG/JPEG magic bytes)
    JSON_CONFIG = auto()      # .json / .txt  plain text
    FOLDER = auto()           # directory entry (has .meta + pathname, NO asset file)
    FONT = auto()             # .ttf / .otf / .ttc  font files
    MESH = auto()             # .fbx / .obj / .mesh  external binary models
    AUDIO = auto()            # .wav / .mp3 / .ogg  audio clips
    BINARY = auto()           # unrecognised binary blob
    UNKNOWN = auto()          # ultimate fallback


# ── Text asset types (safe to decode as UTF-8) ──

TEXT_ASSET_TYPES: frozenset[AssetType] = frozenset({
    AssetType.YAML_ASSET,
    AssetType.SHADER,
    AssetType.CSHARP_SCRIPT,
    AssetType.JSON_CONFIG,
})

# ── Extension → AssetType heuristic ──

_EXTENSION_MAP: dict[str, AssetType] = {
    # YAML-based Unity assets
    ".mat":    AssetType.YAML_ASSET,
    ".asset":  AssetType.YAML_ASSET,
    ".unity":  AssetType.YAML_ASSET,
    ".prefab": AssetType.YAML_ASSET,
    ".physicMaterial": AssetType.YAML_ASSET,
    ".physicMaterial2D": AssetType.YAML_ASSET,

    # Shaders
    ".shader":     AssetType.SHADER,
    ".shadergraph": AssetType.SHADER,
    ".shadersubgraph": AssetType.SHADER,
    ".compute":    AssetType.SHADER,
    ".hlsl":       AssetType.SHADER,
    ".cginc":      AssetType.SHADER,
    ".glslinc":    AssetType.SHADER,

    # Scripts
    ".cs": AssetType.CSHARP_SCRIPT,

    # Textures
    ".png":  AssetType.TEXTURE,
    ".jpg":  AssetType.TEXTURE,
    ".jpeg": AssetType.TEXTURE,
    ".tga":  AssetType.TEXTURE,
    ".tif":  AssetType.TEXTURE,
    ".tiff": AssetType.TEXTURE,
    ".bmp":  AssetType.TEXTURE,
    ".psd":  AssetType.TEXTURE,
    ".gif":  AssetType.TEXTURE,
    ".exr":  AssetType.BINARY,
    ".hdr":  AssetType.TEXTURE,

    # JSON / config
    ".json": AssetType.JSON_CONFIG,
    ".txt":  AssetType.JSON_CONFIG,
    ".csv":  AssetType.JSON_CONFIG,
    ".xml":  AssetType.JSON_CONFIG,
    ".html": AssetType.JSON_CONFIG,
    ".md":   AssetType.JSON_CONFIG,

    # Fonts
    ".ttf": AssetType.FONT,
    ".otf": AssetType.FONT,
    ".ttc": AssetType.FONT,

    # Audio
    ".wav":  AssetType.AUDIO,
    ".mp3":  AssetType.AUDIO,
    ".ogg":  AssetType.AUDIO,
    ".aiff": AssetType.AUDIO,
    ".flac": AssetType.AUDIO,

    # 3D Meshes
    ".fbx":  AssetType.MESH,
    ".obj":  AssetType.MESH,
    ".mesh": AssetType.MESH,
    ".blend": AssetType.MESH,

    # Other known binaries
    ".dll":    AssetType.BINARY,
    ".so":     AssetType.BINARY,
    ".bundle": AssetType.BINARY,
    ".assetbundle": AssetType.BINARY,
    ".anim":   AssetType.BINARY,
    ".controller": AssetType.BINARY,
    ".overrideController": AssetType.BINARY,
    ".playable": AssetType.BINARY,
    ".mask":   AssetType.BINARY,
}

# ── Magic bytes → AssetType verification ──

# Threshold: read up to this many bytes for type detection
_MAGIC_READ_SIZE = 256


def detect_asset_type(
    ext: str,
    content_bytes: bytes | None = None,
    is_folder: bool = False,
) -> AssetType:
    """Detect the asset type via extension hint + content verification.

    Args:
        ext: Lowercase file extension including dot (e.g. ``".mat"``, ``""``).
        content_bytes: First ``_MAGIC_READ_SIZE`` bytes of the ``asset`` file, or None.
        is_folder: True when the entry is a directory (has pathname but NO asset file).

    Returns:
        The best-guess ``AssetType``.
    """
    # ── Folder first ──
    if is_folder:
        return AssetType.FOLDER

    # ── Extension hint as base ──
    base_type = _EXTENSION_MAP.get(ext, AssetType.UNKNOWN)

    # ── Content-based correction ──
    if content_bytes is not None and len(content_bytes) > 0:
        magic_type = _detect_by_magic(content_bytes)
        # If magic disagrees with extension hint and magic isn't UNKNOWN → trust magic
        if magic_type != AssetType.UNKNOWN and magic_type != base_type:
            return magic_type

    return base_type


def _detect_by_magic(data: bytes) -> AssetType:
    """Classify bytes by magic number / content prefix.

    Args:
        data: First bytes of the asset file.

    Returns:
        ``AssetType`` determined from content, or ``UNKNOWN`` on no match.
    """
    # ── YAML ──
    if data[:5] == b"%YAML":
        return AssetType.YAML_ASSET

    # ── Text with UTF-8 BOM ──
    if data[:3] == b"\xef\xbb\xbf":
        # Strip BOM and look at the text
        text = data[3:].decode("utf-8", errors="replace")

        if text.lstrip().startswith("Shader "):
            return AssetType.SHADER
        if text.lstrip().startswith("using ") or text.lstrip().startswith("namespace "):
            return AssetType.CSHARP_SCRIPT
        if "MonoBehaviour" in text[:300] or "GameObject" in text[:300]:
            return AssetType.YAML_ASSET
        # Any other UTF-8 BOM text → heuristic
        if text.strip():
            first_word = text.split(maxsplit=1)[0] if text.split() else ""
            if first_word in ("using", "namespace", "class", "public", "private",
                              "internal", "protected", "static", "sealed"):
                return AssetType.CSHARP_SCRIPT
        return AssetType.JSON_CONFIG

    # ── Image magic ──
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return AssetType.TEXTURE
    if data[:2] == b"\xff\xd8":
        return AssetType.TEXTURE
    if data[:4] == b"RIFF":
        # WAV audio (RIFF...WAVE) or WEBP
        if data[8:12] == b"WEBP":
            return AssetType.TEXTURE
        return AssetType.AUDIO
    if data[:3] == b"GIF":
        return AssetType.TEXTURE
    if data[:4] == b"BM\x00":
        return AssetType.TEXTURE

    # ── Audio ──
    if data[:3] == b"ID3":   # MP3 with ID3 tag
        return AssetType.AUDIO
    if data[:2] == b"\xff\xfb" or data[:2] == b"\xff\xf3":  # MPEG frame
        return AssetType.AUDIO
    if data[:4] == b"OggS":
        return AssetType.AUDIO
    if data[:4] == b"fLaC":
        return AssetType.AUDIO

    # ── Font magic ──
    if data[:4] == b"\x00\x01\x00\x00" or data[:4] == b"true" or data[:4] == b"OTTO":
        return AssetType.FONT

    # ── Compressed / archive ──
    if data[:2] == b"\x1f\x8b":
        return AssetType.BINARY  # gzip
    if data[:2] == b"PK":
        return AssetType.BINARY  # zip

    # ── Plain text (ASCII/UTF-8, no BOM) ──
    try:
        text = data.decode("utf-8", errors="strict")
        if text.lstrip().startswith("%YAML"):
            return AssetType.YAML_ASSET
        if text.lstrip().startswith("Shader "):
            return AssetType.SHADER
        # Heuristic: many alphabetic chars → likely text
        alpha_ratio = sum(1 for c in text if c.isalpha()) / max(len(text), 1)
        if alpha_ratio > 0.5:
            return AssetType.JSON_CONFIG
    except UnicodeDecodeError:
        pass

    return AssetType.UNKNOWN


def is_text_asset(asset_type: AssetType) -> bool:
    """Return True if this asset type's content can be decoded as text."""
    return asset_type in TEXT_ASSET_TYPES


def extension_from_path(filepath: str) -> str:
    """Extract lowercase extension from a pathname.

    Args:
        filepath: Original asset path (e.g. ``Assets/Materials/My Shader.shader``).

    Returns:
        Lowercase extension with dot, or ``""`` if none.
    """
    import os
    return os.path.splitext(filepath)[1].lower()


# ── Dataclasses ──


@dataclass
class UnityPackageAsset:
    """Metadata for a single asset inside a .unitypackage."""

    guid: str
    """32-character MD5 hex hash directory name (asset GUID)."""

    original_path: str
    """Reconstructed original asset path from the ``pathname`` file."""

    asset_type: AssetType
    """Classified asset type."""

    size: int
    """Size of the ``asset`` file in bytes. 0 for folders."""

    has_preview: bool = False
    """True when the hash directory contains a ``preview.png`` file."""

    content_preview: str = ""
    """For text assets: first 500 characters of decoded content."""


@dataclass
class UnityPackageInfo:
    """Summary statistics for a parsed .unitypackage."""

    file_path: str
    """Absolute path to the .unitypackage on disk."""

    total_assets: int = 0
    """Number of non-folder asset entries."""

    total_folders: int = 0
    """Number of folder-only entries."""

    total_size: int = 0
    """Sum of all ``asset`` file sizes in bytes."""

    total_entries: int = 0
    """Raw tar member count (for diagnostics)."""

    classification: dict[str, int] = field(default_factory=dict)
    """Count per AssetType name (e.g. {'CSHARP_SCRIPT': 5, 'TEXTURE': 12})."""


def classification_counts(
    assets: list[UnityPackageAsset],
) -> dict[str, int]:
    """Build a ``{AssetType.name: count}`` dict from a list of assets.

    Args:
        assets: Parsed asset list.

    Returns:
        Classification summary dict.
    """
    counts: dict[str, int] = {}
    for a in assets:
        name = a.asset_type.name
        counts[name] = counts.get(name, 0) + 1
    return counts
