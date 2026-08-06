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


class PacketType:
    """Numeric identifiers for the packet types used on the wire."""

    AUTH = 0
    AUTH_RESP = 1
    APP_DATA = 2
    PING = 3
    PONG = 4


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
            PacketType.AUTH,
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
        if len(data) < 21:
            raise ValueError("Authentication packet too short")
        payload_len, pkt_type, token_high, token_low = struct.unpack("!IBQQ", data)
        if pkt_type != PacketType.AUTH:
            raise ValueError(f"Expected AUTH({PacketType.AUTH}), got {pkt_type}")
        if payload_len != 17:
            raise ValueError(f"Unexpected payload_len: {payload_len}")
        return cls((token_high << 64) | token_low)


@dataclass
class AuthenticationResponse(PacketType):
    """Server -> client reply to an :class:`Authentication` request.

    On success the response carries the tunnel IPv4 address assigned to
    the client.

    Attributes:
        success: Whether the authentication succeeded.
        ip_addr: The assigned tunnel IPv4 address as a 32-bit integer.
        ip_cidr: The prefix length of the tunnel network (e.g. 24).
    """

    success: bool
    ip_addr: int
    ip_cidr: int

    def pack(self) -> bytes:
        """Serialize the packet to its wire representation.

        Returns:
            The encoded packet bytes (header plus payload).
        """
        return struct.pack(
            "!IBBIB",
            7,  # payload_len = 1 (type) + 1 (success) + 4 (ip_addr) + 1 (ip_cidr)
            PacketType.AUTH_RESP,
            1 if self.success else 0,
            self.ip_addr,
            self.ip_cidr
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
        if len(data) < 11:
            raise ValueError("AuthenticationResponse packet too short")
        payload_len, pkt_type, success, ip_addr, ip_cidr = struct.unpack("!IBBIB", data)
        if pkt_type != PacketType.AUTH_RESP:
            raise ValueError(f"Expected AUTH_RESP({PacketType.AUTH_RESP}), got {pkt_type}")
        if payload_len != 7:
            raise ValueError(f"Unexpected payload_len: {payload_len}")
        return cls(success == 1, ip_addr, ip_cidr)


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
        return struct.pack("!IB", payload_len, PacketType.APP_DATA) + self.data

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
        if pkt_type != PacketType.APP_DATA:
            raise ValueError(f"Expected APP_DATA({PacketType.APP_DATA}), got {pkt_type}")
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
        return struct.pack("!IB", 1, PacketType.PING)

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
        if pkt_type != PacketType.PING or payload_len != 1:
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
        return struct.pack("!IB", 1, PacketType.PONG)

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
        if pkt_type != PacketType.PONG or payload_len != 1:
            raise ValueError("Not a Pong packet")
        return cls()


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

    if pkt_type == PacketType.AUTH:
        return Authentication.unpack(data)
    elif pkt_type == PacketType.AUTH_RESP:
        return AuthenticationResponse.unpack(data)
    elif pkt_type == PacketType.APP_DATA:
        return ApplicationData.unpack(data)
    elif pkt_type == PacketType.PING:
        return Ping.unpack(data)
    elif pkt_type == PacketType.PONG:
        return Pong.unpack(data)
    else:
        raise ValueError(f"Unknown packet type: {pkt_type}")
