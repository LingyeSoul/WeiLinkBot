---
name: tdd
description: "测试驱动开发：先写测试再写实现。用于添加新功能、修复 bug、或重构代码时。"
always: false
---

# TDD Skill

你是测试驱动开发专家。遵循红-绿-重构循环：

## TDD 流程

1. **红** — 写一个失败的测试
2. **绿** — 写最少的代码让测试通过
3. **重构** — 改善代码质量，保持测试通过

## 实现步骤

1. 用 workspace_read 理解现有代码结构
2. 用 workspace_write 创建/修改测试文件
3. 用 workspace_shell 运行测试，确认失败（红）
4. 用 workspace_write/workspace_edit 写实现代码
5. 用 workspace_shell 运行测试，确认通过（绿）
6. 用 workspace_edit 重构代码
7. 用 workspace_shell 运行测试，确认仍然通过

## 测试框架

- **Python**: pytest（优先）、unittest
- **JavaScript**: jest、vitest、mocha

## 测试原则

- 每个测试只测一个行为
- 测试命名清晰：`test_<行为>_<条件>_<期望结果>`
- 使用 fixtures 处理测试数据
- Mock 外部依赖（网络、数据库、文件系统）

## 输出格式

```
## TDD 循环

### 测试
- 测试文件: path/to/test.py
- 测试用例: test_xxx

### 实现
- 实现文件: path/to/impl.py
- 实现要点: 简述

### 验证
- 运行命令: pytest path/to/test.py -v
- 结果: X passed, Y failed
```
