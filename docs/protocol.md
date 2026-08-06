# WoW - Wire over Wire

WoW is a VPN working on L2, data transfer via TCP
Works like this:

Client Application -> TUN -----TCP-----> Server -> TUN -> Physical interface

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
0         1         5     6
+---------+---------+-----+
| Success | IP Addr | CIDR|
+---------+---------+-----+
```

On success, `IP Addr` (4 bytes) and `CIDR` (1 byte prefix length) tell the
client which virtual address to configure on its TUN interface.
Meaningless when `Success` is 0.

### Type 2 Application Data

Just IP Data

### Type 3 Ping

No body. Sent by the client periodically (every 15s) to keep the TCP
connection alive across NAT/firewall middleboxes and to detect dead
connections.

### Type 4 Pong

No body. Sent by the server in reply to a Ping.