## 变更内容

<!-- 一句话说清「改了什么」，再补必要的背景 -->

-

## 关联 issue

<!-- 没有就写“无”；有关联用 Closes #123 -->

Closes #

## 验证方式

<!-- 贴关键命令与结论，不要只写“已测试” -->

```bash
cd backend && .venv/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" -v
cd backend && .venv/Scripts/python.exe scripts/smoke_test.py
cd frontend && npm run build
```

## 自查清单

- [ ] 39 个自动化用例全绿（新增逻辑已补用例）
- [ ] 冒烟脚本通过（注册 / 登录 / 建库 / 上传 / 检索 / SSE 问答）
- [ ] 改了 `docs/*.md` 或 README 时已重新生成 `docs/word/*.docx` 并通过 `--check`
- [ ] 改了手写源码时已更新 `scripts/source_to_docx.py` 的 `GROUPS` 与文档中的文件/行数口径
- [ ] 未提交 `.env`、`backend/data/*.db`、`secret.key`、`uploads/`、`*.bak`
- [ ] 未提交 `node_modules/`、`frontend/dist/`、`src-tauri/target/`、`backend/.venv/`
- [ ] 没有无关的整文件格式化 diff（换行由 `.gitattributes` 统一）

## 影响面 / 截图

<!-- 前端改动请贴改动前后截图；接口改动请附请求与响应示例 -->
