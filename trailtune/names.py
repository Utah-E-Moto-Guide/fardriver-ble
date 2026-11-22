"""Helpers on top of address_map: labels, serial number, save timestamp."""

from .address_map import BY_ADDR

SERIAL_ADDRS = range(0xA1, 0xAB)
SAVE_TIME_ADDRS = (0x22, 0x23, 0x24)


def label(addr: int) -> str:
    return "; ".join(f.name for f in BY_ADDR.get(addr, []))


def decode_serial(words: dict[int, int]) -> str:
    raw = b"".join(words.get(a, 0).to_bytes(2, "little") for a in SERIAL_ADDRS)
    return raw.split(b"\x00")[0].decode("ascii", errors="replace")


def decode_save_time(words: dict[int, int]) -> str:
    """Last settings save, as written by the saving app from the phone clock."""
    b = [x for a in SAVE_TIME_ADDRS for x in words.get(a, 0).to_bytes(2, "little")]
    return f"20{b[0]:02d}-{b[1]:02d}-{b[2]:02d} {b[3]:02d}:{b[4]:02d}:{b[5]:02d}"
