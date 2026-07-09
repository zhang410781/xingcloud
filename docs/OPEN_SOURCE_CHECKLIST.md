# 开源发布检查清单

这份清单用于正式公开仓库前做最后检查。

## 必做

- [x] 添加 `LICENSE` 文件，并在 README 中明确开源协议。
- [x] 添加 `NOTICE` 文件。
- [ ] 确认仓库内未保留演示账号、演示数据生成脚本或演示凭据。
- [ ] 确认 `SECRET_KEY`、数据库密码、Redis 地址、云账号、Kubeconfig、SSH 密钥、监控 Token、模型 API Key 未进入仓库。
- [ ] 确认 `backend/config.json`、`.env`、SQLite 数据库、日志、运行目录和构建产物未被 git 跟踪。
- [ ] 运行后端测试：`cd backend && python manage.py test`。
- [ ] 运行前端构建：`cd frontend && npm run build`。
- [ ] 从全新环境执行一次 K8S 部署，确认 README 和 `k8s/XINGHAI_DEPLOY.md` 可复现。
- [ ] 检查 README 图片链接和 docs 链接。

## 当前需要注意

- `backend/runtime/aiops-backend.err.log` 和 `backend/runtime/aiops-backend.out.log` 当前被 git 跟踪；正式开源前建议从版本库中移除。
- 仓库已声明 Apache License 2.0；后续分发或二次开发时请保留 `LICENSE` 和 `NOTICE`。

## 推荐检查命令

```bash
git status --short
git ls-files | rg "(^backend/db\\.sqlite3$|\\.log$|\\.out\\.log$|\\.err\\.log$|config\\.json$|kubeconfig|\\.pem$|\\.key$|secret|token)"
cd backend && python manage.py test
cd frontend && npm run build
```
