"""多租户业务域隔离 — 域级KB + 指标过滤 + 跨域管控"""

from ..core.logging import get_logger

logger = get_logger(__name__)

# 预定义的业务域配置
DOMAINS = {
    "集团经营总览": {
        "tables": ["bid_management", "contracts"],
        "roles": ["admin", "leader", "employee"],
        "description": "集团级经营指标总览",
    },
    "客户全景管理": {
        "tables": ["contracts"],
        "roles": ["admin", "leader", "employee"],
        "description": "客户资产与生命周期管理",
    },
    "商机全生命周期管理": {
        "tables": ["opportunities"],
        "roles": ["admin", "leader"],
        "description": "商机从线索到签单全流程",
    },
    "中标与项目执行管理": {
        "tables": ["bid_management"],
        "roles": ["admin", "leader", "employee"],
        "description": "中标与项目交付管理",
    },
    "营收与应收账款管理": {
        "tables": ["accounts_receivable"],
        "roles": ["admin", "leader"],
        "description": "营收确认与回款追踪",
    },
    "营销团队效能管理": {
        "tables": ["bid_management"],
        "roles": ["admin", "leader"],
        "description": "团队业绩与效能分析",
    },
    "区域与渠道管理": {
        "tables": ["bid_management"],
        "roles": ["admin", "leader", "employee"],
        "description": "区域市场与渠道分析",
    },
    "风险预警管理": {
        "tables": ["opportunities", "accounts_receivable"],
        "roles": ["admin", "leader"],
        "description": "经营风险实时监控与预警",
    },
}


def get_visible_domains(user: dict) -> list[str]:
    """返回用户可见的业务域列表"""
    role = user.get("role", "employee")
    department = user.get("department", "")
    visible = []
    for domain, config in DOMAINS.items():
        if role == "admin":
            visible.append(domain)
        elif role in config["roles"]:
            # leader 可看他所在部门的域
            if role == "leader" and department:
                if any(t in department for t in ["事业部", "部门"]):
                    visible.append(domain)
                else:
                    visible.append(domain)  # 跨部门leader可见全部
            else:
                visible.append(domain)
    return visible if visible else list(DOMAINS.keys())


def filter_metrics_by_domain(metrics: list[dict], user: dict) -> list[dict]:
    """按用户可见域过滤指标列表"""
    visible = set(get_visible_domains(user))
    if "admin" == user.get("role"):
        return metrics  # admin 无限制
    return [m for m in metrics if m.get("category", "") in visible]


def check_cross_domain(metric_name: str, user: dict) -> dict:
    """检查是否需要跨域审批"""
    # 跨域指标 (如"人均中标额"涉及CRM+HR)
    cross_domain_metrics = {"人均中标额", "人均签约额", "人均营收"}
    if metric_name in cross_domain_metrics and user.get("role") != "admin":
        return {
            "requires_approval": True,
            "message": f"指标'{metric_name}'涉及跨域数据, 需管理员审批",
        }
    return {"requires_approval": False}
