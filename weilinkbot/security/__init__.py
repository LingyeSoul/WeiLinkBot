"""Security framework for WeiLinkBot Agent.

Provides pre-execution tool-call guarding to detect dangerous patterns
before the agent executes them. Referenced from QwenPaw's security architecture.

Components:
  - ToolGuardEngine: orchestrator that runs all guardians
  - RuleBasedGuardian: YAML regex-signature matching on parameters
  - FilePathGuardian: blocks access to sensitive file paths
"""

from .tool_guard import ToolGuardEngine, GuardResult, GuardFinding
