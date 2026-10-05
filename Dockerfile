# JobLander 云端版：每个用户一台 machine 跑这个镜像，/data 是该用户独占的持久卷。
FROM python:3.12-slim

# chromium：简历转 PDF；fonts-noto-cjk：中文简历不出豆腐块
RUN apt-get update \
 && apt-get install -y --no-install-recommends chromium fonts-noto-cjk \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY joblander ./joblander
COPY evals ./evals
RUN pip install --no-cache-dir .

COPY deploy/entrypoint.sh deploy/chromium-headless /usr/local/bin/
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/chromium-headless \
 && useradd --create-home --uid 1000 joblander \
 && mkdir -p /data && chown joblander /data

ENV JOBLANDER_CONFIG=/data/config.yaml \
    JOBLANDER_CHROME=/usr/local/bin/chromium-headless \
    PYTHONUNBUFFERED=1
USER joblander
# 中立工作目录：别让 cwd 里的源码遮住已安装的包
WORKDIR /data
EXPOSE 8899
ENTRYPOINT ["entrypoint.sh"]
