"""calculate tool — safely evaluate mathematical expressions."""

from __future__ import annotations

import ast
import math
import operator
from typing import Any

from .base import Tool, ToolExecutionError

# Whitelisted binary operators
_SAFE_OPERATORS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

# Whitelisted functions
_SAFE_FUNCTIONS: dict[str, Any] = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "pow": pow,
    "sqrt": math.sqrt,
    "int": int,
    "float": float,
}


def _safe_eval(node: ast.AST) -> float:
    """Recursively evaluate an AST node using only whitelisted operations."""
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)

    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ToolExecutionError(f"Unsupported constant type: {type(node.value).__name__}")

    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _SAFE_OPERATORS:
            raise ToolExecutionError(f"Unsupported operator: {op_type.__name__}")
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        return _SAFE_OPERATORS[op_type](left, right)

    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _SAFE_OPERATORS:
            raise ToolExecutionError(f"Unsupported unary operator: {op_type.__name__}")
        return _SAFE_OPERATORS[op_type](_safe_eval(node.operand))

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ToolExecutionError("Only simple function calls are allowed (no attribute calls)")
        fname = node.func.id
        if fname not in _SAFE_FUNCTIONS:
            raise ToolExecutionError(f"Unsupported function: {fname}")
        args = [_safe_eval(arg) for arg in node.args]
        return _SAFE_FUNCTIONS[fname](*args)

    raise ToolExecutionError(f"Unsupported expression node: {type(node).__name__}")


class CalculateTool(Tool):
    name = "calculate"
    description = (
        "Evaluate a mathematical expression safely. "
        "Supports +, -, *, /, //, **, %, and functions: abs, round, min, max, pow, sqrt. "
        "Example: '2 + 3 * 4', 'sqrt(144)', 'abs(-5) + round(3.7)'"
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "The mathematical expression to evaluate.",
            },
        },
        "required": ["expression"],
        "additionalProperties": False,
    }

    async def execute(self, *, expression: str, **kwargs) -> str:
        expression = expression.strip()
        if not expression:
            raise ToolExecutionError("Expression cannot be empty")

        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as e:
            raise ToolExecutionError(f"Syntax error in expression: {e}")

        # Security: reject any node types we don't explicitly handle
        for node in ast.walk(tree):
            if isinstance(node, (ast.Attribute, ast.Import, ast.ImportFrom,
                                 ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.Assign, ast.AugAssign, ast.NamedExpr,
                                 ast.ListComp, ast.SetComp, ast.DictComp,
                                 ast.GeneratorExp, ast.Lambda, ast.List,
                                 ast.Dict, ast.Set, ast.Tuple)):
                raise ToolExecutionError(f"Disallowed expression element: {type(node).__name__}")

        try:
            result = _safe_eval(tree)
        except ToolExecutionError:
            raise
        except ZeroDivisionError:
            raise ToolExecutionError("Division by zero")
        except Exception as e:
            raise ToolExecutionError(f"Calculation error: {e}")

        # Format: show int result when possible
        if isinstance(result, float) and result == int(result) and not math.isinf(result):
            return f"{expression} = {int(result)}"
        return f"{expression} = {result}"
