"""DNS fallback queries using direct UDP packets to public resolvers."""
from __future__ import annotations

import secrets
import socket
import struct
from typing import Optional


def _dns_query_fallback(
    hostname: str,
    dns_servers: tuple[str, ...] = ("8.8.8.8", "1.1.1.1"),
) -> Optional[str]:
    tx_id = secrets.randbelow(65535) + 1
    packet = struct.pack(">HHHHHH", tx_id, 0x0100, 1, 0, 0, 0)
    for part in hostname.split("."):
        packet += struct.pack("B", len(part)) + part.encode("ascii")
    packet += b"\x00\x00\x01\x00\x01"
    for dns_ip in dns_servers:
        sock = None
        data = b""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(2.0)
            sock.sendto(packet, (dns_ip, 53))
            data, _ = sock.recvfrom(1024)
        except Exception:
            continue
        finally:
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass
        if len(data) < 12:
            continue

        resp_tx_id = struct.unpack(">H", data[0:2])[0]
        if resp_tx_id != tx_id:
            continue
        idx = 12
        while idx < len(data) and data[idx] != 0:
            if (data[idx] & 0xC0) == 0xC0:
                idx += 2
                break
            idx += 1 + data[idx]
        else:
            idx += 5
        if idx > len(data):
            continue
        ancount = struct.unpack(">H", data[6:8])[0]
        for _ in range(ancount):
            if idx >= len(data):
                break
            if (data[idx] & 0xC0) == 0xC0:
                idx += 2
            else:
                while idx < len(data) and data[idx] != 0:
                    idx += 1 + data[idx]
                idx += 1
            if idx + 10 > len(data):
                break
            rtype, _rclass, _ttl, rdlength = struct.unpack(">HHIH", data[idx : idx + 10])
            idx += 10
            if rtype == 1 and rdlength == 4 and idx + 4 <= len(data):
                return socket.inet_ntoa(data[idx : idx + 4])
            idx += rdlength
    return None


def apply_dns_fallback() -> None:
    orig = socket.getaddrinfo
    cache: dict[str, str] = {}

    def custom(host, port, family=0, type=0, proto=0, flags=0):
        if isinstance(host, str) and "zoho" in host.lower():
            if host not in cache:
                resolved = _dns_query_fallback(host)
                if resolved:
                    cache[host] = resolved
            if host in cache:
                return orig(cache[host], port, family, type, proto, flags)
        try:
            return orig(host, port, family, type, proto, flags)
        except Exception:
            resolved = _dns_query_fallback(host) if isinstance(host, str) else None
            if resolved:
                cache[host] = resolved
                return orig(resolved, port, family, type, proto, flags)
            raise

    socket.getaddrinfo = custom  # type: ignore[method-assign]
