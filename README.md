# 晴雨校园助手 · 部署版

第 8 组 / 郑州大学。Python 标准库 Web 服务 + DeepSeek 规划 + 10 个工具 + 6 条工作流。

## Render 部署

1. Render → New Web Service → 连接本仓库
2. Runtime 选 Docker（仓库内有 Dockerfile）
3. 环境变量：
   - `DEEPSEEK_API_KEY`：DeepSeek 密钥
   - `LLM_PLANNER`：`true`
   - `DEEPSEEK_MODEL`：`deepseek-chat`
4. 部署完成后访问 `/api/health`，确认 `planner=LLMPlanner`、`llm_enabled=true`

## 本地运行

```bash
python -m pip install -r requirements.txt
python run.py --host 0.0.0.0 --port 8765
```

打开 http://127.0.0.1:8765 。

> `.env` 不会提交，密钥只放在本地或 Render 环境变量中。
