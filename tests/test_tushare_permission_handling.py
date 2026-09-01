from src.datasources.tushare_provider import TushareProvider
from src.pipelines.tushare_permission_audit_pipeline import build_summary


def test_permission_code_2002_is_permission_error():
    assert TushareProvider._is_permission_error(2002, "") is True


def test_permission_message_is_permission_error():
    assert TushareProvider._is_permission_error(-1, "抱歉，您没有权限访问该接口") is True


def test_normal_api_error_is_not_permission_error():
    assert TushareProvider._is_permission_error(-1, "系统内部错误") is False


def test_permission_audit_summary_degraded():
    results = [
        {"api_name": "daily", "status": "AVAILABLE"},
        {"api_name": "daily_basic", "status": "PERMISSION_DENIED"},
    ]

    summary = build_summary(results)

    assert summary["overall_status"] == "DEGRADED"
    assert summary["permission_denied_apis"] == ["daily_basic"]
    assert summary["unavailable_apis"] == ["daily_basic"]


def test_permission_audit_summary_healthy():
    results = [
        {"api_name": "daily", "status": "AVAILABLE"},
        {"api_name": "daily_basic", "status": "AVAILABLE"},
    ]

    summary = build_summary(results)

    assert summary["overall_status"] == "HEALTHY"
    assert summary["permission_denied_apis"] == []
    assert summary["unavailable_apis"] == []
