"""Linux TUN device wrapper and network configuration helpers."""

from __future__ import annotations

import fcntl
import ipaddress
import logging
import os
import shutil
import struct
import subprocess
from collections.abc import Sequence
from types import TracebackType

TUNSETIFF = 0x400454CA
IFF_TUN = 0x0001
IFF_NO_PI = 0x1000

TUN_MTU = 65535

logger = logging.getLogger(__name__)


class Tun:
    """Linux TUN device wrapper (IFF_TUN | IFF_NO_PI).

    Attributes:
        name: Name of the TUN interface, e.g. ``"wowtun"``.
        mtu: Read buffer size used for :meth:`read`.
    """

    def __init__(self, name: str, mtu: int = TUN_MTU) -> None:
        """Create and attach to a TUN device.

        Args:
            name: Interface name to request from the kernel.
            mtu: Maximum number of bytes read per packet.
        """
        self.name = name
        self.mtu = mtu
        self._fd = os.open("/dev/net/tun", os.O_RDWR)
        fcntl.ioctl(
            self._fd, TUNSETIFF, struct.pack("16sH", name.encode(), IFF_TUN | IFF_NO_PI)
        )
        logger.info("TUN device %s opened", name)

    def fileno(self) -> int:
        """Return the underlying file descriptor for use with event loops."""
        return self._fd

    def read(self) -> bytes:
        """Read one IP packet from the device.

        Returns:
            The raw IP packet bytes.
        """
        return os.read(self._fd, self.mtu)

    def write(self, data: bytes) -> int:
        """Write one IP packet to the device.

        Args:
            data: The raw IP packet bytes.

        Returns:
            The number of bytes written.
        """
        return os.write(self._fd, data)

    def close(self) -> None:
        """Close the device file descriptor."""
        os.close(self._fd)

    def up(self, mtu: int = 1400) -> None:
        """Set the interface MTU and bring the link up.

        The MTU must be smaller than the physical path MTU: the inner IP
        packet still has to carry the outer IP/TCP/TLS overhead, otherwise
        large packets are silently dropped (ping works but TCP stalls).

        Args:
            mtu: Link MTU to configure.
        """
        subprocess.run(
            ["ip", "link", "set", "dev", self.name, "mtu", str(mtu), "up"], check=True
        )

    def set_addr(self, addr: str) -> None:
        """Assign an address to the interface, e.g. ``'10.8.0.1/24'``.

        Args:
            addr: CIDR notation address to configure.
        """
        subprocess.run(["ip", "addr", "add", addr, "dev", self.name], check=True)

    def add_route(self, cidr: str) -> None:
        """Add a route via this interface, e.g. ``'10.8.0.2/32'`` (used to steer reply packets into the TUN).

        Args:
            cidr: Destination prefix to route through this interface.
        """
        subprocess.run(["ip", "route", "add", cidr, "dev", self.name], check=True)

    def setup_routing(self, fwmark: int, table: int = 100, bypass_ip: str | None = None,
                      bypass_networks: Sequence[str] | None = None) -> None:
        """Route all traffic through the TUN except packets carrying ``fwmark`` (prevents loops of the VPN's own traffic).

        Configures policy routing for both IPv4 and IPv6. The bypass rules
        for the VPN server's address and for directly-connected LAN
        networks are only added in the address family they belong to.

        Args:
            fwmark: Netfilter mark applied to the VPN's own outer packets;
                traffic with this mark keeps using the main routing table.
            table: Number of the custom routing table used for the
                default-via-TUN route.
            bypass_ip: The VPN server's address. Ordinary traffic to it
                (e.g. management ssh) must bypass the TUN and consult the
                main table, otherwise it would loop back to itself on the
                server, forming a hairpin path. An explicit priority is
                used: the bypass rule must have a numerically smaller
                priority than the fwmark rule so it matches first.
            bypass_networks: Directly-connected networks (e.g. ``"192.168.1.0/24"``)
                that must stay on the main table. Reply packets to LAN
                clients (a proxy on this host answering the LAN, ssh to
                local devices, etc.) would otherwise be captured by the
                TUN route and dropped, so local traffic bypasses the tunnel.
        """
        self._fwmark = fwmark
        self._table = table
        self._bypass_ip = bypass_ip
        self._bypass_networks = list(bypass_networks or [])
        # Remove possibly leftover rules first (a previous abnormal exit may
        # have skipped teardown) to keep this method idempotent.
        for family, ip_cmd in (("inet", ["ip"]), ("inet6", ["ip", "-6"])):
            for network in self._bypass_networks:
                if self._bypass_matches(family, network):
                    subprocess.run(
                        ip_cmd + ["rule", "del", "to", network, "lookup", "main",
                                  "priority", str(table * 10 - 1)],
                        check=False,
                    )
            if bypass_ip and self._bypass_matches(family, bypass_ip):
                subprocess.run(
                    ip_cmd + ["rule", "del", "to", bypass_ip, "lookup", "main",
                              "priority", str(table * 10)],
                    check=False,
                )
            subprocess.run(
                ip_cmd + ["rule", "del", "not", "fwmark", hex(fwmark), "lookup", str(table),
                          "priority", str(table * 10 + 1)],
                check=False,
            )
            subprocess.run(
                ip_cmd + ["route", "del", "default", "dev", self.name, "table", str(table)],
                check=False,
            )
        for family, ip_cmd in (("inet", ["ip"]), ("inet6", ["ip", "-6"])):
            for network in self._bypass_networks:
                if self._bypass_matches(family, network):
                    subprocess.run(
                        ip_cmd + ["rule", "add", "to", network, "lookup", "main",
                                  "priority", str(table * 10 - 1)],
                        check=True,
                    )
            if bypass_ip and self._bypass_matches(family, bypass_ip):
                subprocess.run(
                    ip_cmd + ["rule", "add", "to", bypass_ip, "lookup", "main",
                              "priority", str(table * 10)],
                    check=True,
                )
            subprocess.run(
                ip_cmd + ["rule", "add", "not", "fwmark", hex(fwmark), "lookup", str(table),
                          "priority", str(table * 10 + 1)],
                check=True,
            )
            subprocess.run(
                ip_cmd + ["route", "add", "default", "dev", self.name, "table", str(table)],
                check=True,
            )
        logger.info("Routing set: all traffic via %s except fwmark %#x", self.name, fwmark)

    @staticmethod
    def _bypass_matches(family: str, addr: str) -> bool:
        """Return True if ``addr`` (an IP or CIDR network) belongs to ``family`` (``"inet"`` or ``"inet6"``)."""
        return (4 if family == "inet" else 6) == ipaddress.ip_network(addr, strict=False).version

    def setup_dns(self, server: str = "8.8.8.8") -> None:
        """Bind DNS resolution to this interface (queries go through the tunnel) to prevent DNS poisoning on the physical link.

        Silently skips the setup when ``resolvectl`` is not available.

        Args:
            server: Upstream DNS server to use through the tunnel.
        """
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
        """Revert the DNS binding created by :meth:`setup_dns`, if any."""
        if not getattr(self, "_dns_server", None):
            return
        subprocess.run(["resolvectl", "revert", self.name], check=False)
        subprocess.run(["resolvectl", "flush-caches"], check=False)
        self._dns_server = None

    def teardown_routing(self) -> None:
        """Remove the policy routing rules and routes created by :meth:`setup_routing`, if any."""
        if not hasattr(self, "_fwmark"):
            return
        bypass_ip = getattr(self, "_bypass_ip", None)
        bypass_networks = getattr(self, "_bypass_networks", [])
        for family, ip_cmd in (("inet", ["ip"]), ("inet6", ["ip", "-6"])):
            subprocess.run(
                ip_cmd + ["route", "del", "default", "dev", self.name,
                          "table", str(self._table)],
                check=False,
            )
            subprocess.run(
                ip_cmd + ["rule", "del", "not", "fwmark", hex(self._fwmark),
                          "lookup", str(self._table)],
                check=False,
            )
            for network in bypass_networks:
                if self._bypass_matches(family, network):
                    subprocess.run(
                        ip_cmd + ["rule", "del", "to", network, "lookup", "main"],
                        check=False,
                    )
            if bypass_ip and self._bypass_matches(family, bypass_ip):
                subprocess.run(
                    ip_cmd + ["rule", "del", "to", bypass_ip, "lookup", "main"],
                    check=False,
                )

    def setup_nat(self, out_iface: str) -> None:
        """Enable kernel forwarding and configure MASQUERADE to NAT TUN traffic out through the physical interface.

        Configures both IPv4 (iptables) and IPv6 (ip6tables) NAT. The IPv6
        part is best-effort: when the kernel/distro lacks ip6tables NAT
        support the tunnel still carries IPv6 between peers, only the
        NAT66 path to the internet is unavailable.

        Args:
            out_iface: Name of the physical egress interface, e.g. ``"ens5"``.
        """
        self._nat_iface = out_iface
        with open("/proc/sys/net/ipv4/ip_forward", "w") as f:
            f.write("1")
        try:
            with open("/proc/sys/net/ipv6/conf/all/forwarding", "w") as f:
                f.write("1")
        except OSError:
            logger.warning("Cannot enable IPv6 forwarding (IPv6 disabled on this host?)")
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
        for cmd in (
            ["ip6tables", "-t", "nat", "-A", "POSTROUTING", "-o", out_iface, "-j", "MASQUERADE"],
            ["ip6tables", "-A", "FORWARD", "-i", self.name, "-o", out_iface, "-j", "ACCEPT"],
            ["ip6tables", "-A", "FORWARD", "-i", out_iface, "-o", self.name,
             "-m", "conntrack", "--ctstate", "RELATED,ESTABLISHED", "-j", "ACCEPT"],
        ):
            try:
                subprocess.run(cmd, check=True)
            except (OSError, subprocess.CalledProcessError):
                logger.warning("ip6tables rule failed (IPv6 NAT unavailable?): %s", " ".join(cmd))
        logger.info("NAT set: %s -> %s (MASQUERADE)", self.name, out_iface)

    def teardown_nat(self) -> None:
        """Remove the iptables rules created by :meth:`setup_nat`, if any."""
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
        for cmd in (
            ["ip6tables", "-t", "nat", "-D", "POSTROUTING", "-o", out_iface, "-j", "MASQUERADE"],
            ["ip6tables", "-D", "FORWARD", "-i", self.name, "-o", out_iface, "-j", "ACCEPT"],
            ["ip6tables", "-D", "FORWARD", "-i", out_iface, "-o", self.name,
             "-m", "conntrack", "--ctstate", "RELATED,ESTABLISHED", "-j", "ACCEPT"],
        ):
            subprocess.run(cmd, check=False)

    def __enter__(self) -> "Tun":
        """Enter the context manager, returning this TUN device."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit the context manager, closing the device."""
        self.close()
