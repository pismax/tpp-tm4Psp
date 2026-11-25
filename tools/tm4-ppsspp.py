#!/usr/bin/env python3
"""Reproducible TM4 PPSSPP lab setup and local debugger automation.

Python 3.10+. Debug commands require websockets; prepare uses the stdlib only.
See plan/half-width-and-ppsspp.md.
"""
import argparse
import asyncio
import base64
import collections
import configparser
import json
import pathlib
import shutil
import sys
import time

GAME_IDS = {'NPJH50127', 'ULJM05541'}
SCENE_ADDRESS = 0x08871160
DRAW_ADDRESS = 0x08871144
MARKER = '.tpp-tm4-lab.json'


def prepare(source, destination, port, copy_saves=False):
    source, destination = pathlib.Path(source).resolve(), pathlib.Path(destination).resolve()
    if source == destination or destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError('Choose a separate lab directory outside the source emulator tree.')
    exe = source / 'PPSSPPWindows64.exe'
    if not exe.is_file() or not (source / 'assets').is_dir():
        raise ValueError('The source directory must contain PPSSPPWindows64.exe and assets/.')
    if destination.exists() and any(destination.iterdir()) and not (destination / MARKER).is_file():
        raise ValueError('The destination is not an owned TM4 lab. Choose a new empty directory.')
    destination.mkdir(parents=True, exist_ok=True)
    # Record ownership before copying, so a failed copy can be retried safely.
    (destination / MARKER).write_text(json.dumps({'source': str(source), 'port': port}, indent=2), encoding='utf8')
    shutil.copy2(exe, destination / exe.name)
    for dll in source.glob('*.dll'): shutil.copy2(dll, destination / dll.name)
    shutil.copytree(source / 'assets', destination / 'assets', dirs_exist_ok=True)
    system = destination / 'memstick/PSP/SYSTEM'
    system.mkdir(parents=True, exist_ok=True)
    (destination / 'portable.txt').write_text('', encoding='utf8')
    ini = configparser.RawConfigParser(strict=False)
    ini.optionxform = str
    # Retain lab settings on subsequent preparation. Never write source config.
    own_ini = system / 'ppsspp.ini'
    ini.read(own_ini if own_ini.exists() else source / 'memstick/PSP/SYSTEM/ppsspp.ini', encoding='utf-8-sig')
    settings = {'General': {'RemoteDebuggerOnStartup': 'True', 'RemoteDebuggerLocal': 'True',
                           'RemoteISOPort': str(port), 'PauseOnLostFocus': 'False',
                           'PauseWhenMinimized': 'False', 'DumpFileTypes': '0',
                           'AutoLoadSaveState': '0', 'EnableCheats': 'False',
                           'WindowX': '100', 'WindowY': '100', 'WindowWidth': '1000', 'WindowHeight': '650'},
                'Graphics': {'InternalResolution': '1', 'GraphicsBackend': '2 (DIRECT3D11)'}}
    for section, pairs in settings.items():
        if not ini.has_section(section): ini.add_section(section)
        for key, value in pairs.items(): ini.set(section, key, value)
    with own_ini.open('w', encoding='utf8') as stream: ini.write(stream, space_around_delimiters=True)
    saves = source / 'memstick/PSP/SAVEDATA'
    if copy_saves and saves.is_dir():
        target = destination / 'memstick/PSP/SAVEDATA'
        # First-copy only: do not overwrite progress subsequently made in the lab.
        if not target.exists(): shutil.copytree(saves, target)
    return {'executable': str(destination / exe.name), 'memstick': str(destination / 'memstick'), 'port': port}


class Debugger:
    def __init__(self, port=20002, timeout=10, load_timeout=60, trace=False):
        self.port, self.timeout, self.load_timeout = port, timeout, load_timeout
        self.trace = trace
        self.logs = collections.deque(maxlen=100)

    async def __aenter__(self):
        try:
            import websockets
        except ImportError as ex:
            raise RuntimeError('Install the debugger dependency: python -m pip install websockets==10.3') from ex
        self.ws = await websockets.connect(f'ws://127.0.0.1:{self.port}/debugger',
            subprotocols=['debugger.ppsspp.org'], origin=f'http://127.0.0.1:{self.port}',
            max_size=None, open_timeout=self.timeout, close_timeout=2)
        return self

    async def __aexit__(self, *_): await self.ws.close()

    async def rpc(self, event, **params):
        if self.trace: print('RPC ' + event, file=sys.stderr, flush=True)
        await self.ws.send(json.dumps({'event': event, **params}))
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0: raise TimeoutError(f'No response to {event}')
            try:
                reply = json.loads(await asyncio.wait_for(self.ws.recv(), remaining))
            except asyncio.TimeoutError as ex:
                raise TimeoutError(f'No response to {event}; restart the isolated emulator if its debugger has stalled') from ex
            if reply.get('event') == 'log': self.logs.append(reply)
            if reply.get('event') == 'error': raise RuntimeError(reply)
            if reply.get('event') == event: return reply

    async def read(self, address, size):
        raw = base64.b64decode((await self.rpc('memory.read', address=address, size=size))['base64'])
        if len(raw) != size: raise RuntimeError('Incomplete memory read')
        return raw

    async def require_game(self):
        deadline = time.monotonic() + self.load_timeout
        while True:
            status = await self.rpc('game.status')
            game = status.get('game') or {}
            if game or time.monotonic() >= deadline: break
            await asyncio.sleep(.2)
        if game.get('id', '').replace('-', '') not in GAME_IDS:
            raise RuntimeError('The debugger is not running the supported TM4 game: ' + repr(game))
        return status

    async def running(self, wait_seconds=0):
        deadline=time.monotonic()+wait_seconds
        while True:
            status = await self.rpc('cpu.status')
            if not (status.get('stepping') or status.get('paused')):return
            if time.monotonic()>=deadline:
                raise RuntimeError('The CPU is already paused. Resume it before starting an automated probe.')
            # Startup can briefly report stepping before the first frame.
            # Wait for it to run naturally; never resume a manual stop here.
            await asyncio.sleep(.1)

    async def hit(self, address, seconds):
        deadline = time.monotonic() + seconds
        while True:
            status = await self.rpc('cpu.status')
            if status.get('stepping'):
                if status.get('pc') != address: raise RuntimeError('CPU stopped at a different breakpoint; inspect it manually.')
                return True
            if time.monotonic() >= deadline: return False
            await asyncio.sleep(min(.2, max(0, deadline - time.monotonic())))

    async def remove_probe(self, address):
        # Resume only a stop at the breakpoint owned by this operation.
        status = await self.rpc('cpu.status')
        await self.rpc('cpu.breakpoint.remove', address=address)
        if status.get('stepping') and status.get('pc') == address: await self.rpc('cpu.resume')

    async def add_probe(self, address, condition=''):
        # These two addresses are reserved for this isolated test instance.
        # Avoid cpu.breakpoint.list: it stalled the tested v1.20.4 debugger.
        await self.rpc('cpu.breakpoint.add', address=address, enabled=True, condition=condition, log=True)


async def navigate(debugger, boot_wait=15, wait_scale=1):
    await debugger.require_game()
    await debugger.running(wait_seconds=5)
    await debugger.add_probe(SCENE_ADDRESS)
    actions = []
    try:
        # Stop as soon as the scenario loop runs. Do not accidentally advance it.
        if await debugger.hit(SCENE_ADDRESS, boot_wait): return {'sceneReached': True, 'buttons': actions}
        # User-supplied route, followed by one title-menu retry for timing drift.
        steps = [('circle', 2), ('start', 2), ('start', 2), ('circle', 2),
                 ('circle', 8), ('start', 8), ('circle', 10), ('start', 10)]
        for button, wait in steps:
            print('PPSSPP: ' + button, file=sys.stderr, flush=True)
            await debugger.rpc('input.buttons.press', button=button, duration=10)
            actions.append(button)
            if await debugger.hit(SCENE_ADDRESS, wait * wait_scale):
                return {'sceneReached': True, 'buttons': actions}
        raise RuntimeError('First scenario was not detected. Inspect the title/menu state; use press or rerun with longer waits.')
    finally: await debugger.remove_probe(SCENE_ADDRESS)


async def verify(debugger, seconds=10, expected_character=None):
    await debugger.require_game()
    await debugger.running()
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'python'))
    import tm4_font
    mismatches = []
    for address, (_, expected) in tm4_font.PATCHES.items():
        if address == 0x08835d9c: expected = 0xc4409480  # post-loader relocation
        # The JIT may replace raw RAM words with EMUHACK block markers.
        # Disassembly resolves them back to the original instruction encoding.
        decoded = await debugger.rpc('memory.disasm', address=address, count=1, compact=False)
        line = next((line for line in decoded.get('lines', []) if line.get('address') == address), {})
        actual = line.get('encoding')
        if not isinstance(actual, int): raise RuntimeError(f'No decoded instruction at {address:08x}')
        if actual != expected: mismatches.append({'address': hex(address), 'expected': hex(expected), 'actual': hex(actual)})
    if mismatches: raise RuntimeError('Runtime half-width patch differs: ' + json.dumps(mismatches))
    await debugger.add_probe(DRAW_ADDRESS, 't4>=0x20 && t4<0x7f')
    try:
        if not await debugger.hit(DRAW_ADDRESS, seconds):
            raise RuntimeError('No scenario ASCII draw was observed. Reach a message containing ASCII; a Japanese-only message cannot pass this probe.')
        category = (await debugger.rpc('cpu.getAllRegs'))['categories'][0]
        regs = dict(zip(category['registerNames'], category['uintValues']))
        # The third-byte terminator is in the impending JAL delay slot; only
        # inspect the first two bytes, which have already been written.
        raw = await debugger.read(regs['a0'], 2)
        character = chr(regs['t4'])
        result = {'profile': tm4_font.PROFILE, 'patchWordsVerified': len(tm4_font.PATCHES),
                  'character': character, 'bufferHex': raw.hex(), 'drawX': regs['a1'],
                  'nextX': regs['s1'], 'advance': regs['s1'] - regs['a1']}
        if raw != bytes([regs['t4'], 0]) or result['advance'] != 8:
            raise RuntimeError('Incorrect ASCII serialization/advance: ' + json.dumps(result))
        if expected_character is not None and character != expected_character:
            raise RuntimeError('Unexpected first ASCII character: ' + json.dumps(result))
        return result
    finally: await debugger.remove_probe(DRAW_ADDRESS)


def save_result(result, output):
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if output:
        path = pathlib.Path(output); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(encoded + '\n', encoding='utf8')
    print(encoded)


async def remote(args):
    async with Debugger(args.port, args.timeout, args.load_timeout, args.trace) as debugger:
        if args.command == 'info':
            return {event: await debugger.rpc(event) for event in ('version', 'game.status', 'cpu.status')}
        await debugger.require_game()
        if args.command == 'press':
            await debugger.running()
            return await debugger.rpc('input.buttons.press', button=args.button, duration=args.duration)
        if args.command == 'navigate':
            result = await navigate(debugger, args.boot_wait, args.wait_scale)
            if args.verify: result['verification'] = await verify(debugger, args.scene_timeout, args.expected_character)
            return result
        if args.command == 'verify': return await verify(debugger, args.scene_timeout, args.expected_character)
        if args.command == 'disasm': return await debugger.rpc('memory.disasm', address=args.address, count=args.count, compact=True)
        if args.command == 'read':
            raw = await debugger.read(args.address, args.size)
            pathlib.Path(args.file).write_bytes(raw)
            return {'file': str(pathlib.Path(args.file).resolve()), 'bytes': len(raw)}
        raise ValueError(args.command)


def main():
    if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=20002)
    parser.add_argument('--timeout', type=float, default=10, help='RPC timeout in seconds')
    parser.add_argument('--load-timeout', type=float, default=60, help='Wait for the game ID after the debugger starts')
    parser.add_argument('--trace', action='store_true', help='Print RPC event names to stderr')
    parser.add_argument('--output', help='Optional JSON evidence file')
    sub = parser.add_subparsers(dest='command', required=True)
    setup = sub.add_parser('prepare', help='Create an isolated portable emulator copy')
    setup.add_argument('--source', required=True); setup.add_argument('--destination', required=True)
    setup.add_argument('--copy-saves', action='store_true', help='Copy SAVEDATA only on first preparation')
    sub.add_parser('info')
    press = sub.add_parser('press'); press.add_argument('button'); press.add_argument('--duration', type=int, default=10, help='Held emulated frames')
    for command in ('navigate', 'verify'):
        probe = sub.add_parser(command)
        probe.add_argument('--scene-timeout', type=float, default=10)
        probe.add_argument('--expected-character', help='Optional first ASCII character assertion')
        if command == 'navigate':
            probe.add_argument('--boot-wait', type=float, default=15)
            probe.add_argument('--wait-scale', type=float, default=1)
            probe.add_argument('--verify', action='store_true')
    disasm = sub.add_parser('disasm'); disasm.add_argument('address', type=lambda x: int(x, 0)); disasm.add_argument('--count', type=int, default=40)
    read = sub.add_parser('read'); read.add_argument('address', type=lambda x: int(x, 0)); read.add_argument('size', type=lambda x: int(x, 0)); read.add_argument('file')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535: parser.error('Port must be between 1 and 65535')
    try:
        result = prepare(args.source, args.destination, args.port, args.copy_saves) if args.command == 'prepare' else asyncio.run(remote(args))
        save_result(result, args.output)
    except (Exception, KeyboardInterrupt) as ex:
        save_result({'error': str(ex) or type(ex).__name__, 'command': args.command}, args.output)
        return 1
    return 0


if __name__ == '__main__': sys.exit(main())
