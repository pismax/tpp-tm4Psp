"""Verified single-byte Latin patch. No executable or font data is distributed.

The game already maps ASCII to its own full-width atlas. Scale only that path
to 8x16 and fix the scenario loop which otherwise discards all single bytes.
Guest addresses below describe the relocated image at 0x08804000; patch words
are ELF words before PSP relocation (notably the LWC1 immediate).
"""
import hashlib
import struct

PROFILE = 'tm4-ascii-8x16-v1'
SOURCE_SHA256 = '7068e4cb62a1eb2761d207564182fddb72dcb7703f1ffc2d292b5b88a4f5886d'
ATLAS_SHA256 = 'fbae09c4c7626d4baaa0009df9fa9e1eb9b83f8a562112a6764edd5fa1311124'
ATLAS_SIZE = 445440
WEIGHTS = ('regular', 'bold')
PATCHES = {
    # Generic glyph advance: return size/2 for ASCII, retaining double-byte size.
    0x08834ff0: (0x44801000, 0x00062043),
    0x08834ff4: (0x46800820, 0x1000ffbe),
    0x08834ff8: (0xc501001c, 0x00000000),
    # ASCII glyph quad width: 0.75 -> existing 0.5 constant, height unchanged.
    0x08835d9c: (0xc4405488, 0xc4405480),
    # Scenario records are little-endian SJIS u16. Accept ASCII <0x80 as
    # well as double-byte characters, retain skipping unsupported half-kana.
    # t5=1 for ASCII, 0 for SJIS lead bytes. Advance 16 - (t5 << 3).
    0x088710f8: (0x2462ff7f, 0x2c6d0080),  # sltiu t5,v1,0x80
    0x088710fc: (0x10800014, 0x14800003),  # bne a0,zero,0x0887110c
    0x08871100: (0x2c4d001f, 0x02202821),  # move a1,s1 (delay slot)
    0x08871104: (0x2462ff20, 0x11a00012),  # beq t5,zero,0x08871150
    0x08871108: (0x02202821, 0x00000000),
    0x08871110: (0x2c42001d, 0x000d68c0),  # sll t5,t5,3
    0x0887112c: (0x15a00003, 0x022d8823),  # subu s1,s1,t5
    0x08871134: (0x50400007, 0x00000000),
    0x08871138: (0x26520001, 0x00000000),
}


def file_offset(address):
    return address - 0x08804000 + 0xc0


def patch(raw):
    if raw[:4] != b'\x7fELF':
        raise ValueError('Half-width text needs a decrypted EBOOT.BIN (ELF), not the encrypted ISO EBOOT or dummy BOOT.BIN. Select the PPSSPP executable dump.')
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError('Unsupported decrypted TM4 executable. Select an unmodified EBOOT.BIN dumped from the original Japanese game. This patch supports only the verified executable fingerprint.')
    out = bytearray(raw)
    for address, (old, new) in PATCHES.items():
        offset = file_offset(address)
        if struct.unpack_from('<I', raw, offset)[0] != old:
            raise ValueError(f'TM4 executable instruction mismatch at {address:08x}')
        struct.pack_into('<I', out, offset, new)
    return bytes(out)


def inspect(raw):
    result = patch(raw)
    return {'profile': PROFILE, 'sourceSha256': SOURCE_SHA256,
            'patchedSha256': hashlib.sha256(result).hexdigest(),
            'patchWords': len(PATCHES), 'asciiWidth': 8, 'glyphHeight': 16,
            'requires': 'PPSSPP or PSP custom firmware (unsigned decrypted ELF)'}


def glyph_pixel(index, x, y):
    """Paired 2-bit glyph planes in the linear 384x384 texture pages."""
    page, cell = index // 1152, (index % 1152) // 2
    px, py = (cell % 24) * 16 + x, (cell // 24) * 16 + y
    return page * 0x12000 + py * 192 + px // 2, (px % 2) * 4 + (index % 2) * 2


def bold_atlas(raw, executable):
    """Thicken Latin/digits only; preserve both the paired glyph and all metrics.

    The renderer compresses a 16-pixel source glyph to 8 pixels. A horizontal
    maximum over x-1..x+1 adds about one displayed pixel of stroke weight.
    Vertical strokes/counters are not expanded vertically. Full-width Latin
    shares these exact glyphs and therefore receives the same heavier strokes.
    """
    patch(executable)  # Authoritative executable and lookup-table identity guard.
    if len(raw) != ATLAS_SIZE or hashlib.sha256(raw).hexdigest() != ATLAS_SHA256:
        raise ValueError('Unsupported TM4 font atlas; bold text requires the verified original tm4_font16.fnt')
    # The lookup is in the ELF's second PT_LOAD segment, unlike the code sites.
    lookup_offset = 0x314b00 + 0x08b197c0 - 0x08b18a00
    codes = struct.unpack_from('<6960H', executable, lookup_offset)
    ascii_offset = file_offset(0x08adefd4)
    ascii_codes = struct.unpack_from('<96H', executable, ascii_offset)
    lookup = {code: index for index, code in enumerate(codes)}
    indexes = {lookup[ascii_codes[code - 0x20]] for code in range(0x30, 0x7b)
               if chr(code).isalnum()}
    out = bytearray(raw)
    for index in indexes:
        for y in range(16):
            row = []
            for x in range(16):
                offset, shift = glyph_pixel(index, x, y)
                row.append((raw[offset] >> shift) & 3)
            for x in range(16):
                value = max(row[max(0, x - 1):min(16, x + 2)])
                offset, shift = glyph_pixel(index, x, y)
                out[offset] = (out[offset] & ~(3 << shift)) | (value << shift)
    result = bytes(out)
    return result, {'profile': 'tm4-latin-bold-v1', 'weight': 'bold',
                    'glyphs': len(indexes), 'sourceSha256': ATLAS_SHA256,
                    'patchedSha256': hashlib.sha256(result).hexdigest(),
                    'sharedWithFullWidthLatin': True}
