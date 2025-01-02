FROM python:3.11.11-slim-bookworm

# 创建并编辑 sources.list 文件
RUN sed -i 's@deb.debian.org@mirrors.aliyun.com@g' /etc/apt/sources.list.d/debian.sources

# 更新软件包列表
RUN apt-get update

WORKDIR /app
COPY ./requirements.txt /app

RUN pip install --no-cache-dir -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

# 安装 Playwright 及其依赖
RUN python -m playwright install --with-deps

COPY . /app

# 设置环境变量
ENV HOST=0.0.0.0
ENV PORT=8888

EXPOSE ${PORT}

# 启动应用
CMD ["python", "main.py"]
