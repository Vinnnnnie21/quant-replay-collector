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
- [x] clean release 和正式 Windows 包复核均不含数据库、缓存、日志、备份、导出或本机绝对路径。

## 自动测试

- [x] 整理前默认测试：1,716 passed，10 deselected。
- [x] 整理前性能测试：8 passed，1,718 deselected。
- [x] 分类移动未减少测试；发布回归新增后为 246 个文件、默认收集 1,746（总计 1,756，10 个按标记排除）。
- [x] 整理后 `compileall`、`pip check`、core/gui/all 自检通过。
- [x] 整理后默认 pytest：1,746 passed，10 deselected，267.04 秒。
- [x] performance：8 passed；Qt native 单独 1 passed；安全关闭包含在默认全集；clean release 通过。

## 文档与界面

- [x] README 已改为 v1.6.0 中文入口。
- [x] `docs/USER_GUIDE_v1.6.0.md` 已覆盖安装、回放、开/平仓研究、备份和风险。
- [x] 深浅主题决策研究截图由合成数据库生成。
- [x] 正式 EXE、窗口和 Alt+Tab 完成原生可见验证；任务栏使用稳定 AppUserModelID，快捷方式绑定包内权威 ICO。任务栏自动隐藏环境下以 Alt+Tab 截图、实际启动和资源测试共同验收。

## 正式包

- [x] `quant_collector_app/build_windows.bat` 从干净提交 `21d910e` 构建成功。
- [x] 非项目目录、带空格目录和中文目录原生启动—关闭通过。
- [x] 临时 schema 19 数据库副本启动通过，源数据库 SHA-256 不变。
- [x] 数据分析、开仓研究、平仓研究和版本报告可打开。
- [x] manifest 标记原生启动通过并覆盖 2,040 个正式文件。
- [x] `QRC-v1.6.0-Windows-x64.zip` 原子生成：144,809,840 字节，SHA-256 `8b87bdcf2d52e04489537b9f7e5b80060d6eccd44ef5d59aa8376cfe66b94929`。

## 发布

- [x] `$code-review-skill` 无 blocking 或 important 遗留；发现的 Windows 路径安全问题均有红灯测试并已修复。
- [ ] 代码和标签已无强制操作地推送到 GitHub。
- [ ] GitHub Release 不是 draft，也不是 prerelease。
- [ ] 远端资产 SHA-256 与本地一致。
- [ ] README、教程和发布说明链接可访问。
- [x] 桌面快捷方式 dry-run、原子更新和实际启动—正常关闭验证完成；目标为 `D:\Trading\quant_collector_app\dist\QRC\QRC.exe`，旧 v1.5.2 EXE 保留。
