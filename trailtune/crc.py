"""Checksums used on the Fardriver controller link.

The "new" 16-byte frames use CRC-16/MODBUS (reflected poly 0xA001) started at
0x7F3C instead of 0xFFFF. The two CRC bytes go on the wire low byte first.
The 8-byte command frames use a plain additive byte sum plus its complement.
"""

INIT = 0x7F3C


def crc16(data: bytes, init: int = INIT) -> int:
    crc = init
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def crc16_bytes(data: bytes) -> bytes:
    c = crc16(data)
    return bytes((c & 0xFF, c >> 8))


def frame_ok(frame: bytes) -> bool:
    """True when a 16-byte new-format frame's last two bytes match its CRC."""
    return len(frame) == 16 and crc16_bytes(frame[:14]) == frame[14:16]


def command_frame(cmd: int, sub: int, v1: int, v2: int) -> bytes:
    """8-byte command frame: AA cmd ~cmd sub v1 v2 sum ~sum."""
    body = bytes((0xAA, cmd, (~cmd) & 0xFF, sub, v1, v2))
    s = sum(body) & 0xFF
    return body + bytes((s, (~s) & 0xFF))
