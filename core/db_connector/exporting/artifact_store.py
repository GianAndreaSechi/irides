import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from urllib.parse import unquote

import yaml
from loguru import logger

from .markdown import render_markdown
from .models import ExportFormat, ExportOptions
from .okf import render_okf
from .preformatters import essential_record


def sanitize_segment(name: str) -> str:
    """Encode a logical name into a safe, reversible, collision-free path segment."""
    if not isinstance(name, str) or not name or not name.strip():
        raise ValueError("Path segment must be a non-empty string.")
    if name in {".", ".."}:
        raise ValueError(f"Invalid path segment '{name}': relative traversal segments are not allowed.")
    encoded = re.sub(
        r"[^A-Za-z0-9._\-]",
        lambda m: "".join(f"%{b:02X}" for b in m.group(0).encode("utf-8")),
        name,
    )
    if ".." in encoded:
        encoded = encoded.replace("..", "%2E%2E")
    return encoded


def desanitize_segment(segment: str) -> str:
    """Decode a sanitized path segment back into its logical name."""
    return unquote(segment)


def extract_frontmatter(content: str) -> Optional[Dict[str, Any]]:
    """Safely extract YAML frontmatter delimited by standalone '---' lines."""
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    end_idx = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break
    if end_idx is None:
        return None
    frontmatter_text = "\n".join(lines[1:end_idx])
    try:
        parsed = yaml.safe_load(frontmatter_text)
        return parsed if isinstance(parsed, dict) else {}
    except yaml.YAMLError:
        return None


class FileArtifactStore:
    """Writes derived exports separately from canonical metadata."""

    def __init__(self, base_dir: Path | str):
        self.base_dir = Path(base_dir)

    @staticmethod
    def _sanitize(name: str) -> str:
        return sanitize_segment(name)

    def _ensure_confined(self, path: Path) -> Path:
        base_resolved = self.base_dir.resolve()
        target_resolved = path.resolve()
        if not target_resolved.is_relative_to(base_resolved):
            raise ValueError(f"Refusing to access path '{path}' outside export root '{self.base_dir}'.")
        return path

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, delete=False
            ) as temporary:
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            temporary_path.chmod(0o644)
            os.replace(temporary_path, path)
        except Exception:
            if temporary_path is not None and temporary_path.exists():
                try:
                    temporary_path.unlink()
                except OSError:
                    pass
            raise

    def _relative_concept_path(self, record: Dict[str, Any]) -> Path:
        return Path(
            self._sanitize(record["config_name"]),
            self._sanitize(record["instance_name"]),
            self._sanitize(record["schema_name"]),
            f"{self._sanitize(record['table_name'])}.md",
        )

    def _write_okf_index(self, bundle_dir: Path) -> None:
        self._ensure_confined(bundle_dir)
        entries = []
        if bundle_dir.exists():
            for path in sorted(bundle_dir.rglob("*.md")):
                if path.parent == bundle_dir and path.name in {"index.md", "log.md"}:
                    continue
                content = path.read_text(encoding="utf-8")
                frontmatter = extract_frontmatter(content)
                if frontmatter is None:
                    continue
                title = frontmatter.get("title") or desanitize_segment(path.stem)
                description = frontmatter.get("description")
                relative = path.relative_to(bundle_dir).as_posix()
                suffix = f" - {description}" if description else ""
                entries.append(f"* [{title}]({relative}){suffix}")

        body = "\n".join(entries) if entries else "No concepts exported."
        index = f'---\nokf_version: "0.2"\n---\n\n# Database Catalog\n\n{body}\n'
        self._atomic_write(bundle_dir / "index.md", index)

    def rebuild_okf_index(self) -> None:
        """Rebuild the OKF catalog index once (e.g. after a batch export)."""
        bundle_dir = self.base_dir / ExportFormat.OKF.value / "catalog"
        if bundle_dir.exists():
            self._write_okf_index(bundle_dir)

    def export(
        self,
        record: Dict[str, Any],
        options: ExportOptions,
        *,
        rebuild_index: bool = True,
    ) -> None:
        export_record = essential_record(record) if options.preformat else record
        relative_path = self._relative_concept_path(record)

        if options.includes(ExportFormat.MARKDOWN):
            path = self._ensure_confined(
                self.base_dir / ExportFormat.MARKDOWN.value / relative_path
            )
            self._atomic_write(path, render_markdown(export_record))
            logger.info("FileArtifactStore: Saved Markdown export -> {}", path)

        if options.includes(ExportFormat.OKF):
            bundle_dir = self.base_dir / ExportFormat.OKF.value / "catalog"
            path = self._ensure_confined(bundle_dir / relative_path)
            self._atomic_write(path, render_okf(export_record))
            if rebuild_index:
                self._write_okf_index(bundle_dir)
            logger.info("FileArtifactStore: Saved OKF export -> {}", path)

    def export_batch(self, records: Iterable[Dict[str, Any]], options: ExportOptions) -> int:
        """Export multiple records and rebuild the OKF index only once at the end."""
        count = 0
        for record in records:
            self.export(record, options, rebuild_index=False)
            count += 1
        if count > 0 and options.includes(ExportFormat.OKF):
            self.rebuild_okf_index()
        return count
