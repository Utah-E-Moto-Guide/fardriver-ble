"""Turn 0xAA status frames (ids 0..54) into a {address: u16} memory snapshot.

Each frame id maps to a start address; the frame carries six little-endian u16
words for that address and the next five. Ids that map to 0xE2/0xE8/0xEE repeat
every 7 frames and carry live telemetry; the rest are parameter blocks.
Map from jackhumbert/fardriver-controllers (MIT, see THIRD_PARTY_NOTICES.md), matched to our capture.
"""

FLASH_READ_ADDR = (
    0xE2, 0xE8, 0xEE, 0x00, 0x06, 0x0C, 0x12,
    0xE2, 0xE8, 0xEE, 0x18, 0x1E, 0x24, 0x2A,
    0xE2, 0xE8, 0xEE, 0x30, 0x5D, 0x63, 0x69,
    0xE2, 0xE8, 0xEE, 0x7C, 0x82, 0x88, 0x8E,
    0xE2, 0xE8, 0xEE, 0x94, 0x9A, 0xA0, 0xA6,
    0xE2, 0xE8, 0xEE, 0xAC, 0xB2, 0xB8, 0xBE,
    0xE2, 0xE8, 0xEE, 0xC4, 0xCA, 0xD0,
    0xE2, 0xE8, 0xEE, 0xD6, 0xDC, 0xF4, 0xFA,
)  # fmt: skip
TELEMETRY_ADDRS = {0xE2, 0xE8, 0xEE}


def words(frame: bytes) -> list[int]:
    return [frame[i] | (frame[i + 1] << 8) for i in range(2, 14, 2)]


def frame_block(frame: bytes) -> tuple[int, list[int]] | None:
    """(start address, six words) for a CRC-checked status frame, else None."""
    fid = frame[1] & 0x7F
    if fid >= len(FLASH_READ_ADDR):
        return None
    return FLASH_READ_ADDR[fid], words(frame)


def parse_raw_log(path) -> list[bytes]:
    """Re-frame the RX lines of a captures/*/raw_notifications.txt log."""
    from .crc import frame_ok

    stream = bytearray()
    for line in open(path):
        parts = line.split()
        if len(parts) == 3 and parts[1] == "RX":
            stream += bytes.fromhex(parts[2])
    frames, i = [], 0
    while i + 16 <= len(stream):
        f = bytes(stream[i : i + 16])
        if f[0] == 0xAA and f[1] & 0x80 and frame_ok(f):
            frames.append(f)
            i += 16
        else:
            i += 1
    return frames


# The app's .heb export: first 312 bytes are these 26 blocks (156 words), packed in
# address order. Verified 2026-11-21 against an exported .heb: 142/156 words equal,
# the rest explained by setting changes since. 0x5D, 0xD6, 0xDC, 0xF4, 0xFA are not in
# the file; they hold the counter-like words.
HEB_BLOCKS = tuple(sorted(a for a in set(FLASH_READ_ADDR) - TELEMETRY_ADDRS if a <= 0xD0 and a != 0x5D))
HEB_ADDRS = tuple(a + k for a in HEB_BLOCKS for k in range(6))
assert len(HEB_ADDRS) == 156


def heb_main_words(heb: bytes) -> dict[int, int]:
    """{address: u16} for the first section of a 696-byte .heb file."""
    import struct

    assert len(heb) == 696, len(heb)
    return dict(zip(HEB_ADDRS, struct.unpack("<156H", heb[:312]), strict=True))
