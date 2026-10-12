FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# 离线 IP 库（DB-IP City Lite，每月一版）：单独一层，改代码不用重新下载
COPY gw/geo.py ./gw/geo.py
RUN python gw/geo.py fetch /app/geo.mmdb
COPY gw ./gw
ENV PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "-m", "gw.main"]
