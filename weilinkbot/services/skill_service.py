"""Skill loading and management service.

Supports both legacy flat .md files and directory-based skills (SKILL.md).
Directory-based skills take precedence when both exist.
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

SKILLS_DIR = Path("workspace/skills")
LEGACY_SKILLS_DIR = Path("data/skills")

_SKILL_FILENAME = "SKILL.md"

# Regex to strip YAML frontmatter between --- markers
_STRIP_FRONTMATTER = __import__("re").compile(
    r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?",
    __import__("re").DOTALL,
)


def migrate_skills() -> None:
    """Migrate skill files from legacy locations to workspace/skills/."""
    legacy = LEGACY_SKILLS_DIR
    if not legacy.exists():
        return

    target = SKILLS_DIR
    target.mkdir(parents=True, exist_ok=True)

    migrated = 0
    for f in legacy.glob("*.md"):
        dest = target / f.name
        if not dest.exists():
            dest.write_bytes(f.read_bytes())
            f.unlink()
            migrated += 1

    if not any(legacy.iterdir()):
        legacy.rmdir()

    if migrated:
        logger.info("Migrated %d skills from %s to %s", migrated, legacy, target)


@dataclass
class SkillMeta:
    """Metadata for a single skill."""
    name: str
    description: str
    content: str
    source: str = "workspace"  # "workspace" or "builtin"
    available: bool = True
    always: bool = False
    missing_requirements: str = ""


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter using PyYAML. Returns (metadata_dict, body_text)."""
    match = _STRIP_FRONTMATTER.match(text)
    if not match:
        return {}, text
    try:
        meta = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}, text
    if not isinstance(meta, dict):
        return {}, text
    body = text[match.end():].strip()
    return {str(k): v for k, v in meta.items()}, body


def _get_nanobot_meta(metadata: dict) -> dict:
    """Extract nanobot/openclaw metadata block from frontmatter."""
    raw = metadata.get("metadata")
    if isinstance(raw, dict):
        data = raw
    elif isinstance(raw, str):
        try:
            data = __import__("json").loads(raw)
        except (ValueError, TypeError):
            return {}
    else:
        return {}
    if not isinstance(data, dict):
        return {}
    payload = data.get("nanobot", data.get("openclaw", {}))
    return payload if isinstance(payload, dict) else {}


def _check_requirements(meta: dict) -> tuple[bool, str]:
    """Check if skill requirements are met. Returns (available, missing_desc)."""
    requires = meta.get("requires", {})
    if not requires:
        return True, ""

    missing = []
    for cmd in requires.get("bins", []):
        if not shutil.which(cmd):
            missing.append(f"CLI: {cmd}")
    for var in requires.get("env", []):
        if not os.environ.get(var):
            missing.append(f"ENV: {var}")

    return (not missing), ", ".join(missing)


class SkillService:
    """Manages skill files and their enable state.

    Skills can be:
    - Directory-based: workspace/skills/<name>/SKILL.md  (preferred)
    - Flat files:      workspace/skills/<name>.md         (legacy, still supported)

    Directory-based skills take precedence over flat files with the same name.
    """

    def __init__(
        self,
        skills_dir: Path | str = SKILLS_DIR,
        builtin_skills_dir: Path | str | None = None,
    ) -> None:
        self._dir = Path(skills_dir)
        self._builtin_dir = Path(builtin_skills_dir) if builtin_skills_dir else None

    # ── Scanning ──────────────────────────────────────────────

    def _scan_dir_skills(self, base: Path, source: str) -> list[SkillMeta]:
        """Scan a directory for directory-based skills (name/SKILL.md)."""
        if not base.exists():
            return []
        results: list[SkillMeta] = []
        for skill_dir in sorted(base.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / _SKILL_FILENAME
            if not skill_file.exists():
                continue
            text = skill_file.read_text(encoding="utf-8")
            meta, body = _parse_frontmatter(text)
            name = meta.get("name", skill_dir.name)
            description = meta.get("description", "")
            nanobot_meta = _get_nanobot_meta(meta)
            available, missing = _check_requirements(nanobot_meta)
            always = nanobot_meta.get("always", False) or meta.get("always", False)
            results.append(SkillMeta(
                name=name,
                description=description,
                content=body,
                source=source,
                available=available,
                always=always,
                missing_requirements=missing,
            ))
        return results

    def _scan_flat_skills(self, base: Path, source: str, skip_names: set[str]) -> list[SkillMeta]:
        """Scan for legacy flat .md skill files."""
        if not base.exists():
            return []
        results: list[SkillMeta] = []
        for f in sorted(base.glob("*.md")):
            name_from_stem = f.stem
            if name_from_stem in skip_names:
                continue
            text = f.read_text(encoding="utf-8")
            meta, body = _parse_frontmatter(text)
            name = meta.get("name", name_from_stem)
            description = meta.get("description", "")
            results.append(SkillMeta(
                name=name,
                description=description,
                content=body,
                source=source,
            ))
        return results

    def scan(self, filter_disabled: bool = True) -> list[SkillMeta]:
        """Scan all skills (workspace + builtin), workspace overrides builtin."""
        # Workspace directory-based skills
        workspace_skills = self._scan_dir_skills(self._dir, "workspace")
        workspace_names = {s.name for s in workspace_skills}

        # Workspace flat .md files (only if no directory version exists)
        workspace_skills.extend(
            self._scan_flat_skills(self._dir, "workspace", workspace_names)
        )
        workspace_names = {s.name for s in workspace_skills}

        all_skills = list(workspace_skills)

        # Builtin skills (skip names already defined in workspace)
        if self._builtin_dir:
            builtin_skills = self._scan_dir_skills(self._builtin_dir, "builtin")
            builtin_skills = [s for s in builtin_skills if s.name not in workspace_names]
            builtin_flat = self._scan_flat_skills(
                self._builtin_dir, "builtin",
                workspace_names | {s.name for s in builtin_skills},
            )
            all_skills.extend(builtin_skills)
            all_skills.extend(builtin_flat)

        if filter_disabled:
            all_skills = [s for s in all_skills if s.available]

        return all_skills

    # ── Loading ───────────────────────────────────────────────

    def load_skill(self, name: str) -> str | None:
        """Load a skill's full content by name. Searches workspace first, then builtin."""
        roots = [self._dir]
        if self._builtin_dir:
            roots.append(self._builtin_dir)

        for root in roots:
            # Directory-based
            skill_file = root / name / _SKILL_FILENAME
            if skill_file.exists():
                return skill_file.read_text(encoding="utf-8")
            # Flat .md
            flat_file = root / f"{name}.md"
            if flat_file.exists():
                return flat_file.read_text(encoding="utf-8")
        return None

    def load_enabled(self, enabled_names: list[str]) -> str:
        """Load and concatenate content of enabled skills."""
        if not enabled_names:
            return ""
        enabled_set = set(enabled_names)
        parts: list[str] = []
        for skill in self.scan(filter_disabled=False):
            if skill.name in enabled_set and skill.available:
                parts.append(f"### {skill.name}\n{skill.content.strip()}")
        if not parts:
            return ""
        return "\n\n---\n\n".join(parts)

    def build_prompt(self, enabled_names: list[str]) -> str:
        """Return the skill prompt block to inject into system prompt.

        Always-on skills are included automatically. For other enabled skills,
        only the summary (name + description) is injected to save tokens.
        Full content is loaded on-demand via workspace_read.
        """
        all_skills = self.scan(filter_disabled=False)
        enabled_set = set(enabled_names)

        always_parts: list[str] = []
        summary_lines: list[str] = []

        for skill in all_skills:
            if not skill.available:
                continue
            if skill.always:
                always_parts.append(f"### {skill.name}\n{skill.content.strip()}")
            elif skill.name in enabled_set:
                desc = skill.description or skill.name
                summary_lines.append(f"- **{skill.name}** — {desc}")

        sections: list[str] = []
        if always_parts:
            sections.append("### Always-on Skills\n\n" + "\n\n---\n\n".join(always_parts))
        if summary_lines:
            sections.append(
                "### Available Skills\n"
                "The following skills are available. "
                "Use workspace_read to load full content when needed.\n\n"
                + "\n".join(summary_lines)
            )

        if not sections:
            return ""
        return "\n\n## Skills\n\n" + "\n\n".join(sections) + "\n"

    def build_skills_summary(self) -> str:
        """Build a summary of all available skills for context injection."""
        all_skills = self.scan(filter_disabled=False)
        if not all_skills:
            return ""

        lines: list[str] = []
        for skill in all_skills:
            desc = skill.description or skill.name
            status = ""
            if not skill.available:
                status = f" (unavailable: {skill.missing_requirements})"
            elif skill.always:
                status = " (always-on)"
            lines.append(f"- **{skill.name}** — {desc}{status}  [{skill.source}]")
        return "\n".join(lines)

    # ── CRUD ──────────────────────────────────────────────────

    def save(self, name: str, content: str, description: str = "", display_name: str = "") -> None:
        """Create or update a skill. Uses directory-based format."""
        self._dir.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(c for c in name if c.isalnum() or c in "-_").strip()
        if not safe_name:
            raise ValueError("Invalid skill name")

        frontmatter_name = display_name or safe_name
        frontmatter = f"---\nname: {frontmatter_name}\ndescription: {description}\n---\n\n"

        # Save as directory-based skill
        skill_dir = self._dir / safe_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / _SKILL_FILENAME
        skill_file.write_text(frontmatter + content, encoding="utf-8")

        # Remove legacy flat file if it exists
        legacy_flat = self._dir / f"{safe_name}.md"
        if legacy_flat.exists():
            legacy_flat.unlink()

        logger.info("Saved skill: %s", skill_file)

    def delete(self, name: str) -> bool:
        """Delete a skill. Matches by frontmatter name or directory name."""
        self._dir.mkdir(parents=True, exist_ok=True)

        # Try directory-based skill
        for skill_dir in self._dir.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / _SKILL_FILENAME
            if not skill_file.exists():
                continue
            text = skill_file.read_text(encoding="utf-8")
            meta, _ = _parse_frontmatter(text)
            if meta.get("name", skill_dir.name) == name:
                import shutil as _shutil
                _shutil.rmtree(skill_dir)
                logger.info("Deleted skill directory: %s", skill_dir)
                return True

        # Fallback: check flat files
        for f in self._dir.glob("*.md"):
            text = f.read_text(encoding="utf-8")
            meta, _ = _parse_frontmatter(text)
            if meta.get("name", f.stem) == name:
                f.unlink()
                logger.info("Deleted skill file: %s", f)
                return True

        # Fallback: sanitize name
        safe_name = "".join(c for c in name if c.isalnum() or c in "-_").strip()
        if not safe_name:
            return False

        skill_dir = self._dir / safe_name
        if skill_dir.is_dir():
            import shutil as _shutil
            _shutil.rmtree(skill_dir)
            logger.info("Deleted skill directory: %s", skill_dir)
            return True

        flat = self._dir / f"{safe_name}.md"
        if flat.exists() and flat.resolve().is_relative_to(self._dir.resolve()):
            flat.unlink()
            logger.info("Deleted skill file: %s", flat)
            return True

        return False
