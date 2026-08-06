import struct
from dataclasses import dataclass


class PacketType:
    AUTH = 0
    AUTH_RESP = 1
    APP_DATA = 2


@dataclass
class Authentication(PacketType):
    token: int

    def pack(self) -> bytes:
        return struct.pack(
            "!IBQQ",
            17,                       # payload_len = 1(type) + 16(token)
            PacketType.AUTH,
            self.token >> 64,
            self.token & 0xFFFFFFFFFFFFFFFF,
        )

    @classmethod
    def unpack(cls, data: bytes) -> "Authentication":
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
    success: bool
    ip_addr: int
    ip_cidr: int

    def pack(self) -> bytes:
        return struct.pack(
            "!IBBIB",
            7,                        # payload_len = 1(type) + 1(success) + 4(ip_addr) + 1(ip_cidr)
            PacketType.AUTH_RESP,
            1 if self.success else 0,
            self.ip_addr,
            self.ip_cidr
        )

    @classmethod
    def unpack(cls, data: bytes) -> "AuthenticationResponse":
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
    data: bytes

    def pack(self) -> bytes:
        payload_len = 1 + len(self.data)
        return struct.pack("!IB", payload_len, PacketType.APP_DATA) + self.data

    @classmethod
    def unpack(cls, data: bytes) -> "ApplicationData":
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


def unpack(data: bytes):
    if len(data) < 5:
        raise ValueError("Data too short to unpack")
    
    pkt_type = data[4]
    
    if pkt_type == PacketType.AUTH:
        return Authentication.unpack(data)
    elif pkt_type == PacketType.AUTH_RESP:
        return AuthenticationResponse.unpack(data)
    elif pkt_type == PacketType.APP_DATA:
        return ApplicationData.unpack(data)
    else:
        raise ValueError(f"Unknown packet type: {pkt_type}")