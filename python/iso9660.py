#!/usr/bin/env python3
"""Minimal ISO9660 parser/patcher for the TM4 PSP image (streaming)."""
import struct, os, sys

SECTOR = 2048


def both32(buf, off, value):
    struct.pack_into('<I', buf, off, value)
    struct.pack_into('>I', buf, off + 4, value)


def get_both32(buf, off):
    return struct.unpack_from('<I', buf, off)[0]


class IsoFile:
    __slots__ = ('path', 'rec_off', 'lba', 'size', 'is_dir')
    def __init__(self, path, rec_off, lba, size, is_dir):
        self.path = path; self.rec_off = rec_off
        self.lba = lba; self.size = size; self.is_dir = is_dir
    def __repr__(self):
        return f'<{self.path} lba={self.lba} size={self.size} dir={self.is_dir}>'


def parse_iso(path):
    f = open(path, 'rb')
    f.seek(16 * SECTOR)
    pvd = f.read(SECTOR)
    if pvd[0] != 1 or pvd[1:6] != b'CD001':
        raise ValueError('no PVD')
    files = []
    seen = set()

    def walk(lba, size, prefix):
        f.seek(lba * SECTOR)
        data = f.read(size)
        pos = 0
        while pos < size:
            ln = data[pos]
            if ln == 0:
                pos = ((pos // SECTOR) + 1) * SECTOR
                continue
            rec = data[pos:pos+ln]
            ext = get_both32(rec, 2)
            sz = get_both32(rec, 10)
            flags = rec[25]
            nlen = rec[32]
            name = rec[33:33+nlen]
            if name in (b'\x00', b'\x01'):
                pos += ln
                continue
            name_s = name.decode('latin1')
            p = prefix + '/' + name_s if prefix else name_s
            rec_off = lba * SECTOR + pos
            if flags & 2:
                if p not in seen:
                    seen.add(p)
                    files.append(IsoFile(p, rec_off, ext, sz, True))
                    if p.count('/') < 8:
                        walk(ext, sz, p)
            else:
                files.append(IsoFile(p, rec_off, ext, sz, False))
            pos += ln

    root_lba = get_both32(pvd, 156 + 2)
    root_size = get_both32(pvd, 156 + 10)
    walk(root_lba, root_size, '')
    f.close()
    return files


def patch_iso(src, dst, replacements: dict, verbose=False):
    """Stream-copy src to dst, replacing files by ISO path."""
    files = parse_iso(src)
    by_path = {f.path: f for f in files if not f.is_dir}
    for p in replacements:
        if p not in by_path:
            raise KeyError('ISO file not found: ' + p)
    src_size = os.path.getsize(src)
    total_sectors = (src_size + SECTOR - 1) // SECTOR
    with open(src, 'rb') as fi, open(dst, 'w+b') as fo:
        # copy whole source
        while True:
            chunk = fi.read(1 << 20)
            if not chunk:
                break
            fo.write(chunk)
        # in-place replacements
        for path, blob in replacements.items():
            f = by_path[path]
            capacity = ((f.size + SECTOR - 1) // SECTOR) * SECTOR
            if len(blob) <= capacity and f.size > 0:
                fo.seek(f.lba * SECTOR)
                fo.write(blob)
                if capacity > len(blob):
                    fo.write(b'\0' * (capacity - len(blob)))
                # patch directory record size
                fo.seek(f.rec_off)
                rec = bytearray(fo.read(40))
                both32(rec, 10, len(blob))
                fo.seek(f.rec_off)
                fo.write(rec)
                if verbose: print(' inplace', path, 'lba', f.lba, 'size', len(blob))
            else:
                fo.seek(0, 2)
                off = fo.tell()
                pad = (-off) % SECTOR
                if pad: fo.write(b'\0' * pad); off += pad
                fo.write(blob)
                new_lba = off // SECTOR
                fo.seek(f.rec_off)
                rec = bytearray(fo.read(40))
                both32(rec, 2, new_lba)
                both32(rec, 10, len(blob))
                fo.seek(f.rec_off)
                fo.write(rec)
                if verbose: print(' append', path, 'lba', new_lba, 'size', len(blob))
                total_sectors = max(total_sectors, (fo.tell() + SECTOR - 1) // SECTOR)
        # pad image and update PVD volume space size
        end = fo.seek(0, 2)
        pad = (-end) % SECTOR
        if pad: fo.write(b'\0' * pad)
        total_sectors = fo.tell() // SECTOR
        fo.seek(16 * SECTOR)
        pvd = bytearray(fo.read(SECTOR))
        both32(pvd, 80, total_sectors)
        fo.seek(16 * SECTOR)
        fo.write(pvd)
    return total_sectors


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Inspect an ISO9660 disc image')
    parser.add_argument('iso', help='Path to the ISO to inspect')
    src = parser.parse_args().iso
    files = parse_iso(src)
    for f in files[:25]:
        print(f)
    print('total entries', len(files))
