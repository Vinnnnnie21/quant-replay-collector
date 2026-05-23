1. 开发运行：双击“开始.bat”。脚本会先检查依赖，缺少依赖时自动执行 pip install -r requirements.txt
2. 打包 EXE：在 Windows 下双击“build_windows.bat”
3. 程序主入口：main_app.py
4. 数据库默认路径：data/quant_replay.db
5. 导出目录默认路径：data/exports/
6. 点击“加载/刷新”会优先联网刷新K线；网络失败时会自动回退到同日期缓存。
7. 导出文件中 event_features/event_wide 默认用于建模输入，不含未来收益或 post_* 窗口；完整版本保存在 event_features_full/event_wide_full，标签保存在 event_labels。
8. 当前交易为回放模拟成交，支持成交价模式、手续费、滑点和每笔名义金额；不接入 Binance 实盘下单 API。
9. 导出会包含 account_equity、performance_summary、event_study_summary、ml_features、ml_labels、sample_index，用于复盘、事件研究和后续建模。
10. 自检脚本：python self_check.py。测试基线：在项目根目录运行 python -m pytest -q。
