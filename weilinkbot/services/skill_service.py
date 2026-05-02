"""Skill loading and management service."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

SKILLS_DIR = Path("data/skills")

_SEPARATORS = ("---\n", "---\r\n")


@dataclass
class SkillMeta:
    name: str
    description: str
    content: str


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse optional YAML frontmatter (key: value lines between --- markers).

    Returns (metadata_dict, body_text). If no frontmatter, returns ({}, text).
    """
    for sep in _SEPARATORS:
        if text.startswith(sep):
            end = text.find(sep, len(sep))
            if end != -1:
                header = text[len(sep):end].strip()
                body = text[end + len(sep):].lstrip("\n")
                meta: dict[str, str] = {}
                for line in header.splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        meta[k.strip()] = v.strip()
                return meta, body
    return {}, text


class SkillService:
    """Manages skill .md files on disk and their enable state."""

    def __init__(self, skills_dir: Path | str = SKILLS_DIR) -> None:
        self._dir = Path(skills_dir)

    def scan(self) -> list[SkillMeta]:
        """Scan skills directory and return metadata for all .md files."""
        self._dir.mkdir(parents=True, exist_ok=True)
        results: list[SkillMeta] = []
        for f in sorted(self._dir.glob("*.md")):
            text = f.read_text(encoding="utf-8")
            meta, body = _parse_frontmatter(text)
            name = meta.get("name", f.stem)
            description = meta.get("description", "")
            results.append(SkillMeta(name=name, description=description, content=body))
        return results

    def load_enabled(self, enabled_names: list[str]) -> str:
        """Load and concatenate content of enabled skills."""
        if not enabled_names:
            return ""
        enabled_set = set(enabled_names)
        parts: list[str] = []
        for skill in self.scan():
            if skill.name in enabled_set:
                parts.append(f"### {skill.name}\n{skill.content.strip()}")
        if not parts:
            return ""
        return "\n\n---\n\n".join(parts)

    def build_prompt(self, enabled_names: list[str]) -> str:
        """Return the skill prompt block to inject into system prompt."""
        body = self.load_enabled(enabled_names)
        if not body:
            return ""
        return f"\n\n## Skills\nThe following specialized skills define additional behavior:\n\n{body}\n"

    def save(self, name: str, content: str, description: str = "") -> None:
        """Create or update a skill .md file."""
        self._dir.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(c for c in name if c.isalnum() or c in "-_").strip()
        if not safe_name:
            raise ValueError("Invalid skill name")
        frontmatter = f"---\nname: {safe_name}\ndescription: {description}\n---\n\n"
        path = self._dir / f"{safe_name}.md"
        path.write_text(frontmatter + content, encoding="utf-8")
        logger.info("Saved skill: %s", path)

    def delete(self, name: str) -> bool:
        """Delete a skill .md file. Returns True if deleted."""
        safe_name = "".join(c for c in name if c.isalnum() or c in "-_").strip()
        if not safe_name:
            return False
        path = self._dir / f"{safe_name}.md"
        if not path.resolve().is_relative_to(self._dir.resolve()):
            return False
        if path.exists():
            path.unlink()
            logger.info("Deleted skill: %s", path)
            return True
        return False
