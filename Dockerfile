# ---- 构建阶段 ----
FROM python:3.12-slim AS builder

WORKDIR /app

# 使用清华镜像加速（中国大陆）
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip install --no-cache-dir uv

COPY pyproject.toml ./
COPY src/ ./src/

# 安装依赖（不含 dev）
RUN uv sync --no-dev --frozen 2>/dev/null || uv sync --no-dev

# ---- 运行阶段 ----
FROM python:3.12-slim AS runner

WORKDIR /app

# 安装运行时系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 从构建阶段复制虚拟环境
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY --from=builder /app/pyproject.toml /app/

# 激活虚拟环境
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

# 默认启动 FastAPI 服务
CMD ["python", "-c", "import sys; print('data-agent container ready'); sys.exit(0)"]
