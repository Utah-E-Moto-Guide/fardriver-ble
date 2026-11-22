"""Unpack a Xamarin assemblies.blob (XABA v1) into DLL files. Pure Python, no deps.

Used to pull the .NET assemblies out of the official Fardriver Android APK so
they can be decompiled locally. Keep the APK, DLLs and decompiled output OUT of
this repo (see .gitignore); they are Fardriver's code.

Usage: python3 -I unpack_xamarin_blob.py assemblies.blob assemblies.manifest outdir
"""

import struct
import sys
from pathlib import Path


def lz4_block_decompress(src: bytes, out_len: int) -> bytes:
    out = bytearray()
    i, n = 0, len(src)
    while i < n:
        token = src[i]
        i += 1
        lit = token >> 4
        if lit == 15:
            while True:
                b = src[i]
                i += 1
                lit += b
                if b != 255:
                    break
        out += src[i : i + lit]
        i += lit
        if i >= n:
            break
        off = src[i] | (src[i + 1] << 8)
        i += 2
        mlen = token & 15
        if mlen == 15:
            while True:
                b = src[i]
                i += 1
                mlen += b
                if b != 255:
                    break
        mlen += 4
        start = len(out) - off
        for k in range(mlen):
            out.append(out[start + k])
    assert len(out) == out_len, (len(out), out_len)
    return bytes(out)


def main(blob_path, manifest_path, outdir):
    blob = Path(blob_path).read_bytes()
    magic, version, local_count, global_count, blob_id = struct.unpack_from("<5I", blob, 0)
    assert magic == 0x41424158, hex(magic)
    print(f"XABA v{version}: {local_count} local, {global_count} global, id {blob_id}")

    names = {}
    for line in Path(manifest_path).read_text(encoding="utf-8").splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 5 and int(parts[2]) == blob_id:
            names[int(parts[3])] = parts[4]

    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    pos = 20
    for idx in range(local_count):
        off, size, *_ = struct.unpack_from("<6I", blob, pos)
        pos += 24
        data = blob[off : off + size]
        if data[:4] == b"XALZ":
            _, _, ulen = struct.unpack_from("<3I", data, 0)
            data = lz4_block_decompress(data[12:], ulen)
        (out / f"{names.get(idx, f'asm{idx}')}.dll").write_bytes(data)
    print("wrote", local_count, "assemblies to", out)


if __name__ == "__main__":
    main(*sys.argv[1:4])
