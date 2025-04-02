FROM python:3.11.11-slim-bookworm

# 创建并编辑 sources.list 文件
RUN sed -i 's@deb.debian.org@mirrors.aliyun.com@g' /etc/apt/sources.list.d/debian.sources

# The installer requires curl (and certificates) to download the release archive
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates

# Download the latest installer
ADD https://astral.sh/uv/install.sh /uv-installer.sh

# Run the installer then remove it
RUN sh /uv-installer.sh && rm /uv-installer.sh

# Ensure the installed binary is on the `PATH`
ENV PATH="/root/.local/bin/:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

# 安装 Playwright 及其依赖
RUN uv run python -m playwright install --with-deps

COPY . /app

# 设置环境变量
ENV HOST=0.0.0.0
ENV PORT=8888

EXPOSE ${PORT}

# 启动应用
CMD ["uv", "run", "python", "main.py"]
