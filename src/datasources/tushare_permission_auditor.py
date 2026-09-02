from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config.settings import settings
from src.config.tushare_api_catalog import API_PROBES, TushareApiProbe


BASE_URL = "http://api.tushare.pro"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CAPABILITY_PATH = (
    PROJECT_ROOT / "data" / "system" / "tushare_capabilities.json"
)


class TusharePermissionAuditor:
    def __init__(
        self,
        token: str | None = None,
        capability_path: str | Path | None = None,
        timeout_seconds: int = 30,
    ) -> None:
        self.token = (token or settings.TUSHARE_TOKEN or "").strip()
        if not self.token:
            raise ValueError(
                "TUSHARE_TOKEN 未配置，请检查 D:\\quant_system\\.env"
            )

        self.capability_path = (
            Path(capability_path)
            if capability_path
            else DEFAULT_CAPABILITY_PATH
        )
        self.timeout_seconds = timeout_seconds

    def _raw_call(
        self,
        api_name: str,
        params: dict[str, Any],
        fields: str,
    ) -> dict[str, Any]:
        payload = {
            "api_name": api_name,
            "token": self.token,
            "params": params,
            "fields": fields,
        }

        req = urllib.request.Request(
            BASE_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(
            req,
            timeout=self.timeout_seconds,
        ) as resp:
            text = resp.read().decode("utf-8")

        return json.loads(text)

    @staticmethod
    def _classify(code: Any, msg: str) -> str:
        if code == 0:
            return "AVAILABLE"
        if code == 2002:
            return "NO_PERMISSION"

        lowered = (msg or "").lower()
        if "权限" in (msg or "") or "permission" in lowered:
            return "NO_PERMISSION"

        return "API_ERROR"

    def _build_params(
        self,
        probe: TushareApiProbe,
        probe_date: str,
    ) -> dict[str, Any]:
        params = dict(probe.params)

        if probe.api_name == "trade_cal":
            params.update(
                {
                    "start_date": probe_date,
                    "end_date": probe_date,
                }
            )
        elif probe.api_name in {
            "daily",
            "daily_basic",
            "adj_factor",
            "moneyflow",
            "suspend_d",
            "limit_list_d",
        }:
            params["trade_date"] = probe_date
        elif probe.api_name == "index_daily":
            params.update(
                {
                    "start_date": probe_date,
                    "end_date": probe_date,
                }
            )

        return params

    def audit_one(
        self,
        probe: TushareApiProbe,
        probe_date: str,
    ) -> dict[str, Any]:
        params = self._build_params(
            probe=probe,
            probe_date=probe_date,
        )

        base = {
            **asdict(probe),
            "probe_date": probe_date,
            "tested_params": params,
        }

        try:
            result = self._raw_call(
                api_name=probe.api_name,
                params=params,
                fields=probe.fields,
            )

            code = result.get("code")
            msg = result.get("msg", "") or ""
            data = result.get("data") or {}
            items = data.get("items") or []
            fields = data.get("fields") or []

            return {
                **base,
                "status": self._classify(code, msg),
                "code": code,
                "message": msg,
                "returned_rows": len(items),
                "returned_fields": len(fields),
            }

        except urllib.error.HTTPError as exc:
            return {
                **base,
                "status": "NETWORK_ERROR",
                "code": exc.code,
                "message": f"HTTPError: {exc.reason}",
                "returned_rows": 0,
                "returned_fields": 0,
            }
        except Exception as exc:
            return {
                **base,
                "status": "NETWORK_ERROR",
                "code": None,
                "message": f"{type(exc).__name__}: {exc}",
                "returned_rows": 0,
                "returned_fields": 0,
            }

    def audit_all(
        self,
        probe_date: str,
    ) -> dict[str, Any]:
        results = [
            self.audit_one(
                probe=probe,
                probe_date=probe_date,
            )
            for probe in API_PROBES
        ]

        available = [
            item["api_name"]
            for item in results
            if item["status"] == "AVAILABLE"
        ]
        unavailable = [
            item["api_name"]
            for item in results
            if item["status"] == "NO_PERMISSION"
        ]
        errors = [
            item["api_name"]
            for item in results
            if item["status"] not in {"AVAILABLE", "NO_PERMISSION"}
        ]

        critical_unavailable = [
            item["api_name"]
            for item in results
            if item["critical"]
            and item["status"] != "AVAILABLE"
        ]

        snapshot = {
            "schema_version": 1,
            "audited_at": datetime.now().astimezone().isoformat(),
            "probe_date": probe_date,
            "summary": {
                "tested_count": len(results),
                "available_count": len(available),
                "no_permission_count": len(unavailable),
                "error_count": len(errors),
                "critical_ok": len(critical_unavailable) == 0,
                "available_apis": available,
                "no_permission_apis": unavailable,
                "error_apis": errors,
                "critical_unavailable_apis": critical_unavailable,
            },
            "apis": results,
        }

        self.capability_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.capability_path.write_text(
            json.dumps(
                snapshot,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        return snapshot


def load_tushare_capabilities(
    capability_path: str | Path | None = None,
) -> dict[str, Any] | None:
    path = (
        Path(capability_path)
        if capability_path
        else DEFAULT_CAPABILITY_PATH
    )
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def is_tushare_api_available(
    api_name: str,
    capability_path: str | Path | None = None,
) -> bool | None:
    snapshot = load_tushare_capabilities(capability_path)
    if snapshot is None:
        return None

    for item in snapshot.get("apis", []):
        if item.get("api_name") == api_name:
            return item.get("status") == "AVAILABLE"

    return None
