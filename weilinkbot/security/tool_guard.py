"""Tool-call guard engine — pre-execution security scanning.

Scans tool parameters before execution to detect dangerous patterns:
command injection, data exfiltration, sensitive file access, etc.

Architecture referenced from QwenPaw security framework.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Severity & Threat Categories
# ---------------------------------------------------------------------------

class GuardSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class GuardThreatCategory(str, Enum):
    COMMAND_INJECTION = "command_injection"
    DATA_EXFILTRATION = "data_exfiltration"
    PATH_TRAVERSAL = "path_traversal"
    SENSITIVE_FILE_ACCESS = "sensitive_file_access"
    NETWORK_ABUSE = "network_abuse"
    CREDENTIAL_EXPOSURE = "credential_exposure"
    RESOURCE_ABUSE = "resource_abuse"
    CODE_EXECUTION = "code_execution"
    PRIVILEGE_ESCALATION = "privilege_escalation"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class GuardFinding:
    """A single security finding."""
    id: str
    rule_id: str
    category: GuardThreatCategory
    severity: GuardSeverity
    title: str
    description: str
    tool_name: str
    param_name: str | None = None
    matched_value: str | None = None
    matched_pattern: str | None = None
    snippet: str | None = None
    remediation: str | None = None


@dataclass
class GuardResult:
    """Aggregated results from guarding a single tool call."""
    tool_name: str
    params: dict[str, Any]
    findings: list[GuardFinding] = field(default_factory=list)

    @property
    def is_safe(self) -> bool:
        return not any(
            f.severity in (GuardSeverity.CRITICAL, GuardSeverity.HIGH)
            for f in self.findings
        )

    @property
    def max_severity(self) -> GuardSeverity:
        if not self.findings:
            return GuardSeverity.INFO
        order = [GuardSeverity.CRITICAL, GuardSeverity.HIGH,
                 GuardSeverity.MEDIUM, GuardSeverity.LOW, GuardSeverity.INFO]
        for sev in order:
            if any(f.severity == sev for f in self.findings):
                return sev
        return GuardSeverity.INFO

    def format_block_reason(self) -> str:
        """Format findings into a human-readable block reason."""
        if self.is_safe:
            return ""
        lines = ["安全守卫拦截了本次操作:"]
        for f in self.findings:
            if f.severity in (GuardSeverity.CRITICAL, GuardSeverity.HIGH):
                lines.append(f"  [{f.severity.value}] {f.title}")
                if f.remediation:
                    lines.append(f"    建议: {f.remediation}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# YAML Rule
# ---------------------------------------------------------------------------

class GuardRule:
    """A single YAML-based guard rule."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.id: str = data["id"]
        raw_tool = data.get("tool", data.get("tools", []))
        self.tools: list[str] = [raw_tool] if isinstance(raw_tool, str) else list(raw_tool or [])
        raw_params = data.get("params", data.get("param", []))
        self.params: list[str] = [raw_params] if isinstance(raw_params, str) else list(raw_params or [])
        self.category = GuardThreatCategory(data["category"])
        self.severity = GuardSeverity(data["severity"])
        self.patterns: list[str] = data.get("patterns", [])
        self.exclude_patterns: list[str] = data.get("exclude_patterns", [])
        self.description: str = data.get("description", "")
        self.remediation: str = data.get("remediation", "")

        self._compiled: list[re.Pattern] = []
        for p in self.patterns:
            try:
                self._compiled.append(re.compile(p, re.IGNORECASE))
            except re.error as e:
                logger.warning("Bad regex in rule %s: %s", self.id, e)

        self._excludes: list[re.Pattern] = []
        for p in self.exclude_patterns:
            try:
                self._excludes.append(re.compile(p, re.IGNORECASE))
            except re.error:
                pass

    def applies_to(self, tool_name: str, param_name: str) -> bool:
        if self.tools and tool_name not in self.tools:
            return False
        if self.params and param_name not in self.params:
            return False
        return True

    def match(self, value: str) -> tuple[re.Match | None, str | None]:
        if any(ep.search(value) for ep in self._excludes):
            return None, None
        for pattern in self._compiled:
            m = pattern.search(value)
            if m:
                return m, pattern.pattern
        return None, None


# ---------------------------------------------------------------------------
# Sensitive file paths
# ---------------------------------------------------------------------------

_SENSITIVE_PATH_PATTERNS: list[re.Pattern] = [
    re.compile(r"(^|[\s/\\])\.env($|[\s\.\\/])", re.I),
    re.compile(r"(^|[\s/\\])\.git($|[\s\\/])", re.I),
    re.compile(r"(^|[\s/\\])\.ssh($|[\s\\/])", re.I),
    re.compile(r"(^|[\s/\\])\.aws($|[\s\\/])", re.I),
    re.compile(r"(^|[\s/\\])\.gnupg($|[\s\\/])", re.I),
    re.compile(r"(^|[\s/\\])\.qwenpaw($|[\s\\/])", re.I),
    re.compile(r"(^|[\s/\\])credentials\.json($|\s)", re.I),
    re.compile(r"\.pem($|\s)", re.I),
    re.compile(r"\.key($|\s)", re.I),
    re.compile(r"(^|[\s/\\])id_rsa", re.I),
    re.compile(r"(^|[\s/\\])id_ed25519", re.I),
    re.compile(r"(^|[\s/\\])\.netrc($|\s)", re.I),
    re.compile(r"(^|[\s/\\])\.npmrc($|\s)", re.I),
    re.compile(r"(^|[\s/\\])\.pypirc($|\s)", re.I),
]


def _check_sensitive_path(value: str) -> bool:
    """Check if a string contains a sensitive file path reference."""
    for pattern in _SENSITIVE_PATH_PATTERNS:
        if pattern.search(value):
            return True
    return False


# ---------------------------------------------------------------------------
# Guard Engine
# ---------------------------------------------------------------------------

_RULES_DIR = Path(__file__).parent / "rules"


class ToolGuardEngine:
    """Orchestrates pre-execution security scanning of tool calls.

    Two guardians:
      1. RuleBasedGuardian — YAML regex rules
      2. FilePathGuardian — sensitive file path blocking
    """

    def __init__(self, rules_dir: Path | None = None) -> None:
        self._rules_dir = rules_dir or _RULES_DIR
        self._rules: list[GuardRule] = []
        self._disabled_rules: set[str] = set()
        self._enabled = True
        self._block_on_critical = True
        self._block_on_high = True
        self._extra_sensitive_paths: list[str] = []
        self._load_rules()
        self._load_config()

    def _load_config(self) -> None:
        """Load security settings from AppConfig."""
        try:
            from weilinkbot.config import get_config
            cfg = get_config().security
            self._enabled = cfg.enabled
            self._block_on_critical = cfg.block_on_critical
            self._block_on_high = cfg.block_on_high
            self._disabled_rules = set(cfg.disabled_rules)
            self._extra_sensitive_paths = list(cfg.custom_sensitive_paths)
        except Exception:
            pass

    def reload_config(self) -> None:
        """Reload config (call after config changes)."""
        self._load_config()

    def _load_rules(self) -> None:
        """Load YAML rules from the rules directory."""
        if not self._rules_dir.is_dir():
            logger.warning("Guard rules directory not found: %s", self._rules_dir)
            return
        for yaml_file in sorted(self._rules_dir.glob("*.yaml")):
            try:
                with open(yaml_file, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if not isinstance(data, list):
                    continue
                for item in data:
                    if isinstance(item, dict):
                        try:
                            self._rules.append(GuardRule(item))
                        except Exception as e:
                            logger.warning("Skipping invalid rule: %s", e)
            except Exception as e:
                logger.warning("Failed to load rules from %s: %s", yaml_file, e)
        logger.info("Loaded %d guard rules", len(self._rules))

    def reload(self) -> None:
        """Reload rules from disk."""
        self._rules.clear()
        self._load_rules()

    def guard(self, tool_name: str, params: dict[str, Any]) -> GuardResult:
        """Scan tool parameters for security violations.

        Returns GuardResult with findings. Check .is_safe before executing.
        """
        result = GuardResult(tool_name=tool_name, params=params)

        # If guard is disabled, return safe
        if not self._enabled:
            return result

        # Guardian 1: YAML rule-based scanning
        for param_name, param_value in params.items():
            value_str = str(param_value) if param_value is not None else ""
            if not value_str:
                continue

            for rule in self._rules:
                if rule.id in self._disabled_rules:
                    continue
                if not rule.applies_to(tool_name, param_name):
                    continue
                m, pattern_str = rule.match(value_str)
                if m:
                    start = max(0, m.start() - 40)
                    end = min(len(value_str), m.end() + 40)
                    result.findings.append(GuardFinding(
                        id=f"GUARD-{uuid.uuid4().hex[:8]}",
                        rule_id=rule.id,
                        category=rule.category,
                        severity=rule.severity,
                        title=f"[{rule.severity.value}] {rule.description}",
                        description=f"Rule {rule.id} matched '{param_name}' of '{tool_name}'",
                        tool_name=tool_name,
                        param_name=param_name,
                        matched_value=m.group(0),
                        matched_pattern=pattern_str,
                        snippet=value_str[start:end],
                        remediation=rule.remediation,
                    ))

        # Guardian 2: Sensitive file path detection
        for param_name, param_value in params.items():
            value_str = str(param_value) if param_value is not None else ""
            if not value_str:
                continue
            if _check_sensitive_path(value_str) or self._check_custom_sensitive(value_str):
                result.findings.append(GuardFinding(
                    id=f"GUARD-{uuid.uuid4().hex[:8]}",
                    rule_id="SENSITIVE_FILE_BLOCK",
                    category=GuardThreatCategory.SENSITIVE_FILE_ACCESS,
                    severity=GuardSeverity.HIGH,
                    title="[HIGH] 访问敏感文件被拦截",
                    description=f"Tool '{tool_name}' attempted to access sensitive file via '{param_name}'",
                    tool_name=tool_name,
                    param_name=param_name,
                    matched_value=value_str[:200],
                    remediation="不要访问 .env/.ssh/.git 等敏感目录",
                ))

        return result

    def _check_custom_sensitive(self, value: str) -> bool:
        """Check custom sensitive paths from config."""
        for path in self._extra_sensitive_paths:
            if path and path.lower() in value.lower():
                return True
        return False

    def get_all_rules(self) -> list[dict[str, Any]]:
        """Return all rules as dicts for the WebUI."""
        rules = []
        for r in self._rules:
            rules.append({
                "id": r.id,
                "severity": r.severity.value,
                "category": r.category.value,
                "description": r.description,
                "disabled": r.id in self._disabled_rules,
                "patterns": r.patterns,
                "remediation": r.remediation,
            })
        return rules
