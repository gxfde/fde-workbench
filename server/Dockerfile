# v0.2 (PG 迁移): server 容器化
# ============================================================
# 为什么容器化: PG 在 Docker 网络 automation_qiflow-net 内（别名 twenty-db），
#   WSL 宿主机上解析不了该别名（Docker DNS 只在网络内生效）。
#   把 server 放进同一网络即可用稳定别名连库，不依赖会变的容器 IP，
#   也不需要改 Twenty 的任何配置或暴露 PG 端口到宿主机。
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 系统依赖：psycopg[binary] 自带 libpq，无需额外装；
# 但 cryptography / argon2 等可能需要 build 工具，先装 gcc 再清理。
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.lock ./
RUN pip install --upgrade pip && pip install -r requirements.lock

COPY pyproject.toml ./
COPY src ./src
RUN pip install -e . --no-deps

COPY alembic.ini ./
COPY migrations ./migrations
# P1：种子数据与加载器烘进镜像（docker exec <api> python load_seeds.py 手动灌，不随启动自动跑）
COPY seeds ./seeds
COPY load_seeds.py ./load_seeds.py

# 非 root 运行（审计遗留项）：应用代码 root 装好，运行身份降到专用账号；
# 运行期预建目录属主在镜像里预设，首次新建的卷会继承，存量卷需一次性 chown。
# V31-P3（试点遗留）：.fde-transcript-drafts（转写草稿独立文件根）一并预建——
# 此前缺失导致容器首写 PermissionError，试点期靠运行时 chown 临时修复。
RUN useradd --system --create-home --uid 1001 fde     && mkdir -p /app/.fde-storage /app/.fde-transcript-drafts     && chown -R fde:fde /app/.fde-storage /app/.fde-transcript-drafts /home/fde
USER fde

EXPOSE 8010

# --timeout＝gunicorn worker 静默上限（arbiter 超时即 SIGKILL worker ⇒ 请求落 500）。
# 真模型评估腿（POST /simulation/runs/<id>/evaluate?model_mode=server）单次模型调用
# 上界＝deepseek_timeout_seconds（配置面 ≤300s），瞬时失败同消息重试一次 ⇒ 最坏
# 2×300=600s；原 120s 恒被击穿（真机实测 41–160s ⇒ 必 500，2026-11-18 实弹）。
# 取 660＝2×上界 +60s 余量（连接/解析/审计/落库开销）；静态钉见
# tests/test_deploy_timeout_budget.py（timeout 必须 > 2×AI 超时上界，防再漂移）。
CMD ["gunicorn", "--bind", "0.0.0.0:8010", "--workers", "2", "--timeout", "660", "fde_api.wsgi:app"]
