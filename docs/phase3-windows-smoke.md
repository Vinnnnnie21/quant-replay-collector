# Phase 3 Windows desktop smoke check

这份清单必须在真实 Windows 桌面会话执行。offscreen pytest 通过不能替代显卡驱动、缩放和窗口管理器验证。

## 固定输入

- 解释器：`D:\Trading\.venv\Scripts\python.exe`
- K 线：至少 270,000 根连续 1 分钟数据
- seed：`20260713`
- 记录：CPU、内存、Windows 版本、GPU、显卡驱动、显示器数量、缩放比例、应用版本

## 操作

1. 启动应用。从进程创建开始计时，到主窗口第一次能响应按钮或拖动为止，记录秒数。
2. 加载至少 270,000 根 1 分钟 K 线。加载期间连续拖动窗口，并点击一个不改变业务状态的控件，确认窗口仍处理事件。
3. 加载过程中切换一次周期。旧请求结束后不得覆盖最新周期的状态和图表。
4. 在加载、分析、导出和日常备份各阶段分别尝试关闭。窗口应显示“正在安全保存任务”，等待安全点，不得强制退出。
5. 任务正常结束后，确认按钮、状态栏、回放和多周期上下文恢复可用。
6. 在同一进程内重复打开/关闭相关窗口或重建主布局至少 20 次。记录是否出现 pyqtgraph/Qt access violation、退出码和 Windows 事件查看器条目。
7. 导出一次。确认严格质量门仍拒绝脏数据，成功导出包含 manifest、质量报告、seed、模拟次数、资源预算和批次元数据。
8. 再次运行相同 seed/config 的 benchmark，确认 data hash 和 research hash 不变。

## 记录模板

```text
执行时间：
机器：
Windows / GPU / 驱动：
显示器 / 缩放：
应用版本：
首次可交互时间：
270,000 根加载耗时：
加载中 heartbeat：通过 / 失败
stale 请求：通过 / 失败
四类任务关闭：通过 / 失败
同进程布局重建次数：
access violation：未复现 / 已复现（附退出码和事件日志）
导出审计字段：通过 / 失败
数据 hash：
研究 hash：
备注：
```

## V1.5.1 验收记录（2026-07-15）

```text
执行时间：2026-07-15
机器：AMD64，32 logical CPUs，16,844,886,016 bytes physical memory
Windows：Windows 11 10.0.26200
应用版本：1.5.1
自动 270,000-bar 基准：通过；报告位于 .scratch/phase3-benchmark-v151-final
Qt heartbeat：自动 worker 基准通过
data hash：f7710c043be97ce62245f9c9c934b31f105f94ee17951d60ad442b672fa3a936
research hash：f8f2620ec49c6a6786425b6f8e16556add3ffa5a8cb860a0af1e1802f2cd67f2
真实可见桌面 smoke：待执行
未执行原因：桌面自动化连接连续两次 60 秒、一次 120 秒初始化超时；未获得可控制桌面会话。
native access violation：一次默认全量测试在 test_theme_system.py 的 PlotItem.__init__ 复现；
  随后的 1,024-test 精确前缀和完整全量重跑通过，仍属于未关闭的间歇性风险。
备注：offscreen pytest 和自动 benchmark 不记作真实桌面通过。
```
