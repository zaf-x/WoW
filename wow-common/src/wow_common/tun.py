from __future__ import annotations

import fcntl
import logging
import os
import shutil
import struct
import subprocess
from types import TracebackType

TUNSETIFF = 0x400454CA
IFF_TUN = 0x0001
IFF_NO_PI = 0x1000

TUN_MTU = 65535

logger = logging.getLogger(__name__)


class Tun:
    """Linux TUN 设备封装（IFF_TUN | IFF_NO_PI）。"""

    def __init__(self, name: str, mtu: int = TUN_MTU) -> None:
        self.name = name
        self.mtu = mtu
        self._fd = os.open("/dev/net/tun", os.O_RDWR)
        fcntl.ioctl(
            self._fd, TUNSETIFF, struct.pack("16sH", name.encode(), IFF_TUN | IFF_NO_PI)
        )
        logger.info("TUN device %s opened", name)

    def fileno(self) -> int:
        return self._fd

    def read(self) -> bytes:
        return os.read(self._fd, self.mtu)

    def write(self, data: bytes) -> int:
        return os.write(self._fd, data)

    def close(self) -> None:
        os.close(self._fd)

    def up(self, mtu: int = 1400) -> None:
        # MTU 要小于物理路径 MTU：内层 IP 包还需套上外层 IP/TCP/TLS 的开销，
        # 否则大包被静默丢弃（ping 通但 TCP 卡死）。
        subprocess.run(
            ["ip", "link", "set", "dev", self.name, "mtu", str(mtu), "up"], check=True
        )

    def set_addr(self, addr: str) -> None:
        """给接口配置地址，如 '10.8.0.1/24'。"""
        subprocess.run(["ip", "addr", "add", addr, "dev", self.name], check=True)

    def add_route(self, cidr: str) -> None:
        """加一条经由本接口的路由，如 '10.8.0.2/32'（用于把回包引进 TUN）。"""
        subprocess.run(["ip", "route", "add", cidr, "dev", self.name], check=True)

    def setup_routing(self, fwmark: int, table: int = 100, bypass_ip: str | None = None) -> None:
        """默认全部流量走 TUN；带 fwmark 的包除外（防止 VPN 自身流量环路）。

        bypass_ip：VPN 服务器地址。发往它的普通流量（如管理用 ssh）必须
        绕过 TUN 查 main 表，否则会在服务器上绕回自身形成发卡路径。
        用显式 priority：bypass 必须比 fwmark 规则数值小（先生效）。
        """
        self._fwmark = fwmark
        self._table = table
        self._bypass_ip = bypass_ip
        # 先清掉可能残留的旧规则（上次异常退出时 teardown 没跑完），保证幂等
        if bypass_ip:
            subprocess.run(
                ["ip", "rule", "del", "to", bypass_ip, "lookup", "main",
                 "priority", str(table * 10)],
                check=False,
            )
        subprocess.run(
            ["ip", "rule", "del", "not", "fwmark", hex(fwmark), "lookup", str(table),
             "priority", str(table * 10 + 1)],
            check=False,
        )
        subprocess.run(
            ["ip", "route", "del", "default", "dev", self.name, "table", str(table)],
            check=False,
        )
        if bypass_ip:
            subprocess.run(
                ["ip", "rule", "add", "to", bypass_ip, "lookup", "main",
                 "priority", str(table * 10)],
                check=True,
            )
        subprocess.run(
            ["ip", "rule", "add", "not", "fwmark", hex(fwmark), "lookup", str(table),
             "priority", str(table * 10 + 1)],
            check=True,
        )
        subprocess.run(
            ["ip", "route", "add", "default", "dev", self.name, "table", str(table)],
            check=True,
        )
        logger.info("Routing set: all traffic via %s except fwmark %#x", self.name, fwmark)

    def setup_dns(self, server: str = "8.8.8.8") -> None:
        """把 DNS 解析绑到本接口（查询走隧道），防止物理链路上的 DNS 污染。"""
        self._dns_server = None
        if shutil.which("resolvectl") is None:
            logger.warning("resolvectl not found, skip DNS binding")
            return
        subprocess.run(["resolvectl", "dns", self.name, server], check=True)
        subprocess.run(["resolvectl", "domain", self.name, "~."], check=True)
        subprocess.run(["resolvectl", "flush-caches"], check=True)
        self._dns_server = server
        logger.info("DNS bound to %s via %s", server, self.name)

    def teardown_dns(self) -> None:
        if not getattr(self, "_dns_server", None):
            return
        subprocess.run(["resolvectl", "revert", self.name], check=False)
        subprocess.run(["resolvectl", "flush-caches"], check=False)
        self._dns_server = None

    def teardown_routing(self) -> None:
        if not hasattr(self, "_fwmark"):
            return
        subprocess.run(
            ["ip", "route", "del", "default", "dev", self.name, "table", str(self._table)],
            check=False,
        )
        subprocess.run(
            ["ip", "rule", "del", "not", "fwmark", hex(self._fwmark), "lookup", str(self._table),
             "priority", str(self._table * 10 + 1)],
            check=False,
        )
        if getattr(self, "_bypass_ip", None):
            subprocess.run(
                ["ip", "rule", "del", "to", self._bypass_ip, "lookup", "main",
                 "priority", str(self._table * 10)],
                check=False,
            )

    def setup_nat(self, out_iface: str) -> None:
        """开启内核转发并配置 MASQUERADE，把 TUN 流量经物理网卡 NAT 出去。"""
        self._nat_iface = out_iface
        with open("/proc/sys/net/ipv4/ip_forward", "w") as f:
            f.write("1")
        subprocess.run(
            ["iptables", "-t", "nat", "-A", "POSTROUTING", "-o", out_iface, "-j", "MASQUERADE"],
            check=True,
        )
        subprocess.run(
            ["iptables", "-A", "FORWARD", "-i", self.name, "-o", out_iface, "-j", "ACCEPT"],
            check=True,
        )
        subprocess.run(
            ["iptables", "-A", "FORWARD", "-i", out_iface, "-o", self.name,
             "-m", "conntrack", "--ctstate", "RELATED,ESTABLISHED", "-j", "ACCEPT"],
            check=True,
        )
        logger.info("NAT set: %s -> %s (MASQUERADE)", self.name, out_iface)

    def teardown_nat(self) -> None:
        if not hasattr(self, "_nat_iface"):
            return
        out_iface = self._nat_iface
        subprocess.run(
            ["iptables", "-t", "nat", "-D", "POSTROUTING", "-o", out_iface, "-j", "MASQUERADE"],
            check=True,
        )
        subprocess.run(
            ["iptables", "-D", "FORWARD", "-i", self.name, "-o", out_iface, "-j", "ACCEPT"],
            check=True,
        )
        subprocess.run(
            ["iptables", "-D", "FORWARD", "-i", out_iface, "-o", self.name,
             "-m", "conntrack", "--ctstate", "RELATED,ESTABLISHED", "-j", "ACCEPT"],
            check=True,
        )

    def __enter__(self) -> "Tun":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()
