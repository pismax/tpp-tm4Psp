#!/usr/bin/env python3
"""TSID message table parser/rebuilder for Tokimeki Memorial 4.

Field types (TSTD bytes):
  1 = int32   2 = int16   3 = int8   4 = uint32
  5 = uint16  6 = uint8   7 = float32 9 = SJIS C string

TSD block payload: `count` records. Each record: u16 n (number of present
fields, <= len(types)), then fields[0:n] encoded in order. Payload is padded
with zero bytes at the end (usually to 16 bytes).
"""
import struct

TYPE_SIZE = {1: 4, 2: 2, 3: 1, 4: 4, 5: 2, 6: 1, 7: 4}

class Record:
    __slots__ = ('n', 'fields', 'raw_tail')
    def __init__(self, n, fields):
        self.n = n
        self.fields = fields  # list of (type, value_bytes or str)
    def __repr__(self):
        return f'<Rec n={self.n} {self.fields!r}>'

class Block:
    def __init__(self, magic, count, f1, f2, payload, size):
        self.magic = magic; self.count = count; self.f1 = f1; self.f2 = f2
        self.payload = payload; self.size = size
        self.records = [] if magic == b'TSDD' else None

class Tsid:
    def __init__(self):
        self.count = 0; self.data_off = 0; self.f1 = 0; self.f2 = 0
        self.names = []; self.blocks = []
        self.tstt = []; self.tstd = []; self.tsdd = None
        self.padding = b''

    @staticmethod
    def parse(data):
        if data[:4] != b'TSID':
            raise ValueError('not TSID')
        t = Tsid()
        t.count, t.data_off, t.f1, t.f2 = struct.unpack_from('<IIHH', data, 4)
        pos = 0x10
        for _ in range(t.count):
            e = data.find(b'\0', pos)
            if e < 0: raise ValueError('names truncated')
            t.names.append(data[pos:e])
            pos = e + 1
        pos = t.data_off
        while pos + 16 <= len(data):
            magic = data[pos:pos+4]
            if magic not in (b'TSTT', b'TSTD', b'TSDD'):
                break
            cnt, size, f1, f2 = struct.unpack_from('<IIHH', data, pos+4)
            if size < 16 or pos + size > len(data):
                raise ValueError(f'bad block size {size} at {pos:#x}')
            payload = data[pos+16:pos+size]
            b = Block(magic, cnt, f1, f2, payload, size)
            t.blocks.append(b)
            pos += size
        t.end = pos
        t.trailing = data[pos:]
        # parse TSTT field names and TSTD types
        for b in t.blocks:
            if b.magic == b'TSTT':
                p = 0
                for _ in range(b.count):
                    e = b.payload.find(b'\0', p)
                    if e < 0: raise ValueError('TSTT truncated')
                    t.tstt.append(b.payload[p:e]); p = e + 1
            elif b.magic == b'TSTD':
                t.tstd = list(b.payload[:b.count])
            elif b.magic == b'TSDD':
                t.tsdd = b
                t._parse_tsdd(b)
        return t

    def _parse_tsdd(self, b):
        types = self.tstd
        p = 0; payload = b.payload
        for i in range(b.count):
            if p + 2 > len(payload): raise ValueError('TSD truncated')
            n = struct.unpack_from('<H', payload, p)[0]; p += 2
            if n > len(types): raise ValueError(f'record {i}: n={n} > types {len(types)}')
            fields = []
            for t in types[:n]:
                if t == 9:
                    e = payload.find(b'\0', p)
                    if e < 0: raise ValueError('string truncated')
                    fields.append((t, payload[p:e])); p = e + 1
                elif t in TYPE_SIZE:
                    sz = TYPE_SIZE[t]
                    if p + sz > len(payload): raise ValueError('scalar overrun')
                    fields.append((t, payload[p:p+sz])); p += sz
                else:
                    raise ValueError(f'unknown type {t}')
            b.records.append(Record(n, fields))
        self.tsdd_used = p
        self.tsdd_pad = payload[p:]
        # The loader allocates this string pool before converting strings to
        # pointers. A stale pool size corrupts its heap after longer name edits.
        # The large voice table has a different convention; retain that header.
        self.tsdd_f1_formula = b.f1 == sum(len(v) + 1 for r in b.records for t, v in r.fields if t == 9)

    def encode(self, new_tsdd_payload=None, keep_size_pad=True):
        """Rebuild the TSID file. If new_tsdd_payload is None, re-encode
        the (possibly modified) records."""
        out = bytearray()
        out += b'TSID'
        out += struct.pack('<IIHH', self.count, self.data_off, self.f1, self.f2)
        for nm in self.names:
            out += nm + b'\0'
        if len(out) < self.data_off:
            out += b'\0' * (self.data_off - len(out))
        # blocks in original order
        for b in self.blocks:
            if b.magic == b'TSDD':
                if new_tsdd_payload is None:
                    payload = self._encode_tsdd_payload()
                    string_bytes, padding = self._tsdd_strsum, self._tsdd_pad
                else:
                    payload = bytes(new_tsdd_payload)
                    payload += b'\0' * (-len(payload) % 16)
                    scratch = Tsid(); scratch.tstd = self.tstd
                    block = Block(b.magic, b.count, b.f1, b.f2, payload, len(payload) + 16)
                    scratch._parse_tsdd(block)
                    string_bytes = sum(len(v) + 1 for r in block.records for t, v in r.fields if t == 9)
                    padding = len(payload) - scratch.tsdd_used
                # pad with zeros to 16-byte boundary (match original style)
                pad = (-(16 + len(payload))) % 16
                payload_padded = payload + b'\0' * pad
                size = 16 + len(payload_padded)
                f1 = string_bytes if self.tsdd_f1_formula else b.f1
                if f1 > 0xffff or padding + pad > 0xffff:
                    raise ValueError('TSID string pool or padding exceeds its 16-bit header budget')
                out += b.magic + struct.pack('<IIHH', b.count, size, f1, padding + pad)
                out += payload_padded
            else:
                out += b.magic + struct.pack('<IIHH', b.count, b.size, b.f1, b.f2)
                out += b.payload
        return bytes(out)

    def _encode_tsdd_payload(self):
        payload = bytearray()
        string_bytes = 0
        for r in self.tsdd.records:
            payload += struct.pack('<H', r.n)
            for t, v in r.fields:
                if t == 9:
                    payload += v + b'\0'
                    string_bytes += len(v) + 1
                else:
                    payload += v
        # pad to multiple of 16 like the original (payload + 16 header)
        pad = (-(16 + len(payload))) % 16
        payload += b'\0' * pad
        self._tsdd_strsum, self._tsdd_pad = string_bytes, pad
        return bytes(payload)
