# v1.6.0 目录整理记录

记录日期：2026-07-21。工作区：`D:\Trading`。

本轮整理只处理可再生测试产物、发布产物和测试文件分类。源码、正式测试、正式文档、Git 元数据、真实数据库、行情、交易记录、研究结果、导出和备份均不因“整理”删除。

## 整理前审计

| 类别 | 位置或识别方式 | 处理 |
| --- | --- | --- |
| 正式源码 | `quant_collector_app/**/*.py` | 保留 |
| 正式测试 | `tests/test_*.py`，共 242 个文件 | 全部保留并分类 |
| 正式文档 | `README.md`、`CONTEXT.md`、`docs/**` | 保留；补充正式版文档 |
| 构建/发布脚本 | `quant_collector_app/build_windows.bat`、`scripts/**` | 保留；按正式版更新 |
| 用户数据 | `quant_collector_app/data`、`data`、`exports` | 保护，不删除、不迁移、不写入测试 |
| 数据库备份 | `backups`、`Backup` | 保护，不删除、不移动 |
| 当前发布产物 | `quant_collector_app/dist` | 整理前不存在正式包 |
| 可再生构建产物 | `dist`、`build`、`performance_reports` | 发布门禁完成后按路径逐项处理 |
| 测试临时文件 | `.test-artifacts`、根目录 `.pytest_tmp_*` | 只删除通过边界检查且 ACL 允许的目标 |
| 缓存 | `__pycache__`、`.pyc`、pytest cache | 可再生；发布包排除 |
| 疑似废弃文件 | 无已确认源码文件 | 不删除 |
| 无法确认用途 | 所有未跟踪 v1.6 源码和文档 | 视为既有用户资产，保留 |

## 受保护数据基线

聚合哈希按“相对路径、大小、文件 SHA-256”的稳定清单计算。目录整理完成后必须重新计算并对比。

| 绝对路径 | 文件数 | 总大小（字节） | 聚合 SHA-256 | 处理 |
| --- | ---: | ---: | --- | --- |
| `D:\Trading\quant_collector_app\data` | 629 | 575,536,844 | `9118CE5EF6372E9C018F5360FFFF7ADCF2FD9FFC0AAC4CC3BDA984B16649B9AD` | 保护 |
| `D:\Trading\data` | 0 | 0 | 空清单标准 SHA-256 | 保护 |
| `D:\Trading\backups` | 52 | 2,146,041,856 | `BB8D96E440673F7D3D17BAA468C2C2F0F3D4816B6B3EBBFA67EE6EFB35540334` | 保护 |
| `D:\Trading\Backup` | 166 | 6,508,570 | `5994F1FFD8D08BB917F5CF3FEED7A44C3DF089D0D6C07307AC15A4A8F4FAF128` | 保护 |
| `D:\Trading\exports` | 0 | 0 | 空清单标准 SHA-256 | 保护 |

主数据库 `D:\Trading\quant_collector_app\data\quant_replay.db`：189,095,936 字节，schema 19，SHA-256 `B258FA31373DF2E8B2830AA6B2E2B8EEFE690D8CA411E3634F45CC6FEB32D29F`。当前 schema 启动检查使用系统临时目录中的只读副本，副本检查后删除。

## 已删除目标

删除前均执行 `Resolve-Path`，确认绝对路径位于 `D:\Trading` 且名称为明确测试临时目录。

| 原路径 | 原因 | 引用检查 | 回归 |
| --- | --- | --- | --- |
| `D:\Trading\.pytest_tmp_candidate_green1` | 已完成测试留下的可再生临时目录 | Git 未跟踪；不被 import、构建、测试或文档引用 | 默认测试收集数不变 |
| `D:\Trading\.pytest_tmp_candidate_related1` | 已完成测试留下的可再生临时目录 | Git 未跟踪；不被 import、构建、测试或文档引用 | 默认测试收集数不变 |

另有 301 个旧 `.pytest_tmp_*` 目录因 Windows ACL 返回 `WinError 5`。按发布约束保留，不提权、不改所有者。它们被 `.gitignore`、pytest `norecursedirs` 和 clean-release 规则排除，不进入 Git 或正式包。新的 pytest 运行不再复用固定目录，而是使用 `.test-artifacts/pytest-tmp-run-<pid>-<uuid>`；清理器只识别明确前缀，并拒绝符号链接和 Windows junction。

## 测试分类移动

移动前后测试文件均使用 `test_*.py`。已跟踪文件使用 `git mv`；未跟踪的既有 v1.6 测试移动到同一分类后继续收集。没有测试被放入停用目录，也没有为了缩短耗时删除断言。

| 原路径 | 新路径 | 文件数 | 分类理由 | 验证 |
| --- | --- | ---: | --- | --- |
| `tests/test_*.py`（界面与主窗口） | `tests/gui/test_*.py` | 45 | PySide6 组件、窗口状态、主题与布局 | 369 passed |
| `tests/test_*.py`（跨层用例） | `tests/integration/test_*.py` | 26 | controller/service/export/会话/后台任务跨层行为 | 217 passed |
| `tests/test_*.py`（迁移与备份） | `tests/migration/test_*.py` | 4 | schema 和升级前备份 | 28 passed |
| `tests/test_*.py`（性能） | `tests/performance/test_*.py` | 10 | opt-in 性能与 Qt native gate | 8 个 performance 用例通过；默认按标记排除 |
| `tests/test_*.py`（发布） | `tests/release/test_*.py` | 20（整理时） | 自检、路径、图标、打包和 clean release | 98 passed（整理时） |
| `tests/test_*.py`（研究） | `tests/research/test_*.py` | 104 | 特征、盲审、检索、模型、后验和快照 | 754 passed |
| `tests/test_*.py`（存储） | `tests/storage/test_*.py` | 8 | repository、事务、索引和数据版本 | 保留并纳入默认全集 |
| `tests/test_*.py`（聚焦单元） | `tests/unit/test_*.py` | 25 | 纯函数、领域值和小型适配器 | 174 passed |

新增 `tests/helpers/project_paths.py` 作为唯一测试仓库路径解析器，并为各分类目录加入 `__init__.py`。跨测试复用改用完整包导入，避免依赖 pytest 执行顺序或当前目录。

整理前测试文件数 242，默认收集 1,716（总计 1,726，10 个按标记排除）。分类移动本身没有减少测试；发布脚本、图标、路径安全、原生启动门、Qt 生命周期和 CI PowerShell 兼容性回归新增后，测试文件为 246，默认收集 1,746（总计 1,756，10 个按标记排除）。最终默认回归结果为 `1746 passed, 10 deselected in 267.04s`。

## 发布审查修复

- clean-release 只允许替换带本项目生成标记的旧输出，拒绝删除未知目录。
- clean-release、正式 manifest、ZIP 归档、依赖裁剪和测试产物清理均拒绝跟随符号链接或 Windows junction。
- 测试分类后的 Qt native 子进程路径已改为 `tests/performance/test_qt_layout_stress.py`；最终生命周期独立回归 `1 passed in 71.39s`，完整性能集 `8 passed, 1745 deselected in 328.41s`。
- 两份新增产品文档和 Windows smoke 清单已使用仓库相对路径，不再固化本机工作区。

## 保留项目

- `quant_collector_app/data`、`data`、`backups`、`Backup`、`exports`：用户数据或恢复资产。
- 全部未提交 v1.6 源码、ADR、产品文档和测试：此前完成的产品资产。
- ACL 无法删除的旧 pytest 临时目录：不提权处理，明确排除发布包。
- 旧版本发布记录和兼容性测试中的版本号：作为历史语境保留。

## 发布包排除规则

`scripts/check_release_clean.py` 和 `scripts/clean_release.py` 继续排除数据库、行情文件、备份、导出、日志、缓存、`.test-artifacts`、根目录 `.pytest_tmp_*`、本机绝对路径和本地 Agent 文件。正式构建还需在最终包内容清单上再次执行数据与敏感信息扫描。
