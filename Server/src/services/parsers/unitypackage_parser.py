"""
UnityPackage Parser — standalone .unitypackage reader and extractor.

Operates entirely without Unity Editor.  Opens a .unitypackage (tar.gz),
builds a hash→path mapping from ``pathname`` files, detects asset types,
and provides lazy content extraction.

Usage::

    parser = UnityPackageParser("MyPackage.unitypackage")
    for asset in parser.list_assets():
        print(asset.original_path, asset.asset_type.name)
    content = parser.get_content("Assets/Scripts/Foo.cs")
    parser.close()
"""

from __future__ import annotations

import io
import logging
import os
import tarfile
from typing import Any

from services.parsers.unitypackage_models import (
    AssetType,
    UnityPackageAsset,
    UnityPackageInfo,
    classification_counts,
    detect_asset_type,
    extension_from_path,
    is_text_asset,
)

logger = logging.getLogger(__name__)

# ── Constants ──

_CONTENT_PREVIEW_CHARS = 500
"""Number of characters to store in ``UnityPackageAsset.content_preview``."""


class UnityPackageParseError(Exception):
    """Raised when a .unitypackage cannot be parsed (corrupt, missing pathname, etc.)."""


class UnityPackageParser:
    """Read and inspect a .unitypackage (tar.gz) without Unity.

    Lifecycle::

        parser = UnityPackageParser("foo.unitypackage")
        # use parser...
        parser.close()  # or use as context manager

    The class also supports the context-manager protocol::

        with UnityPackageParser("foo.unitypackage") as parser:
            ...

    """

    def __init__(self, filepath: str) -> None:
        """Open a .unitypackage for reading.

        Args:
            filepath: Path to the .unitypackage file.

        Raises:
            FileNotFoundError: If ``filepath`` does not exist.
            UnityPackageParseError: If the file is not a valid tar.gz.
        """
        self._filepath = os.path.abspath(filepath)
        if not os.path.isfile(self._filepath):
            raise FileNotFoundError(f"UnityPackage not found: {self._filepath}")

        try:
            self._tar = tarfile.open(self._filepath, "r:gz")
        except tarfile.ReadError as exc:
            raise UnityPackageParseError(
                f"Cannot open {self._filepath} as tar.gz: {exc}"
            ) from exc

        # Lazy internal state
        self._guid_to_path: dict[str, str] | None = None
        self._assets_cache: list[UnityPackageAsset] | None = None
        self._member_map: dict[str, tarfile.TarInfo] | None = None

        logger.debug("Opened %s (%d tar members)", self._filepath,
                      len(self._tar.getmembers()))

    # ── Context manager support ──

    def __enter__(self) -> UnityPackageParser:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ── Public properties ──

    @property
    def filepath(self) -> str:
        """Absolute path to the .unitypackage on disk."""
        return self._filepath

    # ── Core parsing ──

    def list_assets(self) -> list[UnityPackageAsset]:
        """Enumerate all assets in the package, returning metadata for each.

        Returns:
            List of ``UnityPackageAsset`` items sorted by original_path.

        This call scans all tar members and builds the internal
        hash→path mapping.  Subsequent calls return the cached result.
        """
        if self._assets_cache is not None:
            return self._assets_cache

        path_map = self._read_pathname_mapping()
        self._guid_to_path = path_map

        members = self._tar.getmembers()
        member_lookup: dict[str, tarfile.TarInfo] = {}
        for m in members:
            member_lookup[m.name] = m  # e.g. "abc123...abc123/asset"

        assets: list[UnityPackageAsset] = []

        for guid, original_path in path_map.items():
            asset_path = f"{guid}/asset"
            meta_path = f"{guid}/asset.meta"
            preview_path = f"{guid}/preview.png"

            member = member_lookup.get(asset_path)
            size = member.size if member else 0
            has_preview = preview_path in member_lookup

            is_folder = (asset_path not in member_lookup)
            ext = extension_from_path(original_path)

            # Content-based type detection (read up to 256 bytes)
            content_bytes: bytes | None = None
            if member and size > 0:
                try:
                    f = self._tar.extractfile(member)
                    if f:
                        content_bytes = f.read(_MAGIC_READ_SIZE)
                        f.close()
                except Exception:
                    logger.debug("Could not read preview bytes for %s", guid,
                                 exc_info=True)

            asset_type = detect_asset_type(ext, content_bytes, is_folder=is_folder)

            # Content preview for text assets
            content_preview = ""
            if is_text_asset(asset_type) and content_bytes:
                try:
                    text = _decode_bytes(content_bytes)
                    content_preview = text[:_CONTENT_PREVIEW_CHARS]
                except Exception:
                    pass

            assets.append(UnityPackageAsset(
                guid=guid,
                original_path=original_path,
                asset_type=asset_type,
                size=size,
                has_preview=has_preview,
                content_preview=content_preview,
            ))

        assets.sort(key=lambda a: a.original_path)
        self._assets_cache = assets
        return assets

    def get_asset(self, identifier: str) -> UnityPackageAsset | None:
        """Look up a single asset by GUID or original path.

        Args:
            identifier: 32-char hex GUID, or original path (e.g. ``Assets/Scripts/Foo.cs``).

        Returns:
            Matching ``UnityPackageAsset``, or ``None`` if not found.
        """
        for asset in self.list_assets():
            if asset.guid == identifier or asset.original_path == identifier:
                return asset
        return None

    def get_content(self, identifier: str) -> str | bytes | None:
        """Extract the full content of an asset.

        Args:
            identifier: 32-char hex GUID or original path.

        Returns:
            - ``str`` (decoded UTF-8) for text assets
            - ``bytes`` for binary assets
            - ``None`` if the asset is not found or is a folder

        Raises:
            UnityPackageParseError: If the tar member cannot be read.
        """
        asset = self.get_asset(identifier)
        if asset is None:
            return None
        if asset.asset_type == AssetType.FOLDER:
            return None  # folders have no content

        try:
            f = self._tar.extractfile(f"{asset.guid}/asset")
            if f is None:
                return None
            data = f.read()
            f.close()
        except (KeyError, tarfile.TarError) as exc:
            raise UnityPackageParseError(
                f"Cannot read asset content for {identifier}: {exc}"
            ) from exc

        if is_text_asset(asset.asset_type):
            return _decode_bytes(data)
        return data

    def classify(
        self,
        type_filter: AssetType | None = None,
    ) -> dict[AssetType, list[UnityPackageAsset]]:
        """Group assets by type.

        Args:
            type_filter: If provided, return only that type's list (wrapped in a dict).

        Returns:
            Dict mapping ``AssetType`` → list of assets.
        """
        result: dict[AssetType, list[UnityPackageAsset]] = {}
        for asset in self.list_assets():
            if type_filter is not None and asset.asset_type != type_filter:
                continue
            result.setdefault(asset.asset_type, []).append(asset)
        return result

    def summarize(self) -> UnityPackageInfo:
        """Return a package-level summary with asset counts and total size."""
        assets = self.list_assets()
        folders = sum(1 for a in assets if a.asset_type == AssetType.FOLDER)
        total_size = sum(a.size for a in assets)
        non_folders = len(assets) - folders

        return UnityPackageInfo(
            file_path=self._filepath,
            total_assets=non_folders,
            total_folders=folders,
            total_size=total_size,
            total_entries=len(self._tar.getmembers()),
            classification=classification_counts(assets),
        )

    def extract_text_assets(
        self,
        output_dir: str,
        types: list[AssetType] | None = None,
    ) -> int:
        """Extract text assets to disk, preserving directory structure.

        Args:
            output_dir: Root output directory (created if needed).
            types: Asset types to extract.  Defaults to ``TEXT_ASSET_TYPES``.

        Returns:
            Number of files written.
        """
        from services.parsers.unitypackage_models import TEXT_ASSET_TYPES

        if types is None:
            types = list(TEXT_ASSET_TYPES)

        os.makedirs(output_dir, exist_ok=True)
        count = 0

        for asset in self.list_assets():
            if asset.asset_type not in types:
                continue
            try:
                content = self.get_content(asset.original_path)
            except UnityPackageParseError:
                logger.debug("Skipping %s (read error)", asset.original_path)
                continue
            if content is None:
                continue

            # Preserve relative path under output_dir
            rel_path = _sanitize_path(asset.original_path.lstrip("/"))
            out_path = os.path.join(output_dir, rel_path)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)

            if isinstance(content, str):
                with open(out_path, "w", encoding="utf-8", newline="") as f:
                    f.write(content)
            else:
                with open(out_path, "wb") as f:
                    f.write(content)

            count += 1

        logger.info("Extracted %d text assets to %s", count, output_dir)
        return count

    # ── Internal helpers ──

    def _read_pathname_mapping(self) -> dict[str, str]:
        """Scan tar members for ``<hash>/pathname`` files and build a
        hash→original-path mapping.

        Returns:
            ``{guid: original_path}`` dict.

        Raises:
            UnityPackageParseError: If zero pathname entries are found.
        """
        mapping: dict[str, str] = {}
        for member in self._tar.getmembers():
            parts = member.name.split("/")
            if len(parts) == 2 and parts[1] == "pathname":
                guid = parts[0]
                if len(guid) == 32 and _is_hex(guid):
                    try:
                        f = self._tar.extractfile(member)
                        if f:
                            raw = f.read()
                            f.close()
                            path = raw.decode("utf-8", errors="replace").strip()
                            mapping[guid] = path
                    except Exception as exc:
                        logger.debug("Failed to read pathname for %s: %s", guid, exc)

        if not mapping:
            raise UnityPackageParseError(
                f"No valid pathname entries found in {self._filepath}. "
                f"File may be corrupt or not a .unitypackage."
            )
        return mapping

    def close(self) -> None:
        """Close the underlying tar file.  Safe to call multiple times."""
        if self._tar is not None:
            self._tar.close()
            self._tar = None  # type: ignore[assignment]
            logger.debug("Closed %s", self._filepath)


# ── Private helpers ──


_MAGIC_READ_SIZE = 256


def _is_hex(s: str) -> bool:
    """Return True if *s* consists only of hexadecimal characters."""
    return all(c in "0123456789abcdef" for c in s.lower())


def _decode_bytes(data: bytes) -> str:
    """Decode bytes as UTF-8 text, stripping BOM if present."""
    if data[:3] == b"\xef\xbb\xbf":
        data = data[3:]
    return data.decode("utf-8", errors="replace")


def _sanitize_path(path: str) -> str:
    """Normalise a relative path for safe extraction (no absolute, no ..)."""
    # Normalise separators
    norm = path.replace("\\", "/")
    # Strip leading slashes
    while norm.startswith("/"):
        norm = norm[1:]
    # Strip parent directory traversal
    segments = [s for s in norm.split("/") if s and s != ".."]
    return "/".join(segments)
