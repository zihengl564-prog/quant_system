from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TushareApiProbe:
    api_name: str
    category: str
    purpose: str
    params: dict[str, Any] = field(default_factory=dict)
    fields: str = ""
    permission_mode: str = "unknown"
    min_points: int | None = None
    critical: bool = False


# 说明：
# 1) min_points 仅记录官方文档中明确可确认的门槛；未知项不猜测。
# 2) 独立权限类接口最终以真实 API 返回结果为准。
# 3) probe_date 由审计器运行时注入，因此这里尽量使用稳定的参数模板。
API_PROBES: tuple[TushareApiProbe, ...] = (
    TushareApiProbe(
        api_name="trade_cal",
        category="基础数据",
        purpose="交易日历；数据更新、回测日历依赖",
        params={"exchange": ""},
        fields="exchange,cal_date,is_open,pretrade_date",
        permission_mode="points",
        critical=True,
    ),
    TushareApiProbe(
        api_name="stock_basic",
        category="基础数据",
        purpose="股票主数据；股票池与证券状态依赖",
        params={"exchange": "", "list_status": "L"},
        fields="ts_code,symbol,name,industry,market,list_date,delist_date",
        permission_mode="points",
        critical=True,
    ),
    TushareApiProbe(
        api_name="daily",
        category="行情",
        purpose="A股日线；系统最核心行情源",
        fields="ts_code,trade_date,open,high,low,close,pre_close,vol,amount",
        permission_mode="points",
        min_points=120,
        critical=True,
    ),
    TushareApiProbe(
        api_name="daily_basic",
        category="行情/估值",
        purpose="换手率、市值、估值等日频指标",
        fields="ts_code,trade_date,close,turnover_rate,volume_ratio,pe_ttm,pb,total_mv,circ_mv",
        permission_mode="points",
        min_points=2000,
        critical=True,
    ),
    TushareApiProbe(
        api_name="adj_factor",
        category="复权",
        purpose="复权因子；研究用复权价格依赖",
        fields="ts_code,trade_date,adj_factor",
        permission_mode="points",
        min_points=2000,
        critical=True,
    ),
    TushareApiProbe(
        api_name="index_daily",
        category="指数",
        purpose="沪深300等指数日线；后续 Market Regime 可用",
        params={"ts_code": "000300.SH"},
        fields="ts_code,trade_date,open,high,low,close,vol,amount",
        permission_mode="points",
    ),
    TushareApiProbe(
        api_name="moneyflow",
        category="资金流",
        purpose="个股资金流；可作为后续增强特征",
        fields="ts_code,trade_date,buy_sm_amount,sell_sm_amount,buy_lg_amount,sell_lg_amount,net_mf_amount",
        permission_mode="points",
    ),
    TushareApiProbe(
        api_name="suspend_d",
        category="交易状态",
        purpose="停复牌状态；A股执行约束与回测真实性",
        fields="ts_code,trade_date,suspend_timing,suspend_type",
        permission_mode="points",
    ),
    TushareApiProbe(
        api_name="limit_list_d",
        category="交易状态",
        purpose="涨跌停统计；后续执行约束辅助",
        fields="trade_date,ts_code,name,close,pct_chg,amp,fc_ratio,fd_amount",
        permission_mode="points",
    ),
    TushareApiProbe(
        api_name="namechange",
        category="证券状态",
        purpose="历史名称/ST状态辅助；降低历史股票池偏差",
        params={"ts_code": "000001.SZ"},
        fields="ts_code,name,start_date,end_date,change_reason",
        permission_mode="points",
    ),
)


def get_probe(api_name: str) -> TushareApiProbe | None:
    for probe in API_PROBES:
        if probe.api_name == api_name:
            return probe
    return None
