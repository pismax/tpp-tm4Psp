# Tokimeki Memorial 4: half-width text and reproducible PPSSPP tests

Recorded 2026-11-03. Add-on 1.1.0; tested emulator PPSSPP 1.20.4 on Windows,
Direct3D 11. The running game reports NPJH50127, version 1.01. Addresses below
belong to the verified executable; they are not a universal PSP font patch.

## Achievements and scope

The add-on imports dialogue, message tables, CSV cells and interface textures
from the original Japanese ISO, then builds a separate translated ISO. The
observed import contained 299 text resources, 59,956 text occurrences grouped
into 58,361 source rows, and 1,009 editable images. Speaker extraction recovered
27,798 named rows. Local OCR found 661 boxes in 174 images. Dynamic or
unresolved speakers are left blank rather than guessed.

Moving the source ISO is supported: Inject accepts a user-selected ISO or folder,
checks it against the imported disc's SHA-256, and remembers the verified path.
The add-on does not contain this user's ROM directory or emulator directory.

Half-width support now renders ordinary ASCII at 8×16 in scenario dialogue,
with 8-pixel advance. Japanese and full-width Latin retain their original
16-pixel width. Enable it through **Tools → Tokimeki Memorial 4 (PSP) →
Configure half-width alphabet**, or select the optional decrypted EBOOT during
New Project. The original executable is staged with the project; saved settings
survive reopening and the Update hook carries the staged file forward.

We verified a mixed-script comparison from a fresh ISO boot, then exported the
user's opening translation through the normal Inject/export hooks and booted
that ISO. A live breakpoint observed `W` drawn at X=112, with the next cursor
at X=120. Original translation data, contexts and row parameters had the same
checksum before and after enabling the option.

This is fixed half-width spacing using the game's existing glyphs. The optional
bold atlas treatment introduced in 1.2.2 is described below. It does not
implement a variable-width font, accented Latin, half-width kana, or two-letter
glyph encoding. It does not enlarge fixed ASB byte slots. Physical PSP hardware,
custom-firmware compatibility and the rest of the game's playthrough remain
untested. The successful test export contained the opening translation only;
it does not establish that all current drafts pass validation or fit on screen.

## The two separate problems

### Storage capacity is measured in bytes

A fixed ASB budget is the original string's CP932 byte length, excluding NUL.
It is not the width of the message box. Japanese and full-width Latin usually
take two bytes; ordinary ASCII letters, digits, spaces and punctuation take one.
Newlines and stored control codes consume bytes too.

The observed `scespa01.asb`, context `string/718`, has a 57-byte fixed slot. An
83-byte draft exceeds it by 26 bytes. Halving glyph width cannot make those 83
bytes fit. Using ASCII instead of full-width Latin makes roughly twice as many
Latin characters possible within the same slot, with deductions for other bytes.

Some longer ASB strings are safely appended and their static references patched.
When the exporter cannot account for every reference, `canGrow: false` retains
the original slot. This is a conservative parser limitation, not proof that
the PSP hardware cannot display a longer string. The exporter rejects overflow,
line-count changes and damaged control codes; it never truncates drafts.

### Scenario ASCII was deliberately skipped

The font atlas already contains usable Latin glyphs, and a shared renderer has
an ASCII-to-full-width-SJIS lookup table. However, the scenario path does not
send an entire string directly to that renderer. It prepares character records,
draws one character at a time, and maintains a separate cursor position.

The scenario loop rejected a record whose high byte was zero. That discarded
single-byte ASCII before drawing. It also advanced every accepted character by
16 pixels. A generic font-width patch alone therefore left scenario ASCII
invisible; the scenario acceptance and cursor logic also needed changes.

## How we found the working solution

1. Read the local format/font research, extracted a decrypted executable with
   PPSSPP, and made an isolated emulator copy. All ROM patches went to new ISOs.
2. Compared ASCII, full-width Latin and Japanese in the same three-line message.
   This separated a missing-glyph problem from a byte-budget or scene problem.
3. Found the loaded font object/texture and followed calls to the shared renderer.
   System text and scenario text use different drawing callbacks.
4. Patched the shared ASCII metrics in RAM. Japanese remained intact, but ASCII
   still vanished in the scenario. This ruled out a metrics-only fix.
5. Broke at the shared renderer, inspected arguments and return addresses, then
   followed the caller back to `0887102c`. It passed a stack buffer containing
   one CP932 character, rather than the original ASB string.
6. Disassembled the scenario loop and found its high-byte check and independent
   `+16` cursor update. Enabled ASCII and changed its advance to 8 pixels.
7. Verified mixed-script output in RAM, converted the change into guarded ELF
   word patches, rebuilt the ISO, and repeated from a cold boot. RAM-only success
   was treated as an experiment until the new ISO passed.
8. Integrated the verified patch with staging, configuration, export verification
   and regression tests. The user's screenshot independently confirmed the
   mixed-script result.

The controlled comparison was:

```text
ABC abc!
ＡＢＣ abc!
日本語 ABC xyz
```

Before the scenario fix only the full-width/Japanese parts appeared. After the
fix all three lines displayed, with ASCII half as wide and height unchanged.

Approaches that did not become the solution:

| Experiment | Finding |
|---|---|
| Full-width English | Displays, but costs two bytes per Latin character. |
| Change only global/generic metrics | Does not bypass the scenario's ASCII rejection. |
| Replace an ASB string only in live RAM | Existing per-character buffers can keep displaying the old message; reload the scene or rebuild/cold-boot. |
| Unused-kanji glyph bank | An experimental atlas decoder and candidate-slot scan worked, but replacing glyphs was unnecessary once the existing ASCII route was understood. |
| Two-letter glyph combinations | Not implemented or required by the successful patch. |

## Exact executable patch

[`python/tm4_font.py`](../python/tm4_font.py) is the authoritative patch profile.
It requires ELF input and an exact source fingerprint, then checks all original
words before changing anything. Game executables and font assets are not bundled.

| Property | Value |
|---|---|
| Profile | `tm4-ascii-8x16-v1` |
| Decrypted executable size | 4,631,376 bytes |
| Source SHA-256 | `7068e4cb62a1eb2761d207564182fddb72dcb7703f1ffc2d292b5b88a4f5886d` |
| Patched SHA-256 | `f249b7bd0c4ba9b7a7e11053dac1653dc69329726fdf2980ed4f87b7314bb8c2` |
| Changed words | 13, with no change to ELF length |

The source ISO's EBOOT is encrypted; BOOT.BIN is a zero-filled dummy. Enable
PPSSPP's **Dump decrypted EBOOT.BIN on game boot** developer option, boot the
original game, and select `PSP/SYSTEM/DUMP/<game-id>_EBOOT.BIN` from its memory
stick directory. Reject encrypted, dummy, modified and unknown executables.
The exported executable is unsigned: PPSSPP is tested; stock PSP support is
not claimed. A PSP would need compatible custom firmware and further testing.

The patch changes three cooperating paths:

| Guest address | Purpose |
|---|---|
| `08834ff0`–`08834ff8` | Shared ASCII advance returns glyph size / 2. Double-byte advance is retained. A PC-relative branch reuses the existing return path. |
| `08835d9c` | ASCII quad width uses the existing 0.5 constant instead of 0.75. Height is unchanged. |
| `088710f8`–`08871138` | Scenario accepts ASCII, emits its byte followed by NUL, and advances `16 - (isAscii << 3)`. Double-byte text remains 16 pixels; unsupported half-kana remain skipped. |

Guest addresses refer to the loaded image based at `08804000`. For these code
sites, ELF file offset is `guest - 08804000 + c0`. **File words and runtime words
can differ after relocation.** In particular, the patched file LWC1 word is
`c4405480`; it becomes `c4409480` in the tested runtime. Copying the runtime
immediate directly into the ELF would load the wrong constant. A new absolute
jump at an unrelocated site would likewise need relocation support; the patch
uses an existing PC-relative return branch instead.

Newlines are handled outside the modified scenario block. The font atlas is
unchanged. Project settings reference `font/tm4-decrypted-eboot.bin` relative to
the staging data directory, so a moved emulator dump is not needed for export.
Every build revalidates that staged executable and reads back the ISO's EBOOT
to compare its bytes with the expected patch. A font-only export still replaces
EBOOT; with the option disabled and no edits, export remains a bit-exact copy.

## Follow-up: em-dash control-code collision (1.1.1)

The subsequent [control-code reference](../CONTROL_CODES.md) documents the
complete inspected dispatch, decimal name selectors and before-expansion budget
rules. Version 1.1.2 also protects numeric arguments and extends collision checks
to the other confirmed byte-oriented substitution prefixes.

The user subsequently spotted `＄川さん` inside the English wake-up line where
`—hey` belonged. This was an export-encoding regression, not a deliberate name
placeholder in the translation or a missing Japanese glyph. The original draft
remains unchanged in the project.

The earlier encoder accepted Unicode em dash by converting it to CP932's
horizontal bar (`―`). That character encodes as `81 5C`. Followed by `hey`,
the byte sequence becomes:

```text
81 5C 68 65 79
   \  h  e  y
```

The game's byte-oriented escape handling interprets `\h` even though the
backslash byte is the trail of a Japanese-encoded character. The displayed
Japanese-name insertion matches that collision. The dollar glyph is also
explained by CP932: an orphan `81` before `星` (`90 AF`) produces `81 90`
(`＄`) followed by `AF` (half-width `ｯ`, skipped by the scenario), then the
remaining `川さん`. This reproduces the visible fragment without any dollar
sign in the stored translation.

Version 1.1.1 exports em dashes as ASCII hyphens (`-`), so the phrase becomes
`already-hey`. It also rejects translated encodable characters whose trail
byte is `5C` directly before `h`, `k` or `n`, preventing unintended game escape
prefixes. Authored control codes such as `\h01` and `\k26` still have to match
the source. Ordinary Japanese horizontal bars remain unchanged when they do
not create this collision. The conversion changes output bytes only; it does
not edit saved drafts.

The regression fixture covers the user's complete three-line opening draft,
the dangerous encoded sequence, the dollar/kana byte pairing, preserved genuine
name codes, and rejection of other trail-byte collisions. The 13-word font patch
and its executable fingerprint are unchanged. This illustrates why an 8-pixel
cursor probe must be paired with checking the actual rendered sentence: correct
metrics alone did not catch a preprocessing substitution.

Cold-boot verification of the corrected `translated-2.iso` read all 60 processed
scenario character records, not just the first ASCII glyph. They matched the
expected three-line draft exactly after export normalization, including
`Wake up already-hey, I'm talking to you!`; the Japanese-name substitution was
absent. Evidence: `artifacts/tm4-font-lab/dash-fix-scene.json`. All 11 add-on
tests and five automation-helper tests passed after this correction.

## Additional font-atlas findings

### Optional bold Latin (1.2.2, 2026-11-06)

The existing Latin shapes become thin when the 16-pixel atlas cell is drawn at
8 pixels wide. The optional `halfWidthFont.weight: "bold"` setting treats this
separately from the verified executable/spacing patch; missing settings mean
`"regular"` for old projects. Configure it in the half-width alphabet dialog.
This update does not need a newer Translator++.

`tm4_font.bold_atlas` checks the original executable and the 445,440-byte atlas
SHA-256 `fbae09c4c7626d4baaa0009df9fa9e1eb9b83f8a562112a6764edd5fa1311124`.
It reads the executable's ASCII mapping and 6,960-entry glyph lookup, then
changes only A–Z, a–z and 0–9 (62 glyphs). Each output intensity is the maximum
of source x−1, x and x+1 on the same row. This adds approximately one displayed
pixel of stroke weight at half width without thickening vertically or changing
any metrics. The paired glyph's bits are masked and retained exactly. Original
inputs are always used, so repeated exports do not accumulate dilation.

Full-width Latin letters/digits share these same glyphs and receive the same
treatment. Japanese letters and punctuation are untouched. This is a heavier
version of the same narrow design, not a variable-width font or a new font face.
The existing 13 executable words and patched executable SHA-256 are unchanged.
Atlas discovery is opt-in during bold export, including `.fnt` resources without
adding font binaries to translation rows. All changed archives/indexes are
rebuilt and the atlas is re-extracted and compared byte-for-byte before delivery.
The export report records the font weight, atlas hashes and destination paths.

Synthetic tests check both glyph planes, all 62 characters, unchanged neighbouring
glyphs, horizontal-only expansion, exact atlas/executable guards, invalid weight
rejection, staged-executable reuse and saved weight preservation during Update.

Verification on 2026-11-06: a separate `Tokimeki Memorial 4 (Japan).bold.iso`
was built from the verified original with the same corrected opening translation.
Its atlas SHA-256 is `6a76fd4607b26419e34b8bb738441247eee93907e9c26155c38771d731ff158a`;
the rebuilt archive's `tokimeki/00025_tm4_font16.fnt` matched the expected bytes.
A visible isolated PPSSPP 1.20.4 cold boot reached the opening scene, all 13 code
words were checked, and `W` advanced from X=112 to X=120. Native window capture
confirmed the thicker wake-up text. An initial hidden run missed the timed menu
route; the visible run completed with the helper's title-menu retry. Private
evidence is in `artifacts/tm4-bold-ppsspp/bold-scene.json` and
`artifacts/tm4-font-lab/bold-opening-ppsspp.png`. The current project's Bold
setting was saved with unchanged translation cells, contexts, parameters and
tags, and an earlier project backup retained. This remains an opening-scene
test ISO, not a full project translation or full-game/hardware validation.

The experimental decoder recovered paired glyph planes: each 16×16 physical
cell stores two 2-bpp glyphs within its 4-bpp pixels. Pages use a linear
384×384 layout, 24 cells across. For glyph `i` and x/y inside that glyph:

```text
page = i // 1152
cell = (i % 1152) // 2
px = (cell % 24) * 16 + x
py = (cell // 24) * 16 + y
byteOffset = page * 0x12000 + py * 192 + px // 2
shift = (px % 2) * 4 + (i % 2) * 2
pixel = (font[byteOffset] >> shift) & 3
```

The 6,960-entry lookup at `08b197c0` contains little-endian u16 SJIS byte
pairs, in a nonstandard ordering. Confusing that order, the paired planes, or
linear storage with swizzling produced misleading previews. The loaded font
object's +0x20 field points to a texture object, not directly to a page array.
These findings supported tracing but no atlas edit was needed for the solution.

## Repeatable Windows test setup

Reusable tools live in the repository, rather than the ignored experiment folder:

- [`tools/test-tm4-font.ps1`](../tools/test-tm4-font.ps1): prepare/launch
  an isolated PPSSPP copy, optionally navigate and verify, and save evidence.
- [`tools/tm4-ppsspp.py`](../tools/tm4-ppsspp.py): local WebSocket client,
  navigation, runtime verification, button presses, memory reads and disassembly.
- [`tools/test_tm4_ppsspp.py`](../tools/test_tm4_ppsspp.py): synthetic
  tests for setup isolation, RPC handling, navigation and probe cleanup.

Requirements: Windows PowerShell with `Get-NetTCPConnection`, Python 3.10+,
PPSSPP's Windows x64 directory containing `PPSSPPWindows64.exe` and `assets/`.
The debugger client was tested with `websockets` 10.3. Setup uses only the Python
standard library; remote commands need:

```powershell
python -m pip install websockets==10.3
```

From this add-on's folder, substitute your own paths:

```powershell
$iso = 'D:\Games\TM4.translated.iso'
$emulator = 'D:\Emulators\PPSSPP'

.\tools\test-tm4-font.ps1 -Iso $iso -PpssppDir $emulator `
  -CopySaves -Visible -Navigate -Verify
```

The ISO must contain an ASCII message in the opening scene for `-Verify` to
pass. Use the comparison above or the user's translated wake-up line, preserving
the original line count. A Japanese-only original ISO is useful as a visual
baseline but cannot pass the ASCII probe.

The launcher copies the emulator/assets into `artifacts/tm4-ppsspp/emulator`.
`-CopySaves` optionally copies SAVEDATA once; it does not overwrite subsequent
lab progress or write to the original emulator. The main emulator config and
original ISO are not changed. Copies are recognized by `.tpp-tm4-lab.json`;
preparation refuses an unrelated nonempty destination.

On subsequent runs omit `-PpssppDir` and `-CopySaves`. Use `-LabRoot`, `-Port`,
or `-Python` for a different isolated directory, debugger port or interpreter.
`-Verify` implies navigation from boot. Omit `-Visible` for a hidden test window;
use `-Visible` for visual inspection. The launcher stops only the previous PID
whose executable matches its lab copy, checks debugger-port ownership, and
leaves the completed game running for inspection. Close that lab before
rebuilding an ISO it has open. It does not close the user's main emulator.

The lab configuration includes:

```ini
[General]
RemoteDebuggerOnStartup = True
RemoteDebuggerLocal = True
RemoteISOPort = 20002
PauseOnLostFocus = False
PauseWhenMinimized = False

[Graphics]
GraphicsBackend = 2 (DIRECT3D11)
InternalResolution = 1
```

PPSSPP can start its debugger before the game ID is available. The client waits
up to 60 seconds for the supported game, separately from its 10-second RPC
timeout. Do not treat an initial empty `game.status.game` as a wrong ISO.
The launcher applies its 15-second boot grace before sending debugger requests,
to avoid probing during CPU initialization; increase `-BootWait` on slower hosts.
Navigation also tolerates a brief startup stepping state by waiting for it to
clear naturally, without resuming a manually paused game.

## Navigation to the first scenario

The user supplied this route from a fresh boot:

1. Wait about 15 seconds.
2. Circle: acknowledge the memory notification.
3. Start: skip the first video.
4. Start: skip the second video.
5. Circle: enter/restore the title menu if the attract video resumes.
6. Circle: select New Game, initially highlighted.
7. Start: skip the video after New Game.
8. Stop at the black wake-up scene and inspect the message. The black background
   is intentional; it does not by itself indicate a crash.

Timing is affected by fades, video playback and host speed. The automation holds
each button for 10 emulated frames, then waits between transitions. It reserves
a breakpoint at `08871160`, the scenario character loop, and stops sending input
as soon as that loop runs. A bounded extra Circle/Start retry handles reaching
the title menu later than expected. This avoids blindly pressing Start after
the opening message has appeared. Use `navigate --wait-scale 2` for slower hosts.

Fresh first-run dialogs may differ without existing save data. If navigation
times out, inspect the visible window and use individual button commands; do
not interpret a navigation timeout as a font-patch failure.

## Runtime proof and saved evidence

The endpoint is `ws://127.0.0.1:20002/debugger`, with WebSocket subprotocol
`debugger.ppsspp.org` and origin `http://127.0.0.1:20002`. Requests and replies
are JSON. The helper sends requests sequentially and filters asynchronous log
and stepping notifications until the matching event arrives.

`verify` checks all 13 patched runtime instructions using `memory.disasm`'s
`encoding` field, accounting for the LWC1 relocation. Raw `memory.read` is not
sufficient for code verification under JIT: during testing, RAM at `08871104`
contained `6816fef2`, while disassembly correctly resolved the patched branch
`11a00012`. The debugger's disassembly uses `Memory::Read_Instruction`, as shown
in the [upstream implementation](https://github.com/hrydgard/ppsspp/blob/master/Core/Debugger/WebSocket/DisasmSubscriber.cpp).
Use raw reads for data buffers, and decoded encodings for these code checks.
It then installs a conditional breakpoint at `08871144`:

```text
t4 >= 0x20 && t4 < 0x7f
```

At that point the single-byte draw buffer and cursor update are ready:

- `t4`: the scenario character code, such as `0x57` for W.
- `a0`: stack buffer for the shared renderer; its first two bytes must be `57 00`.
- `a1`: the current drawing X position.
- `s1`: the next X position; `s1 - a1` must be 8.

The third terminator byte is written in the following JAL delay slot. The probe
checks only the first two bytes, which are already valid at this breakpoint.
The helper removes its probe in `finally` and resumes a CPU stop at that probe.
It refuses to begin when the CPU is already paused and does not resume an
unrelated breakpoint. Reserve these two addresses for the helper in the isolated
instance; do not run overlapping debugger probes against it.

A successful launcher run writes `artifacts/tm4-ppsspp/last-test.json`, including
ISO path and SHA-256, emulator path, port, UTC time, route, patch profile, all
13 word checks and observed character/cursor values. Expected probe result:

```json
{
  "profile": "tm4-ascii-8x16-v1",
  "patchWordsVerified": 13,
  "character": "W",
  "bufferHex": "5700",
  "drawX": 112,
  "nextX": 120,
  "advance": 8
}
```

This proves code/serialization/advance, not pixel appearance, wrapping or every
glyph. Also visually inspect mixed English/Japanese, punctuation, line breaks,
quotes, text height and right-edge fit. The user screenshot supplied the visual
confirmation for the controlled comparison. Tests should be repeated on later
scenes, speaker names and menus before claiming complete-game compatibility.

## Individual debugger commands

These attach to an already running isolated emulator. Global options precede
the subcommand. They do not require Translator++ to remain open.

```powershell
python -B tools/tm4-ppsspp.py info
python -B tools/tm4-ppsspp.py press circle --duration 10
python -B tools/tm4-ppsspp.py press start --duration 10
python -B tools/tm4-ppsspp.py --output artifacts/tm4-ppsspp/probe.json verify --expected-character W
python -B tools/tm4-ppsspp.py --output artifacts/tm4-ppsspp/disasm.json disasm 0x088710f4 --count 30
python -B tools/tm4-ppsspp.py read 0x088710f4 0x60 artifacts/tm4-ppsspp/loop.bin
python -B tools/tm4-ppsspp.py --port 20003 --trace navigate --boot-wait 15 --wait-scale 2 --verify
```

`--trace` prints RPC event names to stderr. `--timeout` adjusts one request's
deadline; `--load-timeout` adjusts the game-load wait. Errors write JSON and
return a nonzero exit code; they must not be counted as a pass.

For custom experiments, reuse `Debugger.rpc()` and `read()` from the Python
helper. Events used successfully in this investigation include `version`,
`game.status`, `cpu.status`, `cpu.getAllRegs`, `cpu.breakpoint.add/remove`,
`memory.read`, `memory.disasm`, and `input.buttons.press`. Earlier RAM-only
experiments also used `memory.write_u32`; the reusable verifier does not patch
RAM, so it can establish that the exported ISO contains the fix.

Primary protocol reference: PPSSPP's
[WebSocket breakpoint implementation](https://github.com/hrydgard/ppsspp/blob/master/Core/Debugger/WebSocket/BreakpointSubscriber.cpp).
That is current upstream source; local observations against 1.20.4 take priority
when its behavior differs. This guide does not depend on a hit-notification event
from newer builds; it polls `cpu.status` for the expected PC instead.

## Pitfalls and recovery

| Symptom | Response |
|---|---|
| Port is occupied | Choose `-Port` with a separate lab, or close the matching lab. Do not attach to an arbitrary process. |
| Connection refused | Verify the isolated process and its configured port. A server flag alone did not enable the debugger in the tested build; use the INI settings. |
| Initial game object is empty | Wait for loading; the debugger can become ready first. |
| RPC stops replying | Restart only the isolated copy. Breakpoint-inventory experiments stalled this build; the runner avoids that call and uses the tested log-enabled probe route. |
| GPU screenshot request fails or hangs | Do not use `gpu.buffer.screenshot` in this test runner. It failed with "Could not download output" and sometimes stalled the debugger. Use a normal window capture for visual checks. |
| Captured window shows stale/underlying pixels | Activate the intended PPSSPP window and capture again. Avoid relying on a minimized/hidden-window screenshot. |
| Game appears frozen | Check both `cpu.status.stepping` and `paused`; remove your own breakpoint and resume. They are different states. |
| No ASCII draw observed | Reach the correct scene with ASCII injected; a Japanese-only message cannot satisfy the condition. |
| Runtime words differ | Wrong/unpatched ISO, wrong executable version, or a RAM experiment changed code. Cold-boot the intended ISO. |
| Raw RAM word resembles `68xxxxxx` but disassembly is correct | A JIT marker can replace the raw instruction. Compare decoded `encoding`, not the raw RAM word. |
| ISO cannot be overwritten | Close the isolated emulator holding it, or choose a new output file. |
| RAM edits do not change current text | The scenario caches per-character data. Reload the scene; final validation must cold-boot the rebuilt ISO. |

Save states can accelerate later exploration, but are not the final patch test:
they may restore the old executable, text buffers or RAM-only modifications.
Use a fresh process/ISO boot to validate a permanent export. If a debugger
connection is lost while paused, inspect/resume the private instance or restart
it rather than assuming cleanup succeeded.

## Regression commands and evidence locations

The reusable launcher completed a fresh-process navigation and verification on
2026-11-03. Its successful route was Circle, Start, Start, Circle, Circle,
Start, Circle, Start (the bounded title-menu retry was needed). It verified
all 13 decoded patch words and `W`, buffer `5700`, X=112→120. The tested ISO
SHA-256 was `bee4fde995beec1422acf507679220a7dbc11679a98ad70d2a35f7ccc97bef9f`.
The evidence file is `artifacts/tm4-ppsspp/last-test.json`. All 11 add-on tests
and all four new automation-helper tests passed after the runner changes.

```powershell
node --test www/addons/tm4Psp/test/tm4Psp.module.test.js www/addons/tm4Psp/test/tm4Psp.integration.test.js
python -B www/addons/tm4Psp/test/test_formats.py
python -B www/addons/tm4Psp/test/test_font.py
python -B tools/test_tm4_ppsspp.py
```

Synthetic tests distribute no game binaries. They exercise binary formats,
ASCII/Japanese MIPS behavior including branch delay slots, executable guards,
font-only and disabled exports, UI settings and isolated automation helpers.

Original investigation artifacts are ignored under `artifacts/tm4-font-lab`:
`baseline.elf`, disassembly dumps, comparison ISO, `project-font-check.json`,
`export-check.json`, `verified-scene.json`, and `verified-export/` with its ISO
and export report. They contain private game/project material and are not part
of the add-on distribution. New reproducible runs use `artifacts/tm4-ppsspp`.
The stable documentation, patch profile and tools are tracked in the repository;
following this guide does not require those original experiment artifacts.
