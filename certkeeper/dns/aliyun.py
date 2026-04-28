"""阿里云 DNS Provider — 通过 Alidns API 管理 TXT 记录。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
import urllib.parse
import uuid

import requests

from certkeeper.dns.base import DnsProvider

logger = logging.getLogger(__name__)


class AliyunDnsProvider(DnsProvider):
    """通过阿里云 Alidns API 创建和删除 DNS TXT 记录。"""

    API_URL = "https://alidns.aliyuncs.com/"

    def validate_config(self) -> list[str]:
        errors: list[str] = []
        if "access_key_id" not in self.config.settings:
            errors.append("access_key_id is required")
        if "access_key_secret" not in self.config.settings:
            errors.append("access_key_secret is required")
        return errors

    @property
    def _access_key_id(self) -> str:
        return str(self.config.settings["access_key_id"])

    @property
    def _access_key_secret(self) -> str:
        return str(self.config.settings["access_key_secret"])

    def create_txt_record(self, domain: str, name: str, value: str) -> None:
        """创建 TXT 记录并等待 DNS 生效。"""
        rr, zone = self._parse_record_name(name, domain)
        logger.info("创建 TXT 记录: RR=%s, Zone=%s, Domain=%s", rr, zone, domain)
        params = {
            "Action": "AddDomainRecord",
            "DomainName": zone,
            "RR": rr,
            "Type": "TXT",
            "Value": value,
        }
        self._call_api(params)
        logger.info("TXT 记录已提交, 等待 DNS 生效: %s", name)
        self._wait_for_propagation(name, value)
        logger.info("DNS 记录已生效: %s", name)

    def delete_txt_record(self, domain: str, name: str, value: str) -> None:
        """查询并删除对应的 TXT 记录。"""
        rr, zone = self._parse_record_name(name, domain)
        record_id = self._find_record_id(zone, rr, "TXT")
        if record_id:
            logger.info("删除 TXT 记录: RR=%s, Zone=%s, RecordId=%s", rr, zone, record_id)
            params = {
                "Action": "DeleteDomainRecord",
                "RecordId": record_id,
            }
            self._call_api(params)
            logger.info("TXT 记录已删除: RecordId=%s", record_id)
        else:
            logger.warning("未找到 TXT 记录: RR=%s, Zone=%s", rr, zone)

    def _parse_record_name(self, full_name: str, domain: str) -> tuple[str, str]:
        """解析完整记录名为 (RR, Zone)。

        通过阿里云 DescribeDomains API 查找匹配的 DNS zone，
        支持子域名场景（如 zone=bqdzz.com.cn, domain=bq.bqdzz.com.cn）。

        例如: _acme-challenge.bq.bqdzz.com.cn → ("_acme-challenge.bq", "bqdzz.com.cn")
        """
        # 从 domain 开始逐步去掉前缀，查询阿里云是否有匹配的 zone
        parts = domain.split(".")
        for i in range(len(parts)):
            candidate_zone = ".".join(parts[i:])
            if self._zone_exists(candidate_zone):
                if full_name.endswith("." + candidate_zone):
                    rr = full_name[: -(len(candidate_zone) + 1)]
                else:
                    rr = full_name
                return rr, candidate_zone
        # 找不到就退回到用原始 domain 作为 zone
        if full_name.endswith("." + domain):
            rr = full_name[: -(len(domain) + 1)]
        else:
            rr = full_name
        return rr, domain

    def _zone_exists(self, zone: str) -> bool:
        """查询阿里云是否存在指定的 DNS zone。"""
        try:
            data = self._call_api({"Action": "DescribeDomains", "KeyWord": zone})
            for d in data.get("Domains", {}).get("Domain", []):
                if d.get("DomainName") == zone:
                    return True
        except Exception:
            pass
        return False

    def _find_record_id(self, zone: str, rr: str, record_type: str) -> str | None:
        """查询指定 RR 和类型的记录 ID。"""
        params = {
            "Action": "DescribeDomainRecords",
            "DomainName": zone,
            "RRKeyWord": rr,
            "TypeKeyWord": record_type,
        }
        data = self._call_api(params)
        records = data.get("DomainRecords", {}).get("Record", [])
        for record in records:
            if record["RR"] == rr and record["Type"] == record_type:
                return record["RecordId"]
        return None

    def _wait_for_propagation(self, name: str, value: str, timeout: int = 60, interval: int = 5) -> None:
        """通过 Google DNS-over-HTTPS 确认 TXT 记录已生效。"""
        deadline = time.time() + timeout
        attempt = 0
        while time.time() < deadline:
            attempt += 1
            try:
                resp = requests.get(
                    "https://dns.google/resolve",
                    params={"name": name, "type": "TXT"},
                    timeout=5,
                )
                for answer in resp.json().get("Answer", []):
                    if answer.get("data", "").strip('"') == value:
                        return
                logger.debug("DNS 查询第 %d 次未命中: %s", attempt, name)
            except Exception as exc:
                logger.debug("DNS 查询第 %d 次失败: %s - %s", attempt, name, exc)
            time.sleep(interval)
        logger.warning("DNS 传播超时 (%ds): %s", timeout, name)

    def _call_api(self, business_params: dict) -> dict:
        """调用阿里云 API，自动签名。"""
        public_params = {
            "Format": "JSON",
            "Version": "2015-01-09",
            "AccessKeyId": self._access_key_id,
            "SignatureMethod": "HMAC-SHA1",
            "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "SignatureVersion": "1.0",
            "SignatureNonce": str(uuid.uuid4()),
        }
        all_params = {**public_params, **business_params}

        sorted_params = sorted(all_params.items())
        query_string = "&".join(
            f"{self._percent_encode(str(k))}={self._percent_encode(str(v))}"
            for k, v in sorted_params
        )
        string_to_sign = "GET&%2F&" + self._percent_encode(query_string)
        signature = base64.b64encode(
            hmac.new(
                (self._access_key_secret + "&").encode("utf-8"),
                string_to_sign.encode("utf-8"),
                hashlib.sha1,
            ).digest()
        ).decode("utf-8")

        all_params["Signature"] = signature
        resp = requests.get(self.API_URL, params=all_params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _percent_encode(s: str) -> str:
        """阿里云 API 要求的 URL 编码规则。"""
        return (
            urllib.parse.quote(s, safe="")
            .replace("+", "%20")
            .replace("*", "%2A")
            .replace("%7E", "~")
        )
