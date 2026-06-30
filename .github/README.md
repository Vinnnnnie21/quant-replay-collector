# GitHub Actions Workflow 修复

本次提交添加了缺失的 GitHub Actions workflow 配置文件。

## 新增文件

- `.github/workflows/test.yml` - CI/CD 配置
- `.gitattributes` - Git 属性配置
- `verify_before_push.bat` - 本地验证脚本

## 使用说明

推送前建议运行本地验证：

```powershell
.\verify_before_push.bat
```

该脚本会执行与 GitHub Actions 相同的检查步骤。

## 参考

详细的发布流程请参考 `docs/release.md`
