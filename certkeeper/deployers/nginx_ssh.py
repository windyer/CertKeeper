"""通过 SSH 部署 nginx 证书。"""

from __future__ import annotations

import io
import logging
from pathlib import Path

import paramiko

from certkeeper.deployers.base import Deployer

logger = logging.getLogger(__name__)


class NginxSshDeployer(Deployer):
    """通过 SSH 将证书上传到远程 Nginx 服务器并重载配置。"""

    def validate_config(self) -> list[str]:
        errors: list[str] = []
        for field in ("host", "user", "cert_path", "reload_command"):
            if field not in self.config.settings:
                errors.append(f"{field} is required")
        if "password" not in self.config.settings and "ssh_key_path" not in self.config.settings:
            errors.append("password or ssh_key_path is required")
        return errors

    def _create_ssh_client(self) -> paramiko.SSHClient:
        """创建并返回已认证的 SSH 连接。"""
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        host = str(self.config.settings["host"])
        port = int(self.config.settings["port"]) if self.config.settings.get("port") else 22
        user = str(self.config.settings["user"])

        connect_kwargs: dict = {"hostname": host, "port": port, "username": user, "timeout": 30}

        if "ssh_key_path" in self.config.settings:
            connect_kwargs["key_filename"] = str(self.config.settings["ssh_key_path"])
        elif "password" in self.config.settings:
            connect_kwargs["password"] = str(self.config.settings["password"])

        client.connect(**connect_kwargs)
        return client

    @property
    def _sudo_password(self) -> str | None:
        """获取 sudo 密码，默认与 SSH 密码相同。"""
        pw = self.config.settings.get("sudo_password")
        if pw:
            return str(pw)
        return self.config.settings.get("password")

    def _exec(self, client: paramiko.SSHClient, cmd: str, *, sudo: bool = False) -> tuple[int, str]:
        """执行远程命令，返回 (exit_code, stderr)。"""
        if sudo:
            sudo_pw = self._sudo_password
            if sudo_pw:
                cmd = f"sudo -S {cmd}"
            else:
                cmd = f"sudo {cmd}"
        logger.info("执行命令: %s", cmd)
        stdin, stdout, stderr = client.exec_command(cmd)
        if sudo and sudo_pw:
            stdin.write(sudo_pw + "\n")
            stdin.flush()
        exit_code = stdout.channel.recv_exit_status()
        err_output = stderr.read().decode().strip()
        # sudo -S 会把密码提示也输出到 stderr，过滤掉
        if sudo and err_output.startswith("[sudo]"):
            err_output = err_output.split("\n", 1)[-1].strip()
        return exit_code, err_output

    def deploy(self, domain: str, cert_path: Path, key_path: Path) -> dict[str, str]:
        remote_cert_dir = str(self.config.settings["cert_path"])
        reload_command = str(self.config.settings["reload_command"])
        use_sudo = bool(self.config.settings.get("sudo", True))

        # 远程目标路径
        remote_cert = f"{remote_cert_dir}/{domain}.pem"
        remote_key = f"{remote_cert_dir}/{domain}.key"

        # 临时上传路径（普通用户可写）
        tmp_cert = f"/tmp/{domain}.pem"
        tmp_key = f"/tmp/{domain}.key"

        client = self._create_ssh_client()
        try:
            sftp = client.open_sftp()
            try:
                # 上传到 /tmp
                logger.info("上传证书 %s -> %s", cert_path, tmp_cert)
                sftp.put(str(cert_path), tmp_cert)
                logger.info("上传私钥 %s -> %s", key_path, tmp_key)
                sftp.put(str(key_path), tmp_key)
            finally:
                sftp.close()

            if use_sudo:
                # sudo 确保目标目录存在
                exit_code, err = self._exec(client, f"mkdir -p {remote_cert_dir}", sudo=True)
                if exit_code != 0:
                    raise RuntimeError(f"创建目录失败: {err}")

                # sudo 移动文件到目标位置
                exit_code, err = self._exec(client, f"mv {tmp_cert} {remote_cert}", sudo=True)
                if exit_code != 0:
                    raise RuntimeError(f"移动证书失败: {err}")

                exit_code, err = self._exec(client, f"mv {tmp_key} {remote_key}", sudo=True)
                if exit_code != 0:
                    raise RuntimeError(f"移动私钥失败: {err}")

                # sudo 设置私钥权限
                self._exec(client, f"chmod 600 {remote_key}", sudo=True)

                # sudo 执行重载命令
                exit_code, err = self._exec(client, reload_command, sudo=True)
                if exit_code != 0:
                    raise RuntimeError(f"重载命令失败 (exit {exit_code}): {err}")
            else:
                exit_code, err = self._exec(client, f"mkdir -p {remote_cert_dir}")
                if exit_code != 0:
                    raise RuntimeError(f"创建目录失败: {err}")

                exit_code, err = self._exec(client, f"mv {tmp_cert} {remote_cert}")
                if exit_code != 0:
                    raise RuntimeError(f"移动证书失败: {err}")

                exit_code, err = self._exec(client, f"mv {tmp_key} {remote_key}")
                if exit_code != 0:
                    raise RuntimeError(f"移动私钥失败: {err}")

                self._exec(client, f"chmod 600 {remote_key}")

                exit_code, err = self._exec(client, reload_command)
                if exit_code != 0:
                    raise RuntimeError(f"重载命令失败 (exit {exit_code}): {err}")

            return {
                "domain": domain,
                "target": self.config.name,
                "host": str(self.config.settings["host"]),
                "remote_cert": remote_cert,
                "remote_key": remote_key,
                "status": "success",
            }
        finally:
            client.close()
