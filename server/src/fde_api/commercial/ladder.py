"""对外商业编号映射（L0–L4）——**全仓唯一转换入口**（ADR-001 §2.4 / ADR-006）。

纪律（ADR-006 裁决，评审按此否决违例）：

1. 本模块是代码中唯一允许出现「对外 L0–L4 商业编号」字面量与换算逻辑的地方；
   其他任何模块需要对外编号时必须经 ``external_ladder_code`` 读取，不得自带
   换算（静态钉见 tests/test_commercial_entitlements.py 的散落扫描用例）。
2. 对外编号是**展示层推导**，不落第二套权威值域：权威状态只有
   ``CommercialEntitlement`` 上的角色/席位/认证三类字段。
3. 本文件注释中的每个 L 编号都带三要素（哪一套+主语+方向）——对外 L0–L4
   商业编号：衡量**人在组织中的商业层级**（组织职级轴），与
   交付智能化等级（平台，越大越自动化，BP §1.3a，当前 L2+）、
   交付能力等级 ``fde_profiles.level``（人，越大越资深，dispatch 域）、
   降级链状态 ``agent_runs.fallback_level``（单次运行，越大越不自动化）
   互不相干（六套同名家族全表见 ADR-001 §3.2）。

映射规则（拍板口径 §0.4/Q08/Q24；商业名称只在此处出现）：

=========== ============================ ==========================
角色        状态输入                     对外编号（商业名称）
=========== ============================ ==========================
R3 交付者   已认证 ∧ 席位 active         L1（独立 FDE）
R3 交付者   其余                         L0（候选交付者；Q08：L0/L1 同为「交付者」一身份两状态）
R2 创业者   seat_source=bootcamp_mentorship  L3（陪跑营档位，业务名不带 L 编号）
R2 创业者   seat_source=bootcamp_practical   L2（实战营档位，业务名不带 L 编号）
R2 创业者   其余                         None
R4 区域合作商 任意                        L4（区域合作商）
R1 企业     任意                         None（企业不参与对外个人编号体系）
未分层      任意                         None
=========== ============================ ==========================
"""

from __future__ import annotations

from fde_api.commercial.models import CommercialEntitlement

# 对外编号闭集——除本模块与展示层外不得引用（ADR-006 §2.1/§2.3）
EXTERNAL_LADDER_CODES = ("L0", "L1", "L2", "L3", "L4")


def external_ladder_code(entitlement: CommercialEntitlement) -> str | None:
    """从权益权威状态推导对外商业编号；未分层/R1 返回 None。

    纯函数：只读传入行的角色/席位/认证三类字段，零 IO、零推导写入。
    """
    role = entitlement.commercial_role
    if role is None:
        return None
    if role == "R4":
        return "L4"
    if role == "R1":
        return None
    if role == "R2":
        if entitlement.seat_status == "active":
            if entitlement.seat_source == "bootcamp_mentorship":
                return "L3"
            if entitlement.seat_source == "bootcamp_practical":
                return "L2"
        return None
    # R3 交付者：一身份两状态（Q08）——认证+席位=独立状态，否则候选状态
    certified = entitlement.certification_status == "certified"
    seat_active = entitlement.seat_status == "active"
    return "L1" if certified and seat_active else "L0"
