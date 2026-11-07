# goal-d3（技术实施方案 §4）：agent 执行沙箱镜像。
# 最小运行时：python + node（agent CLI 的宿主）；非 root 运行；工作目录即
# 一次性 tmpfs /workspace（compose 侧挂载，容器销毁随之回收）。
# goal-d4：apt 加装 iptables——egress allowlist 档的助手容器（--net host +
# NET_ADMIN）在本镜像内执行 per-run 白名单规则（agents/sandbox.py EgressPlan）。
# D1=A（2026-11-07 20:08 拍板，见 docs/audit/下一步实施台账-2026-11-07.md §8）：
# 编码 CLI 落在 Windows 宿主侧代理进程空间，本镜像 **不安装 zcode**、
# 不注入 provider/登录态、不放开 egress（#191 实测容器内直跑四重阻断：
# node>=22.5 / provider / 凭据 / network_mode:none）。
# CLI 版本钉定对象改为宿主侧代理（0.17.1 + 二进制 sha256 + provider revision），
# 判据见 docs/试点前联调-iptables与zcodeCLI-检查单.md 二表；真实凭据联调属人工项。
# 本镜像职责：nodejs（其余工具链）+ iptables（EgressPlan per-run 助手容器）。
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs iptables \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /usr/sbin/nologin runner
USER runner
WORKDIR /workspace

# 默认保活命令仅用于 compose 基线验证；真实 run 由服务端以独立容器拉起并
# 显式传命令（--name agent-run-{run_id}，network none，tmpfs /workspace）。
CMD ["sleep", "infinity"]
