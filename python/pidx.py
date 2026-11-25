#!/usr/bin/env python3
"""PIDX / FSTS archive reader for Konami PSP games (Tokimeki Memorial 4).

Format reverse-engineered with reference to Luigi Auriemma's QuickBMS scripts
macross_pidx.bms 0.2.1 and macross_fsts.bms.
"""
import struct, zlib, os, sys

def u32(d, off):
    return struct.unpack_from('<I', d, off)[0]

class PidxEntry:
    __slots__ = ('is_folder','name_off','pack_off','offset','size','zsize','name','pack')
    def __repr__(self):
        return f'<Entry {self.name!r} off={self.offset:#x} size={self.size:#x} zsize={self.zsize:#x} pack={self.pack!r}>'

class Pidx:
    def __init__(self, data, path=''):
        if data[:4] != b'PIDX':
            raise ValueError('not a PIDX file')
        self.data = data
        self.path = path
        (self.packs_off, self.packs, self.info_off, self.files, self.dummy,
         self.offset2, self.offset2_size, self.names_off, self.names_size) = \
            struct.unpack_from('<9I', data, 4)
        self.names = data[self.names_off:self.names_off+self.names_size]
        self.has_folder = self.files != 0
        self.entries = []
        if self.has_folder:
            pos = self.info_off
            n = self.files
        else:
            pos = self.info_off
            n = u32(data, pos); pos += 4
            pos += n * 4  # skip dummy table (per bms)
        for i in range(n):
            e = PidxEntry()
            if self.has_folder:
                e.is_folder = u32(data, pos); pos += 4
            else:
                e.is_folder = 0
            e.name_off, e.pack_off, e.offset, e.size, e.zsize = struct.unpack_from('<5I', data, pos)
            pos += 20
            e.name = self.get_name(e.name_off)
            e.pack = self.get_name(e.pack_off) if e.pack_off else None
            self.entries.append(e)
        # pack table
        self.pack_table = []
        pos = self.packs_off
        for i in range(self.packs):
            name_off = u32(data, pos)
            h = data[pos+16:pos+32]
            self.pack_table.append((self.get_name(name_off), h))
            pos += 32

    def get_name(self, off):
        if off == 0 or off >= len(self.names):
            return None
        end = self.names.find(b'\0', off)
        if end < 0: end = len(self.names)
        return self.names[off:end].decode('cp932', 'replace')

class FstsEntry:
    __slots__ = ('name_off','offset','size','zsize','name')
    def __repr__(self):
        return f'<FstsEntry {self.name!r} off={self.offset:#x} size={self.size:#x} zsize={self.zsize:#x}>'

class Fsts:
    def __init__(self, data, base=0, fname=''):
        self.base = base
        self.data = data
        self.fname = fname
        if data[base:base+4] != b'FSTS':
            raise ValueError('not FSTS')
        self.files, self.info_off, self.names_off, self.names_size = struct.unpack_from('<4I', data, base+4)
        self.names = data[base+self.names_off: base+self.names_off+self.names_size]
        self.entries = []
        pos = base + self.info_off
        for i in range(self.files):
            name_off, offset, size, zsize = struct.unpack_from('<4I', data, pos); pos += 16
            e = FstsEntry(); e.name_off=name_off; e.offset=offset; e.size=size; e.zsize=zsize
            e.name = self.get_name(name_off)
            self.entries.append(e)

    def get_name(self, off):
        if off >= len(self.names): return None
        end = self.names.find(b'\0', off)
        if end < 0: end = len(self.names)
        return self.names[off:end].decode('cp932','replace')

    def raw(self, e):
        """Return raw (possibly compressed) payload bytes for an entry."""
        return self.data[self.base+e.offset: self.base+e.offset+(e.zsize if e.zsize and e.zsize < e.size else e.size)]

def segs_decompress(d, off=0):
    """Decompress a 'segs' blob (big-endian chunk table, raw deflate chunks).
    Returns (bytes, info)."""
    assert d[off:off+4] == b'segs', d[off:off+4]
    flags, chunks, full_size, full_zsize = struct.unpack_from('>HHII', d, off+4)
    table_off = off + 12
    base2_off = table_off + chunks*8
    out = bytearray()
    pos = table_off
    workaround = False
    for i in range(chunks):
        zsize, size, o = struct.unpack_from('>HHI', d, pos); pos += 8
        o -= 1
        if i == 0 and o == 0: workaround = True
        abs_off = o + (base2_off if workaround else off)
        if size == 0: size = 0x10000
        if size == zsize:
            chunk = d[abs_off:abs_off+zsize]
        else:
            chunk = zlib.decompress(d[abs_off:abs_off+zsize], -15)
        out += chunk
    assert len(out) == full_size, (len(out), full_size)
    return bytes(out)

def lzss3_decompress(data, out_size, ring=4096, start=4096-18, xor=0x72):
    """Konami/CC2 ' 3;1' LZSS.

    Body is XOR-0x72. Flag byte, bits LSB-first, 1=literal, 0=match.
    Match token: 2 bytes big-endian, low nibble = length-3, high 12 bits =
    ring position stored nibble-reversed. Ring is filled with zeros and the
    write pointer starts at 4096-18 (Okumura LZSS N-F).
    """
    win = bytearray(ring)
    wpos = start
    out = bytearray()
    i = 0
    n = len(data)
    while len(out) < out_size:
        if i >= n:
            raise ValueError('truncated LZSS stream')
        flag = data[i] ^ xor
        i += 1
        for bit in range(8):
            if len(out) >= out_size:
                break
            if (flag >> bit) & 1:
                if i >= n:
                    raise ValueError('truncated literal')
                c = data[i] ^ xor
                i += 1
                out.append(c)
                win[wpos] = c
                wpos = (wpos + 1) % ring
            else:
                if i + 1 >= n:
                    raise ValueError('truncated match')
                t = ((data[i] ^ xor) << 8) | (data[i+1] ^ xor)
                i += 2
                ln = (t & 0xF) + 3
                v = t >> 4
                pos = ((v & 0xF) << 8) | (v >> 4)
                for k in range(ln):
                    c = win[(pos + k) % ring]
                    out.append(c)
                    win[wpos] = c
                    wpos = (wpos + 1) % ring
                    if len(out) >= out_size:
                        break
    return bytes(out)

def unwrap_3x(data, off, size, zsize):
    """Handle the ' 3;0'/' 3;1' wrapper at data[off:off+zsize]."""
    sign = data[off:off+4]
    if sign == b' 3;0':
        # stored: u32 size follows, payload is raw
        return data[off+8:off+8+size]
    if sign == b' 3;1':
        return lzss3_decompress(data[off+8:off+zsize], size)
    return None

def decompress_payload(data, off, size, zsize):
    """Given container data and an entry's offset/size/zsize, return decompressed bytes."""
    if zsize == 0 or zsize >= size:
        # Some entries store raw data but with a ' 3;0' wrapper (zsize == size+8)
        sign = data[off:off+4]
        if sign == b' 3;0':
            return data[off+8:off+8+size]
        return data[off:off+size]
    sign = data[off:off+4]
    if sign == b'FSTS':
        return data[off:off+size]
    if sign == b'segs':
        return segs_decompress(data, off)
    if sign in (b' 3;0', b' 3;1'):
        res = unwrap_3x(data, off, size, zsize)
        if res is not None:
            return res
    return zlib.decompress(data[off:off+zsize])
