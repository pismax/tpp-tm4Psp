# Tokimeki Memorial 4 (PSP)

Parser 1.2.5 supports the application's shared Validation panel (Translator++
8.11.9 required). Normal Batch Translation and Batch API import offer granular
Block/Warn/Off controls and presets, saved per project. Contextual `\hNN` address
omissions can warn or be ignored through export. Selectors cannot be changed,
functional controls remain required, and export always protects CP932 encoding,
fixed byte capacity and the physical three-line message-box limit. Width is an
editable guideline unless its check is set to Block.

Open the Japanese **ULJM-05541** PSP ISO in Translator++ and translate dialogue,
message tables, CSV cells, and interface textures. Export or Inject writes a
separate `.translated.iso`; it never modifies the source disc.

## Use

1. Start a new project and choose **Tokimeki Memorial 4 (PSP)**, or let engine
   detection identify the ISO. Select the original Japanese disc.
2. Keep **Include editable interface images** enabled to add PNG previews to
   the Images pane. Optional OCR uses your configured OCR engine; Windows
   OneOCR runs locally. Images without detected text remain manually editable.
3. Translate in the grid. Row information shows names recovered from character
   tables and static message setup instructions. The male player protagonist is
   labelled **MC**, including the opening scene's “あなた” speaker. His name is
   player-defined. Unresolved speakers remain blank.
4. Translate image text boxes, use Image Translator's editing layers, or open an
   image with its built-in Krita command. Preserve texture dimensions and sprite
   placement; labels are often packed together on one texture sheet.
5. Export to a folder, export a ZIP, or Inject into a destination folder. These
   operations build a new ISO plus an export report. Correct any validation
   errors before retrying. Keep the original ISO available after reopening.

If you move or rename the original ISO, choose its new folder (or the ISO file)
as **Source material** in Inject. The add-on verifies the imported disc's SHA-256
and remembers the new path after verification. Save the project to keep
that location after reopening. Export also recognises the common case of moving
`Game.iso` into an adjacent `Game/Game.iso` folder. A different or already patched
ISO is rejected with an explanation.

The project stores original resource bytes and image previews in its staging
cache. Keep that cache when moving a `.trans` project, or use Translator++'s
project packaging workflow. Original disc data is never included with this add-on.

Existing TM4 projects receive missing MC row information automatically when
opened with this add-on. Save to retain it. Each identified occurrence also has
`speakerRole: "protagonist"`, `speakerGender: "male"` and
`speakerNameIsVariable: true` in its row parameters. Translation engines vary in
which metadata they use; include “MC is the male protagonist” in your translation
context when needed. The Actor Reference below supplies this context to shared
chat AI engines. These labels do not replace name control codes in game text.

## Re-exporting translated name tables

Version 1.2.3 fixes a startup **NOW LOADING** hang after translating character
names or other shared tables. Re-inject/export with the updated add-on; existing
projects and translations need no migration. The writer now updates text-table
string-pool allocation sizes and keeps untouched archive members at their
original positions. Previously exported ISOs must be
rebuilt; updating the add-on cannot repair an ISO already on disk.

## Thicker half-width letters

In **Tools → Tokimeki Memorial 4 (PSP) → Configure half-width alphabet**, choose
**Bold** and click **Enable**. When half-width support was previously configured,
leave the executable field blank to reuse the staged original. Save the project,
then Inject/export to a new ISO. Existing projects continue using **Regular**
until changed; choose Regular to restore the previous appearance on export.

Bold adds horizontal stroke weight to the game's 62 Latin letters and digits.
ASCII remains 8×16 with an 8-pixel advance, so byte budgets and line lengths do
not change. Full-width Latin shares those glyphs and also becomes bolder.
Japanese letters, punctuation, and the other glyph plane stay unchanged. The
font atlas is checked against the supported original before patching, and the
rebuilt resource is verified before the ISO is delivered.

## AI translation guidance and source CRC

Version 1.2 adds a game prompt, verified syntax instructions and an editable
**Actor Reference** with 15 entries: MC, the twelve heroines and the two male
friends. Column 1 contains English name transliterations; column 2 contains
gender, personality and suggested translation voice. Facts have source links in
row parameters; voice directions are editorial suggestions. Existing edits and
explicitly empty prompts survive reopen/update. Names are project defaults,
including **Rizumi Kyono** with **Rhythmy Kyono** recorded as an alternate spelling.

Edit instructions through **Translator → Prompts**, and names/personality in
Actor Reference. Shared chat AI engines include the mentioned speakers through
`${ACTOR_INFO}`; retain that variable in custom system prompts. The reference's
information column is excluded from translated-name lookup.

**Tools → Tokimeki Memorial 4 (PSP) → Translation limits and source CRC** controls
AI validation and optional source checking. Defaults for scenario dialogue are
**44 stored characters per line** and **3 lines**. Classified ASB message boxes
may use fewer or more lines within those limits. Enable **Message boxes: require
the exact original number of lines** for strict behaviour. Unclassified ASB text
and tables retain their original line structure. The 44-character value is an editable English translation guideline,
not a measured pixel boundary. All original ASB messages have one to three lines.
Menu/table text has separate rules; images and reference tables do not inherit
scenario/CP932 AI restrictions. Glyph widths and expanded names need game testing.

Parameters record `messageType: "messageBox"` when every detected reference uses
the verified direct ASB display-function-0 operand; other ASB strings are marked
`unknown`. Existing projects reuse the saved `canGrow:true` reference evidence
on reopen. Context IDs and translations are preserved, and mixed uses retain
the stricter policy. These changes require Translator++ 8.11.9.

Each AI request receives the actual fixed CP932 byte cap for each row. Growable
ASB and table strings have no original-size cap. The all-ASCII storage capacity
is shown separately from character/line caps; stored controls and newlines count
before expansion. Duplicate source rows use their strictest occurrence limit.
When a shared chat AI reply violates limits, the previous reply and precise
row/line errors go back in corrective turns, using the translator's **Number of
retry** setting. Exhausted or invalid results do not replace existing drafts.
Selected/merged/line commands use complete rows while parser AI constraints are
enabled. Disable these AI checks in the dialog if needed; export's binary-format
validation continues to apply.

CRC32 checking is optional and off by default. Enabling it with a blank expected
value uses the imported disc's checksum. New Project > Advanced also accepts a
check flag and expected CRC32. At Export/Inject, missing settings or an unset
expected CRC skip the optional check, even if an enabled flag was saved. Older
projects open normally and gain disabled CRC settings automatically; no project
recreation, disc rescan or retranslation is required. A mismatch against a
configured CRC blocks Export/Inject and reports both
values. Inject's **Skip source CRC32 check this time** is a one-operation override;
it resets on reopening Inject and does not turn off the saved policy. Source
SHA-256 identity and supported-format checks remain active. The export report
records CRC verification or bypass. The inspected source's CRC32 is `8C6E35CD`;
other inputs must use their own recorded checksum.

Parser authors and agents: [reusable guidance/limits/CRC API](../../docs/parser-translation-guidance.md).
External agents can read limits with the registered `translation.constraints.read`
tool without loading all game documentation.

## Requirements

- Python **3.10+**. New Project > Advanced can select `python.exe`; otherwise
  the add-on uses `python` from PATH. Core extraction/rebuilding uses only the
  Python standard library.
- **Pillow** in that interpreter for GIM/PNG import and edited image injection.
- Translator++ **Image Translator** for the image editor, and an enabled OCR
  engine when image recognition is selected.

## Text and image limits

See [Control codes and byte budgets](CONTROL_CODES.md) for the verified command
catalog, name IDs, context-dependent replacements and before-expansion counting.

- Message-box text may reflow within its line and width limits; other text keeps
  its source line structure. Preserve inline `\hNN` codes (two decimal digits)
  and printf placeholders. Output must encode as CP932.
  Typographic em dashes (`—`) become ASCII hyphens (`-`) during export; saved
  drafts are preserved. CP932's horizontal bar ends in a backslash byte, so
  `―hey` can accidentally trigger a name control code. Export rejects similar
  trail-byte collisions before recognized substitution/newline prefixes instead
  of emitting broken text. Control-code numeric arguments must also be preserved.
- TSID messages and CSV cells can grow. CSV quoting and original line endings
  are preserved; facial-animation CSV developer labels are excluded.
- ASB dialogue is replaced in place when it fits. Longer strings can be
  appended only when every reference is a recognised static operand. Ambiguous
  references have a fixed CP932 byte budget in their row parameters. Export
  rejects overlong edits and reports their contexts; it never truncates them.
- Repeated source strings share a grid row with all their occurrence contexts
  and speaker metadata. Use Context translation to override individual uses;
  these overrides are exported independently.
- Identical archive copies are grouped for editing and updated together.
- Single-frame PSP GIM formats RGB565, RGBA5551, RGBA4444, RGBA8888, INDEX4
  and INDEX8 are supported in normal or swizzled order. Original palettes and
  layouts stay intact; changed pixels in indexed textures use the nearest
  original RGBA colour. Unchanged pixels remain exact. Unsupported variants
  are listed in `project.options.init.sourceManifest.imageErrors`.
- Gallery CG/portrait collections are excluded; interface texture sheets are
  included. Some sheets contain decorative art without text.
- Optional half-width alphabet support renders single-byte ASCII at 8×16 in
  scenario dialogue. Japanese and full-width Latin retain their original size.
  See the setup below. The opening scene has been verified in PPSSPP; PSP
  hardware and later gameplay have not been tested.
- The researched PIDX build hashes have an unknown algorithm and are retained.
  The supplied research reports that its patched ISO boots with these values.

### What a fixed byte budget means

An ASB row's fixed budget is the **original Japanese string's CP932 byte
length**, excluding its terminating NUL. It does not measure the width of the
message window or the number of visible characters. Ordinary ASCII letters,
spaces and punctuation usually cost one byte; Japanese characters usually cost
two. Newline characters and stored control codes also consume bytes.

For example, `scespa01.asb`, context `string/718` (grid row 15 in the observed
project), has a 57-byte source string across two lines. An 83-byte translation
exceeds that slot by 26 bytes. This unclassified occurrence keeps both source lines and the control codes when
shortening the translation.

This restriction reflects the current parser's ability to relocate that
particular string safely. Many ASB strings can grow through append-and-patch;
when the parser cannot verify every reference, it keeps the original slot and
rejects an overflow. It is not a general PSP text-length limit, and does not
prove that a more complete bytecode parser could never relocate the string.
Fitting the encoded byte budget and fitting the text visually in the game's
message window are separate checks; the latter needs in-game testing.

## Half-width alphabet

For the investigation, exact patch rationale, achieved results and automated
emulator testing, see [Half-width text and PPSSPP testing](plan/half-width-and-ppsspp.md).

Choose **Tools → Tokimeki Memorial 4 (PSP) → Configure half-width alphabet**.
Select an **unmodified decrypted EBOOT.BIN** from your own original game and
click Enable. New Project → Advanced accepts the same optional executable.

To obtain it with PPSSPP, enable **Settings → Tools → Developer tools → Dump
decrypted EBOOT.BIN on game boot**, then boot the original game. Select the
resulting `PSP/SYSTEM/DUMP/<game-id>_EBOOT.BIN` in that emulator's memory-stick
directory. The add-on checks the supported executable fingerprint and caches
the original executable with the project. Save the project; subsequent Export,
ZIP and Inject operations apply the patch automatically. Project Update carries
the cached executable into the new cache. Disable the option in the same dialog
to export with the original executable again.

Use ordinary `ABC abc 123!?` characters in translations. Each ASCII character
uses one CP932 byte instead of the two bytes used by full-width `ＡＢＣ`.
This permits roughly twice as many Latin characters in a fixed byte slot;
newlines, Japanese punctuation and control codes still consume their own bytes.
The patch does not enlarge a fixed slot or remove the exporter's safety checks.

The game already contains Latin glyphs and an ASCII lookup table. The patch
enables single-byte characters in the scenario loop, halves their cursor advance,
and renders them at half width using the existing atlas. It changes 13 guarded
MIPS instructions and leaves Japanese glyphs intact. It uses fixed 8-pixel
spacing, not a variable-width font or a two-letter glyph encoding. Extended
Latin/accented characters and half-width kana are outside this feature.

The exported ISO contains an unsigned decrypted executable. **PPSSPP is tested;
PSP hardware would require compatible custom firmware and remains untested.**
The encrypted ISO EBOOT, zero-filled BOOT.BIN, modified executables and unknown
versions are rejected. No executable or copyrighted font asset is distributed
with the add-on, and no user's ROM/emulator directory is built into its code.

## Implementation

`tm4Psp.js` contains the New Project wizard, AddonUtils integration, image/OCR
support and ISO export. `tm4Psp.module.js` is the portable CommonJS/worker API.
`python/tm4_bridge.py` handles import, strict translation validation and rebuilding.
Text descriptors use stable content hashes and per-occurrence contexts; exported
archives update the internal main index and global index together. Rebuilding
re-extracts and compares every modified member before presenting the output ISO.
No-op exports copy the source ISO exactly when the font patch is disabled.
With it enabled, even a text-free export replaces and verifies EBOOT.BIN.

The container codecs in `python/{pidx,lzss3,rebuild,iso9660,tsid2}.py` come from
the user's supplied `tm4_translation/tools` research, bundled so the add-on
does not depend on that folder. GIM block and pixel order were cross-checked
against [arc_unpacker's decoder](https://github.com/vn-tools/arc_unpacker/blob/master/src/dec/playstation/gim_image_decoder.cc).

## Verification

```powershell
node --test www/addons/tm4Psp/test/tm4Psp.module.test.js
node --test www/addons/tm4Psp/test/tm4Psp.integration.test.js
python -B www/addons/tm4Psp/test/test_formats.py
python -B www/addons/tm4Psp/test/test_font.py
```

Tests use synthetic binary fixtures, including duplicate contexts/speakers,
missing translations, ASB append/reference patching, fixed budgets, TSID trailing
data, CSV quoting/newlines, invalid control codes/encoding, and indexed/swizzled
GIM no-op and changed-pixel round trips. No game fixtures are distributed.
Relocation tests use temporary paths and synthetic fingerprints, including
explicit file/folder selection, renamed ISOs, wrong-disc rejection and the
Inject handoff to the add-on. No user's ROM directory is built into the code.

The supplied disc was also imported in the live application. An ISO with TSID,
ASB, CSV and GIM edits was rebuilt, and all changed members were verified after
extraction. See `plan/README.md` for the observed inventory and validation notes.
