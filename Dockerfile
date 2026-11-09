FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV LLM_PLANNER=true

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8765
# Render/Railway 会注入 PORT；本地默认 8765
CMD ["sh", "-c", "python run.py --host 0.0.0.0 --port ${PORT:-8765}"]
