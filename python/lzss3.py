#!/usr/bin/env python3
"""Encoder for the TM4 ' 3;1' LZSS format (compatible with lzss3_decompress)."""
import struct, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pidx import lzss3_decompress

N = 4096
F = 18
MIN_LEN = 3
XOR = 0x72
START = N - F  # 4078


def _v_from_pos(pos):
    """Inverse of decoder mapping pos = ((v & 0xF) << 8) | (v >> 4)."""
    pos &= 0xFFF
    return (((pos & 0x0F0) >> 4) << 8) | ((pos & 0x00F) << 4) | ((pos & 0xF00) >> 8)


def _ring(file_pos):
    return (START + file_pos) % N


def compress_body(data: bytes) -> bytes:
    n = len(data)
    out = bytearray()
    # hash of 3-byte sequences -> most recent file positions (up to 32 each)
    table = {}
    chain_len = 32
    i = 0
    flag_pos = None
    flags = 0
    bit = 0

    while i < n:
        if flag_pos is None:
            flag_pos = len(out)
            out.append(0)
            flags = 0
            bit = 0
        best_len = 0
        best_pos = 0
        if i + MIN_LEN <= n:
            key = data[i:i+3]
            lst = table.get(key)
            if lst:
                for p in reversed(lst):
                    if i - p > N:
                        break
                    # quick check last possible byte
                    if data[p + best_len] != data[i + best_len]:
                        continue
                    ln = 0
                    lim = min(F, n - i)
                    while ln < lim and data[p + ln] == data[i + ln]:
                        ln += 1
                    if ln > best_len:
                        best_len = ln
                        best_pos = p
                        if ln == lim:
                            break
        if best_len >= MIN_LEN:
            flags &= ~(1 << bit)
            pos_field = _v_from_pos(_ring(best_pos))
            tok = (pos_field << 4) | (best_len - MIN_LEN)
            out.append((tok >> 8) & 0xFF)
            out.append(tok & 0xFF)
            # add positions i..i+best_len-1 to the hash table
            for k in range(best_len):
                q = i + k
                if q + 2 < n:
                    table.setdefault(data[q:q+3], []).append(q)
                    if len(table[data[q:q+3]]) > chain_len:
                        table[data[q:q+3]].pop(0)
            i += best_len
        else:
            flags |= (1 << bit)
            out.append(data[i])
            if i + 2 < n:
                table.setdefault(data[i:i+3], []).append(i)
                if len(table[data[i:i+3]]) > chain_len:
                    table[data[i:i+3]].pop(0)
            i += 1
        out[flag_pos] = flags
        bit += 1
        if bit == 8:
            flag_pos = None
    return bytes(b ^ XOR for b in out)


def wrap(data: bytes, force_stored=False) -> bytes:
    if not force_stored:
        body = compress_body(data)
        wrapped = b' 3;1' + struct.pack('<I', len(data)) + body
        if len(wrapped) < len(data) + 8:
            return wrapped
    return b' 3;0' + struct.pack('<I', len(data)) + data


def unwrap(data: bytes, size: int) -> bytes:
    if data[:4] == b' 3;0':
        return data[8:8+size]
    if data[:4] == b' 3;1':
        return lzss3_decompress(data[8:], size)
    raise ValueError('not 3;x')


if __name__ == '__main__':
    from pidx import Pidx, decompress_payload
    d = open('original_files/pack/tokimeki.dat', 'rb').read()
    idx = open('original_files/pack/tokimeki.idx', 'rb').read()
    p = Pidx(idx)
    tests = 0
    for e in p.entries:
        if e.is_folder or not e.name or not e.name.endswith('.dat'):
            continue
        raw = decompress_payload(d, e.offset, e.size, e.zsize)
        w = wrap(raw)
        back = unwrap(w, len(raw))
        assert back == raw, e.name
        print(f'{e.name}: {len(raw)} -> {len(w)} (orig {e.zsize})')
        tests += 1
        if tests >= 12:
            break
    print('ok', tests)
