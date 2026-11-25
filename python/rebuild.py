#!/usr/bin/env python3
"""Rebuild TM4 pack containers (PIDX/FSTS) and tokimeki.dat / tokimeki.idx
with modified inner files.

Modifications are read from a directory mirroring dump/extracted:
  mods/tokimeki/00026_m_charmake_msg.dat
  mods/packs/title_menu.dat/disc/common/msgtbl/m_system_m_system.dat
Unmodified files are copied bit-exactly.
"""
import os, sys, struct, json, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pidx import Pidx, Fsts, decompress_payload, unwrap_3x
import lzss3

ALIGN_DATA = 0x800
ALIGN_INNER = 0x10



def raw_payload(data, off, size, zsize):
    sig = data[off:off+4]
    if sig == b'FSTS':
        return data[off:off+size]
    if sig in (b' 3;1', b' 3;0'):
        return data[off:off+zsize]
    if zsize and zsize < size:
        return data[off:off+zsize]
    return data[off:off+size]

def align(v, a):
    return (v + a - 1) & ~(a - 1)


def build_fsts(blob, fsts, replacements):
    """Patch only changed members, preserving the loader-sensitive FSTS layout.

    slg_ctbl.dat hangs at startup after a dense repack, even when our decoder
    can recover identical resources. Keep the original name table, padding,
    untouched entry metadata and payload positions. Grow a changed entry into
    its original gap or append it; never overwrite an aliased payload.
    """
    out = bytearray(blob)
    offsets = sorted(set(x.offset for x in fsts.entries))
    counts = {offset: sum(x.offset == offset for x in fsts.entries) for offset in offsets}
    for i, x in enumerate(fsts.entries):
        if x.name not in replacements:
            continue
        content = replacements[x.name]
        if content == decompress_payload(blob, fsts.base + x.offset, x.size, x.zsize):
            continue
        payload = lzss3.wrap(content)
        next_offset = next((offset for offset in offsets if offset > x.offset), len(blob) - fsts.base)
        if counts[x.offset] == 1 and len(payload) <= next_offset - x.offset:
            new_offset = x.offset
        else:
            new_offset = align(len(out) - fsts.base, ALIGN_INNER)
        absolute = fsts.base + new_offset
        if absolute > len(out):
            out += b'\0' * (absolute - len(out))
        out[absolute:absolute + len(payload)] = payload
        struct.pack_into('<4I', out, fsts.base + fsts.info_off + i * 16,
                         x.name_off, new_offset, len(content), len(payload))
    return bytes(out)


def build_pidx_container(orig, replacements):
    """Rebuild a simple PIDX .dat (outer pack or tokimeki.dat)."""
    p = Pidx(orig)
    n_entries = len(p.entries)
    if p.has_folder:
        info_size = n_entries * 24
    else:
        info_size = 4 + n_entries * 4 + n_entries * 20
    names_off = p.names_off
    names_size = p.names_size
    data_start = align(names_off + names_size, ALIGN_DATA)
    # Preserve prefix through the names table.
    out = bytearray(orig[:data_start])
    pos = data_start
    new_entries = []
    for idx, e in enumerate(p.entries):
        if e.is_folder:
            new_entries.append(e)
            continue
        replaced = False
        content = None
        if e.name in replacements:
            content = replacements[e.name]
            wrapped = lzss3.wrap(content)
            usize = len(content)
            replaced = True
        else:
            wrapped = raw_payload(orig, e.offset, e.size, e.zsize)
            usize = e.size
        # place
        pos = align(pos, ALIGN_DATA)
        if pos > len(out):
            out += b'\0' * (pos - len(out))
        if len(out) < pos + len(wrapped):
            out += b'\0' * (pos + len(wrapped) - len(out))
        out[pos:pos+len(wrapped)] = wrapped
        e._new_off = pos; e._new_size = usize; e._new_zsize = len(wrapped)
        pos += len(wrapped)
        new_entries.append(e)
    # patch entry tables
    for idx, e in enumerate(p.entries):
        if e.is_folder:
            continue
        if p.has_folder:
            base = p.info_off + idx * 24
            struct.pack_into('<I', out, base + 12, e._new_off)
            struct.pack_into('<I', out, base + 16, e._new_size)
            struct.pack_into('<I', out, base + 20, e._new_zsize)
        else:
            base = p.info_off + 4 + len(p.entries) * 4 + idx * 20
            struct.pack_into('<I', out, base + 8, e._new_off)
            struct.pack_into('<I', out, base + 12, e._new_size)
            struct.pack_into('<I', out, base + 16, e._new_zsize)
    return bytes(out)


def rebuild_tokimeki(dat_path, idx_path, mods_dir, out_dir):
    dat = open(dat_path, 'rb').read()
    idx = open(idx_path, 'rb').read()
    pi = Pidx(dat, 'tokimeki.dat')
    px = Pidx(idx, 'tokimeki.idx')
    # map internal file entries to idx entry indices
    bykey = {}
    for i, e in enumerate(px.entries):
        if not e.is_folder and e.pack is None:
            bykey[(e.name, e.offset, e.size)] = i
    # gather modifications
    mods = {}
    mod_dir = os.path.join(mods_dir, 'tokimeki')
    if os.path.isdir(mod_dir):
        for fn in os.listdir(mod_dir):
            # filename is {idx:05d}_{name}
            i = int(fn.split('_', 1)[0])
            mods[i] = open(os.path.join(mod_dir, fn), 'rb').read()
    # data area starts after internal index prefix
    data_start = align(pi.names_off + pi.names_size, ALIGN_DATA)
    out = bytearray(dat[:data_start])
    pos = data_start
    idx_updates = {}
    for ii, e in enumerate(pi.entries):
        if e.is_folder:
            continue
        key = (e.name, e.offset, e.size)
        if key not in bykey:
            raise RuntimeError(f'unmatched internal entry {e.name}')
        xi = bykey[key]
        if xi in mods:
            content = mods[xi]
            wrapped = lzss3.wrap(content)
            usize = len(content)
        else:
            wrapped = raw_payload(dat, e.offset, e.size, e.zsize)
            usize = e.size
        pos = align(pos, ALIGN_DATA)
        if len(out) < pos + len(wrapped):
            out += b'\0' * (pos + len(wrapped) - len(out))
        out[pos:pos+len(wrapped)] = wrapped
        # internal entry table: HAS_FOLDER=1, 24-byte records
        base = pi.info_off + ii * 24
        struct.pack_into('<I', out, base + 12, pos)
        struct.pack_into('<I', out, base + 16, usize)
        struct.pack_into('<I', out, base + 20, len(wrapped))
        idx_updates[xi] = (pos, usize, len(wrapped))
        pos += len(wrapped)
    # pad to 0x800
    total = align(pos, ALIGN_DATA)
    if len(out) < total:
        out += b'\0' * (total - len(out))
    # patch tokimeki.idx
    new_idx = bytearray(idx)
    for xi, (off, size, zsize) in idx_updates.items():
        e = px.entries[xi]
        base = px.info_off + xi * 24
        struct.pack_into('<I', new_idx, base + 12, off)
        struct.pack_into('<I', new_idx, base + 16, size)
        struct.pack_into('<I', new_idx, base + 20, zsize)
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, 'tokimeki.dat'), 'wb').write(bytes(out))
    open(os.path.join(out_dir, 'tokimeki.idx'), 'wb').write(bytes(new_idx))
    return len(out), len(new_idx)


def rebuild_pack_files(pack_dir, mods_dir, out_dir, only=None):
    os.makedirs(out_dir, exist_ok=True)
    results = []
    for fn in sorted(os.listdir(pack_dir)):
        if not fn.endswith('.dat') or fn == 'tokimeki.dat':
            continue
        if only and fn not in only:
            continue
        with open(os.path.join(pack_dir, fn), 'rb') as stream:
            orig = stream.read()
        try:
            p = Pidx(orig, fn)
        except Exception:
            continue
        # collect inner modifications for this container
        rep = {}
        modroot = os.path.join(mods_dir, 'packs', fn)
        if os.path.isdir(modroot):
            for dp, dn, fns in os.walk(modroot):
                for f in fns:
                    full = os.path.join(dp, f)
                    rel = os.path.relpath(full, modroot).replace('\\', '/')
                    with open(full, 'rb') as stream:
                        rep[rel] = stream.read()
        if not rep:
            continue
        # Patch only the FSTS archives containing a changed member.
        new_entries = {}
        for idx, e in enumerate(p.entries):
            if e.is_folder:
                continue
            is_raw = orig[e.offset:e.offset + 4] == b'FSTS'
            if is_raw:
                blob = orig[e.offset:e.offset + e.size]
            else:
                blob = unwrap_3x(orig, e.offset, e.size, e.zsize)
            if blob is None or blob[:4] != b'FSTS':
                continue
            newblob = build_fsts(blob, Fsts(blob), rep)
            if newblob != blob:
                # Raw outer FSTS zsize is a type/count flag, not byte length.
                payload = newblob if is_raw else lzss3.wrap(newblob)
                new_entries[idx] = (payload, len(newblob), e.zsize if is_raw else len(payload))
        if not new_entries:
            continue
        out = bytearray(orig)
        entries = [e for e in p.entries if not e.is_folder]
        offsets = sorted(set(e.offset for e in entries))
        for idx, (payload, usize, zflag) in new_entries.items():
            e = p.entries[idx]
            next_offset = next((offset for offset in offsets if offset > e.offset), None)
            aliased = sum(x.offset == e.offset for x in entries) > 1
            limit = next_offset if next_offset is not None else len(orig)
            # A sole final archive can extend in place until another replacement
            # has been appended. Otherwise append safely without moving peers.
            extend_final = next_offset is None and len(out) == len(orig)
            if not aliased and (len(payload) <= limit - e.offset or extend_final):
                offset = e.offset
            else:
                offset = align(len(out), ALIGN_DATA)
            if offset > len(out):
                out += b'\0' * (offset - len(out))
            out[offset:offset + len(payload)] = payload
            if p.has_folder:
                base = p.info_off + idx * 24 + 12
            else:
                base = p.info_off + 4 + len(p.entries) * 4 + idx * 20 + 8
            struct.pack_into('<III', out, base, offset, usize, zflag)
        with open(os.path.join(out_dir, fn), 'wb') as stream:
            stream.write(out)
        results.append((fn, len(orig), len(out)))
    return results


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--pack-dir', default='original_files/pack')
    ap.add_argument('--mods', default='rebuild/modified')
    ap.add_argument('--out', default='rebuild/game/USRDIR/disc/pack')
    ap.add_argument('--only')
    args = ap.parse_args()
    only = set(args.only.split(',')) if args.only else None
    r = rebuild_pack_files(args.pack_dir, args.mods, args.out, only)
    print('rebuilt packs:', r)
    # tokimeki needs its own handling if only not restricting
    if not only or 'tokimeki' in only:
        sizes = rebuild_tokimeki(os.path.join(args.pack_dir, 'tokimeki.dat'),
                                 os.path.join(args.pack_dir, 'tokimeki.idx'),
                                 args.mods, args.out)
        print('tokimeki:', sizes)
