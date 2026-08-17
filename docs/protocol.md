# WoW - Wire over Wire

[English](protocol.md) | [中文](protocol.zh-CN.md)

WoW is an L3 (IP) VPN over a TLS-encrypted TCP connection.
Works like this:

Client Application -> TUN -----TCP + TLS-----> Server -> TUN -> Physical interface

## Basic Message Struct

```
0        4        5
+--------+--------+--
| Length |  Type  | Body
+--------+--------+--
```

## Messages

### Type 0 Authentication

```

0                     16
+----------------------+
| Authentication Token |
+----------------------+
```

### Type 1 Authentication Response

```
0         1                   17
+---------+-------------------+
| Success | ID (16 bytes)     |
+---------+-------------------+
```

`Success` is 1 when the token is accepted, 0 otherwise. `ID` is a
128-bit per-connection id chosen by the server's auth handler (used by
the management API to address the connection). On success the server
immediately follows with a Type 5 IPv4 Assign and a Type 6 IPv6 Assign
packet carrying the tunnel addresses.

### Type 2 Application Data

Just IP Data

### Type 3 Ping

No body. Sent by the client periodically (every 5s) to keep the TCP
connection alive across NAT/firewall middleboxes and to detect dead
connections.

### Type 4 Pong

No body. Sent by the server in reply to a Ping.

### Type 5 IPv4 Assign

```
0         4     5
+---------+-----+
| IP Addr |CIDR |
+---------+-----+
```

The virtual IPv4 address (`IP Addr`, 4 bytes big-endian) and the prefix
length (`CIDR`, 1 byte) to configure on the client's TUN interface.

### Type 6 IPv6 Assign

```
0                                    16    17
+------------------------------------+-----+
| IP Addr (16 bytes)                 |CIDR |
+------------------------------------+-----+
```

The virtual IPv6 address (`IP Addr`, 16 bytes big-endian) and the prefix
length (`CIDR`, 1 byte) to configure on the client's TUN interface.

Sent during the handshake right after the Authentication Response, and
again at any later point when the server rotates the client's address
(IPv6 privacy rotation, `--ipv6-rotate-interval`): the client then
replaces its TUN address with the new one.