#!/usr/bin/env python3
"""Build a patched or diagnostic copy of the supported Gunslinger executable.

Run the copy with WINEDEBUG=+debugstr and look for '[coj-sprint]'.
The hooks report sprint state changes and rejection reasons, then replay
the original instructions.

Usage: python3 make-sprint-trace.py CoJGunslinger.exe /path/to/copy.exe
"""

from __future__ import annotations

import argparse
import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path


SUPPORTED_SHA256 = "ca1c4766900feb867372e0e2e87eb5adb92ca26ee537598a034ed7be1313d93c"
OUTPUT_DEBUG_STRING_IAT = 0x1258244
SPRINT_GRACE = 0x2E65B00
SPRINTF_IAT = 0x1258470


@dataclass(frozen=True)
class Hook:
    address: int
    original: str
    test: str
    pass_opcode: int | None
    pass_address: int
    reject_address: int
    replay_on_pass: str
    sprint_flag_operand: int | None
    message: str


HOOKS = (
    Hook(0xBAFDD1, "84 c0 74 e9 8b 4e 28", "84 c0", 0x85, 0xBAFDD8,
         0xBAFDBE, "8b 4e 28", 0x7E, "player state disallowed sprint"),
    Hook(0xBAFE23, "f6 c4 41 74 96", "f6 c4 41", 0x85, 0xBAFE28,
         0xBAFDBE, "", 0x7E, "movement controller speed fell below 10"),
    Hook(0xBAFE8E, "0f 8b 2a ff ff ff", "", 0x8A, 0xBAFE94,
         0xBAFDBE, "", 0x7E, "movement input magnitude fell below 0.60"),
    Hook(0xBAFEB4, "0f 84 04 ff ff ff", "", 0x85, 0xBAFEBA,
         0xBAFDBE, "", 0x7E, "movement input exceeded the 60 degree forward cone"),
    Hook(0xBAFF51, "0f 8b 38 01 00 00", "", 0x8A, 0xBAFF57,
         0xBB008F, "", 0x7B, "sprint action read as zero"),
    Hook(0xBB008A, "f6 c4 41 75 15", "f6 c4 41", 0x85, 0xBB00A4,
         0xBB008F, "", 0x7B, "sprint continuation timer expired"),
    Hook(0xBB58BC, "c6 43 44 01 8b 47 20", "", None, 0,
         0xBB58C3, "", None, "sprint started"),
    Hook(0xBB585F, "88 5e 44 88 5e 31", "", None, 0,
         0xBB5865, "", 0x7E, "sprint stopped"),
)

CLOCK_HOOK = Hook(0xBB0085, "d8 5b 4c df e0 f6 c4 41 75 15", "", None, 0xBB00A4,
                  0xBB008F, "", None, "")


def relative(opcode, address, target):
    return opcode + struct.pack("<i", target - address - len(opcode) - 4)


def make_gateway(hook, start):
    code = bytearray.fromhex(hook.test)
    branch = len(code)
    if hook.pass_opcode is not None:
        code += b"\x0f" + bytes([hook.pass_opcode]) + b"\0" * 4
    code += b"\x9c"
    if hook.sprint_flag_operand is not None:
        code += b"\x80" + bytes([hook.sprint_flag_operand, 0x44, 0])
        skip_logging = len(code)
        code += b"\x74\x00"

    # Keep the original x87/SSE state, general registers and branch flags.
    code += bytes.fromhex("60 89 e5 81 ec 80 02 00 00 83 e4 f0 0f ae 04 24 dd b4 24 00 02 00 00")
    # Recover the image-relative code address and use it to locate the IAT.
    code += bytes.fromhex("e8 00 00 00 00")
    anchor = start + len(code)
    code += bytes.fromhex("58 8d 90")
    message_ref = len(code)
    code += b"\0" * 4
    code += bytes.fromhex("52 ff 90")
    code += struct.pack("<i", OUTPUT_DEBUG_STRING_IAT - anchor)
    code += bytes.fromhex("0f ae 0c 24 dd a4 24 00 02 00 00 89 ec 61")

    if hook.sprint_flag_operand is not None:
        code[skip_logging + 1] = len(code) - skip_logging - 2
    code += b"\x9d"
    if hook.pass_opcode is None:
        code += bytes.fromhex(hook.original)
    code += relative(b"\xe9", start + len(code), hook.reject_address)
    if hook.pass_opcode is not None:
        code[branch:branch + 6] = relative(
            b"\x0f" + bytes([hook.pass_opcode]), start + branch, start + len(code)
        )
        code += bytes.fromhex(hook.replay_on_pass)
        code += relative(b"\xe9", start + len(code), hook.pass_address)
    struct.pack_into("<i", code, message_ref, start + len(code) - anchor)
    code += ("[coj-sprint] " + hook.message + "\n").encode("ascii") + b"\0"
    return code


def make_clock_gateway(hook, start):
    # Copy ST(0) to a 10-byte stack slot, then perform the original
    # compare-and-pop. No calls happen before the comparison.
    code = bytearray.fromhex("8d 64 24 f4 d9 c0 db 3c 24")
    code += bytes.fromhex(hook.original)[:-2]
    branch = len(code)
    code += b"\x0f\x85" + b"\0" * 4

    # Keep the game's register state, including the original status in AX.
    code += bytes.fromhex("9c 60 89 e5 81 ec c0 03 00 00 83 e4 f0 89 e6")
    code += bytes.fromhex("d9 be 70 02 00 00")  # Save x87 control word.
    code += bytes.fromhex("0f ae 06 dd b6 00 02 00 00")  # FXSAVE and FNSAVE.
    code += bytes.fromhex("e8 00 00 00 00")
    anchor = start + len(code)
    code += b"\x5f"  # EDI holds the relocated address of this instruction.

    # Push sprintf arguments in reverse order: CW, SW, grace, deadline,
    # clock significand low/high, clock exponent, format and output buffer.
    code += bytes.fromhex("0f b7 86 70 02 00 00 50 0f b7 45 1c 50 ff b7")
    code += struct.pack("<i", SPRINT_GRACE - anchor)
    code += bytes.fromhex("ff 73 4c ff 75 24 ff 75 28 0f b7 45 2c 50 8d 87")
    format_ref = len(code)
    code += b"\0" * 4
    code += bytes.fromhex("50 8d 86 80 02 00 00 50 ff 97")
    code += struct.pack("<i", SPRINTF_IAT - anchor)
    code += bytes.fromhex("83 c4 24 8d 86 80 02 00 00 50 ff 97")
    code += struct.pack("<i", OUTPUT_DEBUG_STRING_IAT - anchor)
    code += bytes.fromhex("0f ae 0e dd a6 00 02 00 00 89 ec 61 9d")
    code += bytes.fromhex("8d 64 24 0c")
    code += relative(b"\xe9", start + len(code), hook.reject_address)

    code[branch:branch + 6] = relative(b"\x0f\x85", start + branch, start + len(code))
    code += bytes.fromhex("8d 64 24 0c")
    code += relative(b"\xe9", start + len(code), hook.pass_address)
    struct.pack_into("<i", code, format_ref, start + len(code) - anchor)
    code += b"[coj-sprint] timer expired now80=%04X%08X%08X deadline32=%08X grace32=%08X sw=%04X cw=%04X\n\0"
    return code


def make_rounded_clock_gateway(hook, start):
    # Round ST(0) to the same binary32 format as the stored deadline.
    # LEA adjusts the scratch slot without touching integer flags.
    code = bytearray.fromhex("8d 64 24 fc d9 1c 24 d9 04 24 8d 64 24 04")
    code += bytes.fromhex(hook.original)[:-2]
    code += relative(b"\x0f\x85", start + len(code), hook.pass_address)
    code += relative(b"\xe9", start + len(code), hook.reject_address)
    return code


def align(value, alignment):
    return (value + alignment - 1) // alignment * alignment


def build(original, *, test_sprint_fix=False, sprint_fix=False, trace_sprint_clock=False,
          sprint_clock_fix=False):
    if hashlib.sha256(original).hexdigest() != SUPPORTED_SHA256:
        raise ValueError("Unsupported game build. The source file was not modified.")

    image = bytearray(original)
    pe = struct.unpack_from("<I", image, 0x3C)[0]
    count = struct.unpack_from("<H", image, pe + 6)[0]
    optional_size = struct.unpack_from("<H", image, pe + 20)[0]
    optional = pe + 24
    sections = optional + optional_size
    base, virtual_alignment, file_alignment = struct.unpack_from("<III", image, optional + 28)
    _, text_rva, text_size, text_file = struct.unpack_from("<IIII", image, sections + 8)
    timeout_branch = 0xBB008D
    if sprint_fix or test_sprint_fix:
        offset = text_file + timeout_branch - base - text_rva
        if image[offset:offset + 2] != b"\x75\x15":
            raise ValueError("Unexpected continuation timeout branch.")
        # Preserve the comparison and branch target, and skip cancellation.
        image[offset] = 0xEB  # JNE rel8 becomes JMP rel8.
    if sprint_fix:
        return image

    size_of_image, size_of_headers = struct.unpack_from("<II", image, optional + 56)
    section = sections + count * 40
    if section + 40 > size_of_headers or any(image[section:section + 40]):
        raise ValueError("No room for an additional section header.")

    trace_rva = align(size_of_image, virtual_alignment)
    gateways = bytearray()
    if sprint_clock_fix:
        hooks, make_hook = (CLOCK_HOOK,), make_rounded_clock_gateway
    elif trace_sprint_clock:
        hooks, make_hook = (CLOCK_HOOK,), make_clock_gateway
    else:
        hooks, make_hook = HOOKS, make_gateway
    for hook in hooks:
        if test_sprint_fix and hook.address == 0xBB008A:
            continue
        in_section = hook.address - base - text_rva
        expected = bytes.fromhex(hook.original)
        if not 0 <= in_section <= text_size - len(expected):
            raise ValueError(f"Hook outside the code section at {hook.address:#x}.")
        offset = text_file + in_section
        if image[offset:offset + len(expected)] != expected:
            raise ValueError(f"Unexpected instruction bytes at {hook.address:#x}.")
        target = base + trace_rva + len(gateways)
        jump = relative(b"\xe9", hook.address, target)
        image[offset:offset + len(expected)] = jump.ljust(len(expected), b"\x90")
        gateways += make_hook(hook, target)

    # Keep the original certificate as an end-of-file record. Its signature
    # cannot validate the instrumented copy because the executable changed.
    security_dir = optional + 96 + 4 * 8
    certificate_offset, certificate_size = struct.unpack_from("<II", image, security_dir)
    if certificate_offset + certificate_size != len(image):
        raise ValueError("Unexpected certificate location.")
    certificate = image[certificate_offset:]
    del image[certificate_offset:]
    trace_file = align(len(image), file_alignment)
    trace_size = align(len(gateways), file_alignment)
    image += bytes(trace_file - len(image))
    image += gateways.ljust(trace_size, b"\0")
    struct.pack_into("<II", image, security_dir, len(image), certificate_size)
    image += certificate

    struct.pack_into("<8sIIIIIIHHI", image, section, b".cojdiag", len(gateways),
                     trace_rva, trace_size, trace_file, 0, 0, 0, 0, 0x60000020)
    struct.pack_into("<H", image, pe + 6, count + 1)
    code_size = struct.unpack_from("<I", image, optional + 4)[0]
    struct.pack_into("<I", image, optional + 4, code_size + trace_size)
    struct.pack_into("<II", image, optional + 56,
                     align(trace_rva + len(gateways), virtual_alignment), size_of_headers)
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--test-sprint-fix", action="store_true",
                       help="Bypass the continuation timeout and log sprint events.")
    modes.add_argument("--sprint-fix", action="store_true",
                       help="Bypass the continuation timeout for normal play.")
    modes.add_argument("--trace-sprint-clock", action="store_true",
                       help="Log the exact operands of expired sprint deadlines.")
    modes.add_argument("--sprint-clock-fix", action="store_true",
                       help="Round the sprint clock reading to match the stored deadline.")
    parser.add_argument("original", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        patched = build(args.original.read_bytes(), test_sprint_fix=args.test_sprint_fix,
                        sprint_fix=args.sprint_fix, trace_sprint_clock=args.trace_sprint_clock,
                        sprint_clock_fix=args.sprint_clock_fix)
        with args.output.open("xb") as output:
            output.write(patched)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    print(f"Created {args.output}.")


if __name__ == "__main__":
    main()
