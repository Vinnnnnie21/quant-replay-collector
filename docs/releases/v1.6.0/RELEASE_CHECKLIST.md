# v1.6.0 发布门禁

发布日期：2026-07-21。正式发布前所有阻断项必须有命令输出、文件、哈希或截图证据。

## 版本与仓库

- [x] 唯一版本来源为 `quant_collector_app/version.py`，值为 `1.6.0`。
- [x] UI、导出和 manifest 从同一版本来源读取。
- [x] Windows 文件版本由脚本生成，值为 `1.6.0.0`。
- [x] 最终代码审查后的 `git diff --check` 通过；提交前再复核暂存区。
- [x] 源码、文档和 clean release 的敏感信息、用户数据和大文件扫描通过。
- [ ] 本地提交、`v1.6.0` annotated tag 和远端分叉检查完成。

## 数据安全

- [x] 真实数据整理前清单和关键数据库 SHA-256 已记录。
- [x] schema 19 数据库只使用系统临时副本执行启动自检。
- [x] schema 6 → 当前 schema 使用合成数据库测试。
- [x] 整理后受保护目录文件数和字节数与基线一致，主数据库 SHA-256 不变。
- [x] clean release 确认不含数据库、缓存、日志、备份、导出或本机绝对路径；正式 Windows 包构建后再复核。

## 自动测试

- [x] 整理前默认测试：1,716 passed，10 deselected。
- [x] 整理前性能测试：8 passed，1,718 deselected。
- [x] 分类移动未减少测试；发布回归新增后为 246 个文件、默认收集 1,745（总计 1,755，10 个按标记排除）。
- [x] 整理后 `compileall`、`pip check`、core/gui/all 自检通过。
- [x] 整理后默认 pytest：1,745 passed，10 deselected，257.59 秒。
- [x] performance：8 passed；Qt native 单独 1 passed；安全关闭包含在默认全集；clean release 通过。

## 文档与界面

- [x] README 已改为 v1.6.0 中文入口。
- [x] `docs/USER_GUIDE_v1.6.0.md` 已覆盖安装、回放、开/平仓研究、备份和风险。
- [x] 深浅主题决策研究截图由合成数据库生成。
- [ ] 正式 EXE、窗口、Alt+Tab、任务栏和快捷方式图标完成原生可见验证。

## 正式包

- [ ] `quant_collector_app/build_windows.bat` 成功。
- [ ] 非项目目录、带空格目录和中文目录原生启动—关闭通过。
- [ ] 临时 schema 19 数据库副本启动通过。
- [ ] 数据分析、开仓研究、平仓研究和版本报告可打开。
- [ ] manifest 标记原生启动通过并覆盖正式文件清单。
- [ ] `QRC-v1.6.0-Windows-x64.zip` 原子生成，大小和 SHA-256 已记录。

## 发布

- [x] `$code-review-skill` 无 blocking 或 important 遗留；发现的 Windows 路径安全问题均有红灯测试并已修复。
- [ ] 代码和标签已无强制操作地推送到 GitHub。
- [ ] GitHub Release 不是 draft，也不是 prerelease。
- [ ] 远端资产 SHA-256 与本地一致。
- [ ] README、教程和发布说明链接可访问。
- [ ] 桌面快捷方式 dry-run、更新和实际启动验证完成。
