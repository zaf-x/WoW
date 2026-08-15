"""Wire protocol packet definitions for the WoW VPN.

Every packet on the wire consists of a 4-byte big-endian payload length
followed by a 1-byte packet type and the type-specific payload::

    +---------------+---------------+-----------------...
    | payload_len   | packet_type   | payload         ...
    | uint32 (4B)   | uint8  (1B)   | (payload_len-1) ...
    +---------------+---------------+-----------------...

``payload_len`` counts the type byte plus the payload bytes, so the total
frame size is ``4 + payload_len``.
"""

import struct
from dataclasses import dataclass


class PacketType: pass

PT_AUTH = 0
PT_AUTH_RESP = 1
PT_APP_DATA = 2
PT_PING = 3
PT_PONG = 4
PT_IPV4_ASSIGN = 5
PT_IPV6_ASSIGN = 6


@dataclass
class Authentication(PacketType):
    """Client -> server authentication request carrying a 128-bit token.

    Attributes:
        token: The 128-bit authentication token as an integer.
    """

    token: int

    def pack(self) -> bytes:
        """Serialize the packet to its wire representation.

        Returns:
            The encoded packet bytes (header plus payload).
        """
        return struct.pack(
            "!IBQQ",
            17,  # payload_len = 1 (type) + 16 (token)
            PT_AUTH,
            self.token >> 64,
            self.token & 0xFFFFFFFFFFFFFFFF,
        )

    @classmethod
    def unpack(cls, data: bytes) -> "Authentication":
        """Parse a packet from its wire representation.

        Args:
            data: The full frame bytes including the 4-byte length header.

        Returns:
            The decoded :class:`Authentication` packet.

        Raises:
            ValueError: If the data is too short, has the wrong packet
                type, or carries an unexpected payload length.
        """
        verify(data, 17, PT_AUTH)
        _, _, token_high, token_low = struct.unpack("!IBQQ", data)
        return cls((token_high << 64) | token_low)


@dataclass
class AuthenticationResponse(PacketType):
    """Server -> client reply to an :class:`Authentication` request.

    On success the tunnel addresses are carried in the
    :class:`IPv4Assign` and :class:`IPv6Assign` packets sent right after
    this one.

    Attributes:
        success: Whether the authentication succeeded.
    """

    success: bool

    def pack(self) -> bytes:
        """Serialize the packet to its wire representation.

        Returns:
            The encoded packet bytes (header plus payload).
        """
        return struct.pack(
            "!IBB",
            2,  # payload_len = 1 (type) + 1 (success)
            PT_AUTH_RESP,
            1 if self.success else 0,
        )

    @classmethod
    def unpack(cls, data: bytes) -> "AuthenticationResponse":
        """Parse a packet from its wire representation.

        Args:
            data: The full frame bytes including the 4-byte length header.

        Returns:
            The decoded :class:`AuthenticationResponse` packet.

        Raises:
            ValueError: If the data is too short, has the wrong packet
                type, or carries an unexpected payload length.
        """
        verify(data, 2, PT_AUTH_RESP)
        _, _, success = struct.unpack("!IBB", data)
        return cls(success == 1)

@dataclass
class IPv4Assign(PacketType):
    """Server -> client assignment of the tunnel IPv4 address.

    Sent after :class:`AuthenticationResponse`; carries the 32-bit
    address as an integer and the prefix length of the tunnel network.

    Attributes:
        ip_addr: The assigned tunnel IPv4 address as a 32-bit integer.
        ip_cidr: The prefix length of the tunnel network (e.g. 24).
    """

    ip_addr: int
    ip_cidr: int

    def pack(self) -> bytes:
        """Serialize the packet to its wire representation.

        Returns:
            The encoded packet bytes (header plus payload).
        """

        return struct.pack(
            "!IBIB",
            6,
            PT_IPV4_ASSIGN,
            self.ip_addr,
            self.ip_cidr
        )

    @classmethod
    def unpack(cls, data: bytes):
        verify(data, 6, PT_IPV4_ASSIGN)
        _, _, ip_addr, ip_cidr = struct.unpack("!IBIB", data)
        return cls(ip_addr, ip_cidr)


@dataclass
class IPv6Assign(PacketType):
    """Server -> client assignment of the tunnel IPv6 address.

    Sent after :class:`AuthenticationResponse`; carries the 128-bit
    address as an integer and the prefix length of the tunnel network.

    Attributes:
        ip_addr: The assigned tunnel IPv6 address as a 128-bit integer.
        ip_cidr: The prefix length of the tunnel network (e.g. 64).
    """

    ip_addr: int
    ip_cidr: int

    def pack(self) -> bytes:
        """Serialize the packet to its wire representation.

        Returns:
            The encoded packet bytes (header plus payload).
        """
        return struct.pack(
            "!IB16sB",
            18,  # payload_len = 1 (type) + 16 (addr) + 1 (cidr)
            PT_IPV6_ASSIGN,
            self.ip_addr.to_bytes(16, byteorder="big", signed=False),
            self.ip_cidr
        )

    @classmethod
    def unpack(cls, data: bytes) -> "IPv6Assign":
        """Parse a packet from its wire representation.

        Args:
            data: The full frame bytes including the 4-byte length header.

        Returns:
            The decoded :class:`IPv6Assign` packet.

        Raises:
            ValueError: If the data is too short, has the wrong packet
                type, or carries an unexpected payload length.
        """
        verify(data, 18, PT_IPV6_ASSIGN)
        _, _, ip_addr, ip_cidr = struct.unpack("!IB16sB", data)
        return cls(int.from_bytes(ip_addr, byteorder="big"), ip_cidr)



@dataclass
class ApplicationData(PacketType):
    """A tunnelled IP packet exchanged in either direction.

    Attributes:
        data: The raw IP packet bytes to be tunnelled.
    """

    data: bytes

    def pack(self) -> bytes:
        """Serialize the packet to its wire representation.

        Returns:
            The encoded packet bytes (header plus payload).
        """
        payload_len = 1 + len(self.data)
        return struct.pack("!IB", payload_len, PT_APP_DATA) + self.data

    @classmethod
    def unpack(cls, data: bytes) -> "ApplicationData":
        """Parse a packet from its wire representation.

        Args:
            data: The full frame bytes including the 4-byte length header.

        Returns:
            The decoded :class:`ApplicationData` packet.

        Raises:
            ValueError: If the data is too short, has the wrong packet
                type, or is truncated relative to its declared length.
        """
        if len(data) < 5:
            raise ValueError("ApplicationData packet too short")
        payload_len, pkt_type = struct.unpack("!IB", data[:5])
        if pkt_type != PT_APP_DATA:
            raise ValueError(f"Expected APP_DATA({PT_APP_DATA}), got {pkt_type}")
        body_len = payload_len - 1
        expected_total = 5 + body_len
        if len(data) < expected_total:
            raise ValueError(f"Expected {expected_total} bytes, got {len(data)}")
        return cls(data[5:5 + body_len])


@dataclass
class Ping(PacketType):
    """Keepalive request sent by the client; the server answers with :class:`Pong`."""

    def pack(self) -> bytes:
        """Serialize the packet to its wire representation.

        Returns:
            The encoded packet bytes (header only, empty payload).
        """
        return struct.pack("!IB", 1, PT_PING)

    @classmethod
    def unpack(cls, data: bytes) -> "Ping":
        """Parse a packet from its wire representation.

        Args:
            data: The full frame bytes including the 4-byte length header.

        Returns:
            The decoded :class:`Ping` packet.

        Raises:
            ValueError: If the data is not a valid Ping frame.
        """
        if len(data) < 5:
            raise ValueError("Ping packet too short")
        payload_len, pkt_type = struct.unpack("!IB", data[:5])
        if pkt_type != PT_PING or payload_len != 1:
            raise ValueError("Not a Ping packet")
        return cls()


@dataclass
class Pong(PacketType):
    """Keepalive reply sent by the server in response to :class:`Ping`."""

    def pack(self) -> bytes:
        """Serialize the packet to its wire representation.

        Returns:
            The encoded packet bytes (header only, empty payload).
        """
        return struct.pack("!IB", 1, PT_PONG)

    @classmethod
    def unpack(cls, data: bytes) -> "Pong":
        """Parse a packet from its wire representation.

        Args:
            data: The full frame bytes including the 4-byte length header.

        Returns:
            The decoded :class:`Pong` packet.

        Raises:
            ValueError: If the data is not a valid Pong frame.
        """
        if len(data) < 5:
            raise ValueError("Pong packet too short")
        payload_len, pkt_type = struct.unpack("!IB", data[:5])
        if pkt_type != PT_PONG or payload_len != 1:
            raise ValueError("Not a Pong packet")
        return cls()


@dataclass
class Raw:
    data: bytes

    def pack(self):
        return self.data

    @classmethod
    def unpack(cls, data: bytes):
        return cls(data)

def unpack(data: bytes):
    """Decode a single frame into its concrete packet object.

    The packet type is read from the frame and dispatch is delegated to
    the matching packet class.

    Args:
        data: The full frame bytes including the 4-byte length header.

    Returns:
        An instance of one of the packet classes defined in this module.

    Raises:
        ValueError: If the data is too short or the packet type is unknown.
    """
    if len(data) < 5:
        raise ValueError("Data too short to unpack")

    pkt_type = data[4]

    if pkt_type == PT_AUTH:
        return Authentication.unpack(data)
    elif pkt_type == PT_AUTH_RESP:
        return AuthenticationResponse.unpack(data)
    elif pkt_type == PT_APP_DATA:
        return ApplicationData.unpack(data)
    elif pkt_type == PT_PING:
        return Ping.unpack(data)
    elif pkt_type == PT_PONG:
        return Pong.unpack(data)
    elif pkt_type == PT_IPV4_ASSIGN:
        return IPv4Assign.unpack(data)
    elif pkt_type == PT_IPV6_ASSIGN:
        return IPv6Assign.unpack(data)
    else:
        raise ValueError(f"Unknown packet type: {pkt_type}")

def verify(data: bytes, payload_len: int, packet_type: int):
    if int.from_bytes(data[:4], byteorder="big") != payload_len:
        raise ValueError(f"Invalid Packet: Invalid payload length, expecting {payload_len}, found {int.from_bytes(data[:4])}")

    if data[4] != packet_type:
        raise ValueError("Invalid Packet: Invalid Type")