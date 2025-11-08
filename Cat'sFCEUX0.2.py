# program.py - Cat's FCEUX 0.2 (Homebrew-focused single-file NES emulator)
# [C] 2025 Samsoft / Cat-san
#
# NOTE (scope):
# - This build targets *homebrew-friendly* NROM/UxROM/CNROM ROMs.
# - Official 6502 opcodes implemented (no "illegal" opcodes).
# - PPU renders background + 8x8 sprites using CHR ROM/RAM, nametables, attributes, palettes, mirroring.
# - Controller I/O (0x4016) implemented.
# - DMA (0x4014) implemented with cycle stall.
# - APU is a stub (no audio output yet).
# - Timing is not cycle-accurate, but adequate for many homebrew projects.
#
# Dependencies: tkinter, PIL (Pillow), numpy
#
# Run:
#   python program.py
#
# Keys:
#   Z: A, X: B, Enter: START, Right Shift: SELECT, Arrows: D-Pad
#
# -----------------------------

import tkinter as tk
from tkinter import Menu, messagebox, filedialog, simpledialog
import struct
import numpy as np
from typing import Optional, Tuple
from PIL import Image, ImageTk

# ────────────────────────────────────────────────────────────────────────────────────
# Helpers / Constants
# ────────────────────────────────────────────────────────────────────────────────────

def clamp8(v: int) -> int:
    return v & 0xFF

def hi(x: int) -> int:
    return (x >> 8) & 0xFF

def lo(x: int) -> int:
    return x & 0xFF

# NTSC CPU cycles per frame ~ 29780.5; use 29781
CPU_CYCLES_PER_FRAME = 29781

# NES master palette (64 colors). Values approximate gamma-adjusted sRGB.
# Source: widely published approximations; fine-tuned for readability.
NES_PALETTE = np.array([
    [84,  84,  84],[  0,  30, 116],[  8,  16, 144],[ 48,   0, 136],
    [68,   0, 100],[92,   0,  48],[84,   4,   0],[60,  24,   0],
    [32,  42,   0],[  8,  58,   0],[  0,  64,   0],[  0,  60,  0],
    [  0,  50, 60],[  0,   0,   0],[  0,   0,   0],[  0,   0,   0],
    [152, 150, 152],[  8,  76, 196],[ 48,  50, 236],[ 92,  30, 228],
    [136,  20, 176],[160,  20, 100],[152,  34,  32],[120,  60,   0],
    [ 84,  90,   0],[ 40, 114,   0],[  8, 124,   0],[  0, 118,  40],
    [  0, 102, 120],[  0,   0,   0],[  0,   0,   0],[  0,   0,   0],
    [236, 238, 236],[ 76, 154, 236],[120, 124, 236],[176,  98, 236],
    [228,  84, 236],[236,  88, 180],[236, 106, 100],[212, 136,  32],
    [160, 170,   0],[116, 196,   0],[ 76, 208,  32],[ 56, 204, 108],
    [ 56, 180, 204],[ 60,  60,  60],[  0,   0,   0],[  0,   0,   0],
    [236, 238, 236],[168, 204, 236],[188, 188, 236],[212, 178, 236],
    [236, 174, 236],[236, 174, 212],[236, 180, 176],[228, 196, 144],
    [204, 210, 120],[180, 222, 120],[168, 226, 144],[152, 226, 180],
    [160, 214, 228],[160, 162, 160],[  0,   0,   0],[  0,   0,   0],
], dtype=np.uint8)

# ────────────────────────────────────────────────────────────────────────────────────
# Controllers
# ────────────────────────────────────────────────────────────────────────────────────

class Controller:
    def __init__(self, nes: 'NESBackend'):
        self.nes = nes
        self.strobe = 0
        self.buttons = 0  # bit0=A,1=B,2=SELECT,3=START,4=UP,5=DOWN,6=LEFT,7=RIGHT
        self.shift = 0

    def set_button(self, name: str, pressed: bool):
        bit = {'A':0,'B':1,'SELECT':2,'START':3,'UP':4,'DOWN':5,'LEFT':6,'RIGHT':7}.get(name, None)
        if bit is None: return
        if pressed:
            self.buttons |= (1 << bit)
        else:
            self.buttons &= ~(1 << bit)

    def write(self, value: int):
        self.strobe = value & 1
        if self.strobe:
            self.shift = self.buttons

    def read(self) -> int:
        if self.strobe:
            self.shift = self.buttons
        val = (self.shift & 1) | 0x40  # bit6 set like real NES
        self.shift = (self.shift >> 1) | 0x80  # after 8 reads becomes 1s
        return val

# ────────────────────────────────────────────────────────────────────────────────────
# Mapper(s)
# ────────────────────────────────────────────────────────────────────────────────────

class BaseMapper:
    def __init__(self, nes: 'NESBackend', mapper_id: int, prg_rom: bytes, chr_data: bytes, prg_banks: int, chr_banks: int, mirroring: str, chr_is_ram: bool):
        self.nes = nes
        self.id = mapper_id
        self.prg = bytearray(prg_rom)
        self.chr = bytearray(chr_data if len(chr_data) else bytes(0x2000))
        self.prg_banks = max(1, prg_banks)
        self.chr_banks = max(1, chr_banks if len(chr_data) else 1)
        self.mirroring = mirroring  # 'H' or 'V'
        self.chr_is_ram = chr_is_ram

    # CPU PRG
    def cpu_read(self, addr: int) -> int:
        raise NotImplementedError

    def cpu_write(self, addr: int, value: int):
        pass

    # PPU CHR
    def ppu_read(self, addr: int) -> int:
        return self.chr[addr % len(self.chr)]

    def ppu_write(self, addr: int, value: int):
        if self.chr_is_ram:
            self.chr[addr % len(self.chr)] = value

class MapperNROM(BaseMapper):
    # Mapper 0 (NROM) 16K/32K PRG, CHR ROM or CHR RAM
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.prg_bank_lo = 0
        self.prg_bank_hi = self.prg_banks - 1

    def cpu_read(self, addr: int) -> int:
        if 0x8000 <= addr <= 0xBFFF:
            off = self.prg_bank_lo * 0x4000 + (addr - 0x8000)
            return self.prg[off % len(self.prg)]
        elif 0xC000 <= addr <= 0xFFFF:
            off = self.prg_bank_hi * 0x4000 + (addr - 0xC000)
            return self.prg[off % len(self.prg)]
        return 0

class MapperUxROM(BaseMapper):
    # Mapper 2 (UxROM) - switch 16KB @ 0x8000, fixed 16KB @ 0xC000
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bank = 0
        self.fixed = self.prg_banks - 1

    def cpu_read(self, addr: int) -> int:
        if 0x8000 <= addr <= 0xBFFF:
            off = self.bank * 0x4000 + (addr - 0x8000)
            return self.prg[off % len(self.prg)]
        elif 0xC000 <= addr <= 0xFFFF:
            off = self.fixed * 0x4000 + (addr - 0xC000)
            return self.prg[off % len(self.prg)]
        return 0

    def cpu_write(self, addr: int, value: int):
        if 0x8000 <= addr <= 0xFFFF:
            self.bank = value & (self.prg_banks - 1)

class MapperCNROM(BaseMapper):
    # Mapper 3 (CNROM) - switch 8KB CHR
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.chr_bank = 0

    def cpu_write(self, addr: int, value: int):
        if 0x8000 <= addr <= 0xFFFF:
            self.chr_bank = value & (self.chr_banks - 1)

    def ppu_read(self, addr: int) -> int:
        bank_off = self.chr_bank * 0x2000
        return self.chr[(bank_off + addr) % len(self.chr)]

def make_mapper(nes: 'NESBackend', mapper_id: int, prg_rom: bytes, chr_data: bytes, mirroring: str, chr_is_ram: bool) -> BaseMapper:
    prg_banks = max(1, len(prg_rom) // 0x4000)
    chr_banks = max(1, len(chr_data) // 0x2000) if len(chr_data) else 1
    if mapper_id == 0:
        return MapperNROM(nes, mapper_id, prg_rom, chr_data, prg_banks, chr_banks, mirroring, chr_is_ram)
    if mapper_id == 2:
        return MapperUxROM(nes, mapper_id, prg_rom, chr_data, prg_banks, chr_banks, mirroring, chr_is_ram)
    if mapper_id == 3:
        return MapperCNROM(nes, mapper_id, prg_rom, chr_data, prg_banks, chr_banks, mirroring, chr_is_ram)
    # Fallback: treat unsupported mappers as NROM to avoid crashes (may not run properly).
    return MapperNROM(nes, mapper_id, prg_rom, chr_data, prg_banks, chr_banks, mirroring, chr_is_ram)

# ────────────────────────────────────────────────────────────────────────────────────
# CPU (6502) - official opcodes
# ────────────────────────────────────────────────────────────────────────────────────

class CPU:
    def __init__(self, nes: 'NESBackend'):
        self.nes = nes
        self.pc = 0
        self.sp = 0xFD
        self.a = 0
        self.x = 0
        self.y = 0
        self.flags = 0x24  # I and unused
        self.cycles = 0
        self.stall = 0
        self.nmi_pending = False
        self.irq_pending = False

    # Flag bits
    C=0x01; Z=0x02; I=0x04; D=0x08; B=0x10; U=0x20; V=0x40; N=0x80

    # Bus access
    def read(self, addr: int) -> int:
        a = addr & 0xFFFF
        if a < 0x2000:
            return self.nes.ram[a & 0x7FF]
        elif 0x2000 <= a <= 0x3FFF:
            return self.nes.ppu.read_reg( a & 7 )
        elif a == 0x4016:
            return self.nes.controller1.read()
        elif a == 0x4017:
            return self.nes.controller2.read()
        elif 0x4000 <= a <= 0x4017:
            return self.nes.apu.read_reg(a)
        elif 0x6000 <= a <= 0x7FFF:
            return self.nes.sram[a - 0x6000]
        elif a >= 0x8000:
            return self.nes.mapper.cpu_read(a)
        else:
            return 0

    def write(self, addr: int, value: int):
        a = addr & 0xFFFF
        v = value & 0xFF
        if a < 0x2000:
            self.nes.ram[a & 0x7FF] = v
        elif 0x2000 <= a <= 0x3FFF:
            self.nes.ppu.write_reg(a & 7, v)
        elif a == 0x4014:
            # OAM DMA
            self.nes.ppu.do_oam_dma(v)
            # Stall CPU for 513 or 514 cycles depending on alignment
            self.stall += 513 + (1 if (self.cycles & 1) else 0)
        elif a == 0x4016:
            self.nes.controller1.write(v)
        elif a == 0x4017:
            self.nes.controller2.write(v)
        elif 0x4000 <= a <= 0x4017:
            self.nes.apu.write_reg(a, v)
        elif 0x6000 <= a <= 0x7FFF:
            self.nes.sram[a - 0x6000] = v
        elif a >= 0x8000:
            self.nes.mapper.cpu_write(a, v)

    def read_word(self, addr: int) -> int:
        lo_ = self.read(addr)
        hi_ = self.read(addr+1)
        return (hi_ << 8) | lo_

    def push(self, v: int):
        self.nes.ram[0x100 + (self.sp & 0xFF)] = v & 0xFF
        self.sp = (self.sp - 1) & 0xFF

    def pull(self) -> int:
        self.sp = (self.sp + 1) & 0xFF
        return self.nes.ram[0x100 + (self.sp & 0xFF)]

    def set_flag(self, m: int, c: bool):
        if c: self.flags |= m
        else: self.flags &= ~m

    def get_flag(self, m: int) -> int:
        return 1 if (self.flags & m) else 0

    def update_zn(self, v: int):
        self.set_flag(self.Z, (v & 0xFF) == 0)
        self.set_flag(self.N, (v & 0x80) != 0)

    def reset(self):
        self.sp = 0xFD
        self.flags = 0x24
        self.a = self.x = self.y = 0
        self.pc = self.read_word(0xFFFC)
        if self.pc < 0x8000:
            # Some homebrew/test ROMs expect reset at C000 when vectors mirror to ROM end
            self.pc = 0xC000
        self.cycles = 0
        self.stall = 0
        self.nmi_pending = False
        self.irq_pending = False

    # Interrupts
    def nmi(self):
        self.nmi_pending = True

    def irq(self):
        if not self.get_flag(self.I):
            self.irq_pending = True

    def do_interrupt(self, vector_addr: int, brk_flag: int):
        # Push PC and flags, set I
        self.push(hi(self.pc))
        self.push(lo(self.pc))
        # B and U bits behavior: B set only for BRK; U always set
        f = (self.flags | self.U) & 0xEF  # clear B
        f |= brk_flag
        self.push(f)
        self.set_flag(self.I, True)
        self.pc = self.read_word(vector_addr)
        self.cycles += 7

    # Addressing helpers
    def fetch_imm(self) -> Tuple[int, Optional[int], bool]:
        v = self.read(self.pc); self.pc = (self.pc + 1) & 0xFFFF
        return v, None, False

    def fetch_zp(self) -> Tuple[int, int, bool]:
        a = self.read(self.pc); self.pc = (self.pc + 1) & 0xFFFF
        return self.read(a), a, False

    def fetch_zpx(self) -> Tuple[int, int, bool]:
        a = (self.read(self.pc) + self.x) & 0xFF; self.pc = (self.pc + 1) & 0xFFFF
        return self.read(a), a, False

    def fetch_zpy(self) -> Tuple[int, int, bool]:
        a = (self.read(self.pc) + self.y) & 0xFF; self.pc = (self.pc + 1) & 0xFFFF
        return self.read(a), a, False

    def fetch_abs(self) -> Tuple[int, int, bool]:
        a = self.read_word(self.pc); self.pc = (self.pc + 2) & 0xFFFF
        return self.read(a), a, False

    def fetch_absx(self) -> Tuple[int, int, bool]:
        base = self.read_word(self.pc); self.pc = (self.pc + 2) & 0xFFFF
        a = (base + self.x) & 0xFFFF
        crossed = ((base & 0xFF00) != (a & 0xFF00))
        return self.read(a), a, crossed

    def fetch_absy(self) -> Tuple[int, int, bool]:
        base = self.read_word(self.pc); self.pc = (self.pc + 2) & 0xFFFF
        a = (base + self.y) & 0xFFFF
        crossed = ((base & 0xFF00) != (a & 0xFF00))
        return self.read(a), a, crossed

    def fetch_ind(self) -> int:
        ptr = self.read_word(self.pc); self.pc = (self.pc + 2) & 0xFFFF
        # 6502 indirect bug: page wrap for low byte fetch
        lo_addr = ptr
        hi_addr = (ptr & 0xFF00) | ((ptr + 1) & 0xFF)
        return (self.read(hi_addr) << 8) | self.read(lo_addr)

    def fetch_indx(self) -> Tuple[int, int, bool]:
        zp = (self.read(self.pc) + self.x) & 0xFF; self.pc = (self.pc + 1) & 0xFFFF
        lo_ = self.read(zp); hi_ = self.read((zp + 1) & 0xFF)
        a = ((hi_ << 8) | lo_) & 0xFFFF
        return self.read(a), a, False

    def fetch_indy(self) -> Tuple[int, int, bool]:
        zp = self.read(self.pc); self.pc = (self.pc + 1) & 0xFFFF
        lo_ = self.read(zp); hi_ = self.read((zp + 1) & 0xFF)
        base = ((hi_ << 8) | lo_) & 0xFFFF
        a = (base + self.y) & 0xFFFF
        crossed = ((base & 0xFF00) != (a & 0xFF00))
        return self.read(a), a, crossed

    # Core execution
    def step(self) -> int:
        if self.stall > 0:
            take = min(self.stall, 2)  # consume in small chunks to interleave with PPU steps
            self.stall -= take
            self.cycles += take
            return take

        # service NMI/IRQ between instructions
        if self.nmi_pending:
            self.nmi_pending = False
            self.do_interrupt(0xFFFA, 0)  # BRK flag not set for NMI
            return 7
        if self.irq_pending and not self.get_flag(self.I):
            self.irq_pending = False
            self.do_interrupt(0xFFFE, 0)
            return 7

        op = self.read(self.pc); self.pc = (self.pc + 1) & 0xFFFF

        # Generated decode covering official instruction set. Invalid opcodes -> NOP (2 cycles).
        # To keep code size contained, we implement by groups.
        c = 0  # cycles this instruction

        # --- Single-byte implied/accumulator ---
        if op == 0x00:  # BRK
            self.pc = (self.pc + 1) & 0xFFFF  # skip padding byte like real 6502
            self.do_interrupt(0xFFFE, self.B)
            return 7
        elif op == 0x18: self.set_flag(self.C, False); c=2
        elif op == 0x38: self.set_flag(self.C, True);  c=2
        elif op == 0x58: self.set_flag(self.I, False); c=2
        elif op == 0x78: self.set_flag(self.I, True);  c=2
        elif op == 0xB8: self.set_flag(self.V, False); c=2
        elif op == 0xD8: self.set_flag(self.D, False); c=2
        elif op == 0xF8: self.set_flag(self.D, True);  c=2
        elif op == 0xEA: c=2  # NOP
        elif op == 0xAA: self.x = self.a; self.update_zn(self.x); c=2  # TAX
        elif op == 0x8A: self.a = self.x; self.update_zn(self.a); c=2  # TXA
        elif op == 0xCA: self.x = clamp8(self.x - 1); self.update_zn(self.x); c=2  # DEX
        elif op == 0xE8: self.x = clamp8(self.x + 1); self.update_zn(self.x); c=2  # INX
        elif op == 0xA8: self.y = self.a; self.update_zn(self.y); c=2  # TAY
        elif op == 0x98: self.a = self.y; self.update_zn(self.a); c=2  # TYA
        elif op == 0x88: self.y = clamp8(self.y - 1); self.update_zn(self.y); c=2  # DEY
        elif op == 0xC8: self.y = clamp8(self.y + 1); self.update_zn(self.y); c=2  # INY
        elif op == 0x9A: self.sp = self.x; c=2  # TXS
        elif op == 0xBA: self.x = self.sp; self.update_zn(self.x); c=2  # TSX
        elif op == 0x48: self.push(self.a); c=3  # PHA
        elif op == 0x68: self.a = self.pull(); self.update_zn(self.a); c=4  # PLA
        elif op == 0x08: self.push(self.flags | self.B | self.U); c=3  # PHP
        elif op == 0x28:
            self.flags = (self.pull() | self.U) & 0xEF  # PLP
            c=4
        elif op == 0x40:
            # RTI
            self.flags = (self.pull() | self.U) & 0xEF
            lo_ = self.pull(); hi_ = self.pull()
            self.pc = ((hi_ << 8) | lo_) & 0xFFFF
            c=6
        elif op == 0x60:
            # RTS
            lo_ = self.pull(); hi_ = self.pull()
            self.pc = (((hi_ << 8) | lo_) + 1) & 0xFFFF
            c=6
        elif op == 0x0A:
            # ASL A
            old = self.a
            self.set_flag(self.C, (old & 0x80) != 0)
            self.a = clamp8(old << 1)
            self.update_zn(self.a)
            c=2
        elif op == 0x4A:
            # LSR A
            old = self.a
            self.set_flag(self.C, (old & 1) != 0)
            self.a = (old >> 1) & 0xFF
            self.update_zn(self.a)
            c=2
        elif op == 0x2A:
            # ROL A
            old = self.a
            carry = self.get_flag(self.C)
            self.set_flag(self.C, (old & 0x80) != 0)
            self.a = ((old << 1) | carry) & 0xFF
            self.update_zn(self.a); c=2
        elif op == 0x6A:
            # ROR A
            old = self.a
            carry = self.get_flag(self.C)
            self.set_flag(self.C, (old & 1) != 0)
            self.a = ((carry << 7) | (old >> 1)) & 0xFF
            self.update_zn(self.a); c=2

        # --- Jumps / Branches ---
        elif op == 0x4C:  # JMP abs
            self.pc = self.read_word(self.pc); c=3
        elif op == 0x6C:  # JMP ind
            self.pc = self.fetch_ind(); c=5
        elif op == 0x20:  # JSR abs
            addr = self.read_word(self.pc); self.pc = (self.pc + 2) & 0xFFFF
            temp = (self.pc - 1) & 0xFFFF
            self.push(hi(temp)); self.push(lo(temp))
            self.pc = addr; c=6
        elif op in (0x10,0x30,0x50,0x70,0x90,0xB0,0xF0,0xD0):
            # BPL,BMI,BVC,BVS,BCC,BCS,BEQ,BNE
            offset = self.read(self.pc); self.pc = (self.pc + 1) & 0xFFFF
            if offset & 0x80: offset -= 0x100
            cond = False
            if op == 0x10: cond = (self.get_flag(self.N)==0)
            elif op == 0x30: cond = (self.get_flag(self.N)==1)
            elif op == 0x50: cond = (self.get_flag(self.V)==0)
            elif op == 0x70: cond = (self.get_flag(self.V)==1)
            elif op == 0x90: cond = (self.get_flag(self.C)==0)
            elif op == 0xB0: cond = (self.get_flag(self.C)==1)
            elif op == 0xF0: cond = (self.get_flag(self.Z)==1)
            elif op == 0xD0: cond = (self.get_flag(self.Z)==0)
            c = 2
            if cond:
                old_pc = self.pc
                self.pc = (self.pc + offset) & 0xFFFF
                c += 1
                if (old_pc & 0xFF00) != (self.pc & 0xFF00): c += 1

        # --- Load/Store ---
        elif op in (0xA9,0xA5,0xB5,0xAD,0xBD,0xB9,0xA1,0xB1):  # LDA
            if   op == 0xA9: v,_,_= self.fetch_imm(); c=2
            elif op == 0xA5: v,_,_= self.fetch_zp();  c=3
            elif op == 0xB5: v,_,_= self.fetch_zpx(); c=4
            elif op == 0xAD: v,_,_= self.fetch_abs(); c=4
            elif op == 0xBD: v,_,x= self.fetch_absx(); c=4 + (1 if x else 0)
            elif op == 0xB9: v,_,x= self.fetch_absy(); c=4 + (1 if x else 0)
            elif op == 0xA1: v,_,_= self.fetch_indx(); c=6
            elif op == 0xB1: v,_,x= self.fetch_indy(); c=5 + (1 if x else 0)
            self.a = v & 0xFF; self.update_zn(self.a)
        elif op in (0xA2,0xA6,0xB6,0xAE,0xBE):  # LDX
            if   op == 0xA2: v,_,_= self.fetch_imm(); c=2
            elif op == 0xA6: v,_,_= self.fetch_zp();  c=3
            elif op == 0xB6: v,_,_= self.fetch_zpy(); c=4
            elif op == 0xAE: v,_,_= self.fetch_abs(); c=4
            elif op == 0xBE: v,_,x= self.fetch_absy(); c=4 + (1 if x else 0)
            self.x = v & 0xFF; self.update_zn(self.x)
        elif op in (0xA0,0xA4,0xB4,0xAC,0xBC):  # LDY
            if   op == 0xA0: v,_,_= self.fetch_imm(); c=2
            elif op == 0xA4: v,_,_= self.fetch_zp();  c=3
            elif op == 0xB4: v,_,_= self.fetch_zpx(); c=4
            elif op == 0xAC: v,_,_= self.fetch_abs(); c=4
            elif op == 0xBC: v,_,x= self.fetch_absx(); c=4 + (1 if x else 0)
            self.y = v & 0xFF; self.update_zn(self.y)
        elif op in (0x85,0x95,0x8D,0x9D,0x99,0x81,0x91):  # STA
            if   op == 0x85: _,a,_= self.fetch_zp();  c=3
            elif op == 0x95: _,a,_= self.fetch_zpx(); c=4
            elif op == 0x8D: _,a,_= self.fetch_abs(); c=4
            elif op == 0x9D: _,a,_= self.fetch_absx(); c=5
            elif op == 0x99: _,a,_= self.fetch_absy(); c=5
            elif op == 0x81: _,a,_= self.fetch_indx(); c=6
            elif op == 0x91: _,a,_= self.fetch_indy(); c=6
            self.write(a, self.a)
        elif op in (0x86,0x96,0x8E):  # STX
            if   op == 0x86: _,a,_= self.fetch_zp();  c=3
            elif op == 0x96: _,a,_= self.fetch_zpy(); c=4
            elif op == 0x8E: _,a,_= self.fetch_abs(); c=4
            self.write(a, self.x)
        elif op in (0x84,0x94,0x8C):  # STY
            if   op == 0x84: _,a,_= self.fetch_zp();  c=3
            elif op == 0x94: _,a,_= self.fetch_zpx(); c=4
            elif op == 0x8C: _,a,_= self.fetch_abs(); c=4
            self.write(a, self.y)

        # --- Arithmetic / Logic ---
        elif op in (0x69,0x65,0x75,0x6D,0x7D,0x79,0x61,0x71):  # ADC
            if   op == 0x69: v,_,_= self.fetch_imm(); c=2
            elif op == 0x65: v,_,_= self.fetch_zp();  c=3
            elif op == 0x75: v,_,_= self.fetch_zpx(); c=4
            elif op == 0x6D: v,_,_= self.fetch_abs(); c=4
            elif op == 0x7D: v,_,x= self.fetch_absx(); c=4 + (1 if x else 0)
            elif op == 0x79: v,_,x= self.fetch_absy(); c=4 + (1 if x else 0)
            elif op == 0x61: v,_,_= self.fetch_indx(); c=6
            elif op == 0x71: v,_,x= self.fetch_indy(); c=5 + (1 if x else 0)
            carry = self.get_flag(self.C)
            res = self.a + v + carry
            self.set_flag(self.C, res > 0xFF)
            self.set_flag(self.V, (~(self.a ^ v) & (self.a ^ res) & 0x80) != 0)
            self.a = res & 0xFF; self.update_zn(self.a)
        elif op in (0xE9,0xE5,0xF5,0xED,0xFD,0xF9,0xE1,0xF1):  # SBC
            if   op == 0xE9: v,_,_= self.fetch_imm(); c=2
            elif op == 0xE5: v,_,_= self.fetch_zp();  c=3
            elif op == 0xF5: v,_,_= self.fetch_zpx(); c=4
            elif op == 0xED: v,_,_= self.fetch_abs(); c=4
            elif op == 0xFD: v,_,x= self.fetch_absx(); c=4 + (1 if x else 0)
            elif op == 0xF9: v,_,x= self.fetch_absy(); c=4 + (1 if x else 0)
            elif op == 0xE1: v,_,_= self.fetch_indx(); c=6
            elif op == 0xF1: v,_,x= self.fetch_indy(); c=5 + (1 if x else 0)
            carry = self.get_flag(self.C)
            v ^= 0xFF
            res = self.a + v + carry
            self.set_flag(self.C, res > 0xFF)
            self.set_flag(self.V, (~(self.a ^ v) & (self.a ^ res) & 0x80) != 0)
            self.a = res & 0xFF; self.update_zn(self.a)
        elif op in (0x29,0x25,0x35,0x2D,0x3D,0x39,0x21,0x31):  # AND
            if   op == 0x29: v,_,_= self.fetch_imm(); c=2
            elif op == 0x25: v,_,_= self.fetch_zp();  c=3
            elif op == 0x35: v,_,_= self.fetch_zpx(); c=4
            elif op == 0x2D: v,_,_= self.fetch_abs(); c=4
            elif op == 0x3D: v,_,x= self.fetch_absx(); c=4 + (1 if x else 0)
            elif op == 0x39: v,_,x= self.fetch_absy(); c=4 + (1 if x else 0)
            elif op == 0x21: v,_,_= self.fetch_indx(); c=6
            elif op == 0x31: v,_,x= self.fetch_indy(); c=5 + (1 if x else 0)
            self.a = self.a & v; self.update_zn(self.a)
        elif op in (0x09,0x05,0x15,0x0D,0x1D,0x19,0x01,0x11):  # ORA
            if   op == 0x09: v,_,_= self.fetch_imm(); c=2
            elif op == 0x05: v,_,_= self.fetch_zp();  c=3
            elif op == 0x15: v,_,_= self.fetch_zpx(); c=4
            elif op == 0x0D: v,_,_= self.fetch_abs(); c=4
            elif op == 0x1D: v,_,x= self.fetch_absx(); c=4 + (1 if x else 0)
            elif op == 0x19: v,_,x= self.fetch_absy(); c=4 + (1 if x else 0)
            elif op == 0x01: v,_,_= self.fetch_indx(); c=6
            elif op == 0x11: v,_,x= self.fetch_indy(); c=5 + (1 if x else 0)
            self.a = self.a | v; self.update_zn(self.a)
        elif op in (0x49,0x45,0x55,0x4D,0x5D,0x59,0x41,0x51):  # EOR
            if   op == 0x49: v,_,_= self.fetch_imm(); c=2
            elif op == 0x45: v,_,_= self.fetch_zp();  c=3
            elif op == 0x55: v,_,_= self.fetch_zpx(); c=4
            elif op == 0x4D: v,_,_= self.fetch_abs(); c=4
            elif op == 0x5D: v,_,x= self.fetch_absx(); c=4 + (1 if x else 0)
            elif op == 0x59: v,_,x= self.fetch_absy(); c=4 + (1 if x else 0)
            elif op == 0x41: v,_,_= self.fetch_indx(); c=6
            elif op == 0x51: v,_,x= self.fetch_indy(); c=5 + (1 if x else 0)
            self.a = self.a ^ v; self.update_zn(self.a)
        elif op in (0xC9,0xC5,0xD5,0xCD,0xDD,0xD9,0xC1,0xD1):  # CMP
            if   op == 0xC9: v,_,_= self.fetch_imm(); c=2
            elif op == 0xC5: v,_,_= self.fetch_zp();  c=3
            elif op == 0xD5: v,_,_= self.fetch_zpx(); c=4
            elif op == 0xCD: v,_,_= self.fetch_abs(); c=4
            elif op == 0xDD: v,_,x= self.fetch_absx(); c=4 + (1 if x else 0)
            elif op == 0xD9: v,_,x= self.fetch_absy(); c=4 + (1 if x else 0)
            elif op == 0xC1: v,_,_= self.fetch_indx(); c=6
            elif op == 0xD1: v,_,x= self.fetch_indy(); c=5 + (1 if x else 0)
            t = (self.a - v) & 0x1FF
            self.set_flag(self.C, self.a >= v); self.set_flag(self.Z, (t & 0xFF)==0); self.set_flag(self.N, (t & 0x80)!=0)
        elif op in (0xE0,0xE4,0xEC):  # CPX
            if   op == 0xE0: v,_,_= self.fetch_imm(); c=2
            elif op == 0xE4: v,_,_= self.fetch_zp();  c=3
            elif op == 0xEC: v,_,_= self.fetch_abs(); c=4
            t = (self.x - v) & 0x1FF
            self.set_flag(self.C, self.x >= v); self.set_flag(self.Z, (t & 0xFF)==0); self.set_flag(self.N, (t & 0x80)!=0)
        elif op in (0xC0,0xC4,0xCC):  # CPY
            if   op == 0xC0: v,_,_= self.fetch_imm(); c=2
            elif op == 0xC4: v,_,_= self.fetch_zp();  c=3
            elif op == 0xCC: v,_,_= self.fetch_abs(); c=4
            t = (self.y - v) & 0x1FF
            self.set_flag(self.C, self.y >= v); self.set_flag(self.Z, (t & 0xFF)==0); self.set_flag(self.N, (t & 0x80)!=0)
        elif op in (0x24,0x2C):  # BIT zp/abs
            if op == 0x24: v,_,_= self.fetch_zp(); c=3
            else:          v,_,_= self.fetch_abs(); c=4
            self.set_flag(self.Z, (self.a & v)==0)
            self.set_flag(self.V, (v & 0x40)!=0)
            self.set_flag(self.N, (v & 0x80)!=0)

        # --- INC/DEC & Shifts (memory) ---
        elif op in (0xE6,0xF6,0xEE,0xFE):  # INC
            if   op == 0xE6: v,a,_= self.fetch_zp();  c=5
            elif op == 0xF6: v,a,_= self.fetch_zpx(); c=6
            elif op == 0xEE: v,a,_= self.fetch_abs(); c=6
            elif op == 0xFE: v,a,_= self.fetch_absx(); c=7
            v = (v + 1) & 0xFF; self.write(a, v); self.update_zn(v)
        elif op in (0xC6,0xD6,0xCE,0xDE):  # DEC
            if   op == 0xC6: v,a,_= self.fetch_zp();  c=5
            elif op == 0xD6: v,a,_= self.fetch_zpx(); c=6
            elif op == 0xCE: v,a,_= self.fetch_abs(); c=6
            elif op == 0xDE: v,a,_= self.fetch_absx(); c=7
            v = (v - 1) & 0xFF; self.write(a, v); self.update_zn(v)
        elif op in (0x06,0x16,0x0E,0x1E):  # ASL mem
            if   op == 0x06: v,a,_= self.fetch_zp();  c=5
            elif op == 0x16: v,a,_= self.fetch_zpx(); c=6
            elif op == 0x0E: v,a,_= self.fetch_abs(); c=6
            elif op == 0x1E: v,a,_= self.fetch_absx(); c=7
            self.set_flag(self.C, (v & 0x80)!=0); v=(v<<1)&0xFF; self.write(a,v); self.update_zn(v)
        elif op in (0x46,0x56,0x4E,0x5E):  # LSR mem
            if   op == 0x46: v,a,_= self.fetch_zp();  c=5
            elif op == 0x56: v,a,_= self.fetch_zpx(); c=6
            elif op == 0x4E: v,a,_= self.fetch_abs(); c=6
            elif op == 0x5E: v,a,_= self.fetch_absx(); c=7
            self.set_flag(self.C, (v & 1)!=0); v=(v>>1)&0xFF; self.write(a,v); self.update_zn(v)
        elif op in (0x26,0x36,0x2E,0x3E):  # ROL mem
            if   op == 0x26: v,a,_= self.fetch_zp();  c=5
            elif op == 0x36: v,a,_= self.fetch_zpx(); c=6
            elif op == 0x2E: v,a,_= self.fetch_abs(); c=6
            elif op == 0x3E: v,a,_= self.fetch_absx(); c=7
            cary=self.get_flag(self.C); self.set_flag(self.C,(v&0x80)!=0); v=((v<<1)|cary)&0xFF; self.write(a,v); self.update_zn(v)
        elif op in (0x66,0x76,0x6E,0x7E):  # ROR mem
            if   op == 0x66: v,a,_= self.fetch_zp();  c=5
            elif op == 0x76: v,a,_= self.fetch_zpx(); c=6
            elif op == 0x6E: v,a,_= self.fetch_abs(); c=6
            elif op == 0x7E: v,a,_= self.fetch_absx(); c=7
            cary=self.get_flag(self.C); self.set_flag(self.C,(v&1)!=0); v=((cary<<7)|(v>>1))&0xFF; self.write(a,v); self.update_zn(v)

        else:
            # Fallback NOP for unimplemented/illegal opcodes (keeps many simple ROMs running)
            c = 2

        self.cycles += c
        return c

# ────────────────────────────────────────────────────────────────────────────────────
# PPU
# ────────────────────────────────────────────────────────────────────────────────────

class PPU:
    def __init__(self, nes: 'NESBackend'):
        self.nes = nes
        self.palette_ram = bytearray(0x20)  # 0x3F00-0x3F1F
        self.oam = bytearray(0x100)         # 256 bytes
        self.vram = bytearray(0x800)        # 2KB nametable RAM (mirroring applied)
        self.framebuffer = np.zeros((240,256,3), dtype=np.uint8)

        # PPU registers/state
        self.ppuctrl = 0
        self.ppumask = 0
        self.ppustatus = 0
        self.oamaddr = 0
        self.v = 0               # current VRAM address (15-bit)
        self.t = 0               # temporary VRAM address (15-bit)
        self.x = 0               # fine X scroll (3-bit)
        self.w = 0               # first/second write toggle
        self.scanline = 0
        self.cycle = 0

        # Mirroring mode: 'H' or 'V'
        self.mirroring = 'H'

        # CHR access via mapper
        self.bg_pattern_table = 0  # 0 or 0x1000 (bit 4 of PPUCTRL)
        self.sprite_pattern_table = 0  # 0 or 0x1000 (bit 3 of PPUCTRL); only used for 8x8 sprites here

    def set_mirroring(self, mode: str):
        self.mirroring = mode

    def load_chr(self, chr_data: bytes):
        # handled by mapper; no local copy required
        pass

    # --- Register I/O ---
    def read_reg(self, reg: int) -> int:
        r = reg & 7
        if r == 2:  # PPUSTATUS
            val = self.ppustatus
            self.ppustatus &= ~0x80  # clear VBlank
            self.w = 0
            return val
        elif r == 4:  # OAMDATA
            return self.oam[self.oamaddr]
        elif r == 7:  # PPUDATA
            # buffered read for <0x3F00; direct for palette
            if (self.v & 0x3FFF) < 0x3F00:
                val = self.ppu_read(self.v)
                ret = getattr(self, '_read_buffer', 0)
                self._read_buffer = val
                self.v = (self.v + (32 if (self.ppuctrl & 0x04) else 1)) & 0x7FFF
                return ret
            else:
                ret = self.ppu_read(self.v)
                self.v = (self.v + (32 if (self.ppuctrl & 0x04) else 1)) & 0x7FFF
                return ret
        else:
            return 0

    def write_reg(self, reg: int, val: int):
        r = reg & 7
        if r == 0:  # PPUCTRL
            self.ppuctrl = val & 0xFF
            self.t = (self.t & 0x73FF) | ((val & 0x03) << 10)
            self.bg_pattern_table = 0x1000 if (val & 0x10) else 0x0000
            self.sprite_pattern_table = 0x1000 if (val & 0x08) else 0x0000
        elif r == 1:  # PPUMASK
            self.ppumask = val & 0xFF
        elif r == 2:  # PPUSTATUS (read-only)
            pass
        elif r == 3:  # OAMADDR
            self.oamaddr = val & 0xFF
        elif r == 4:  # OAMDATA
            self.oam[self.oamaddr] = val & 0xFF
            self.oamaddr = (self.oamaddr + 1) & 0xFF
        elif r == 5:  # PPUSCROLL
            if self.w == 0:
                self.x = val & 0x07
                self.t = (self.t & 0x7FE0) | ((val & 0xF8) >> 3)
                self.w = 1
            else:
                self.t = (self.t & 0x0C1F) | ((val & 0x07) << 12) | ((val & 0xF8) << 2)
                self.w = 0
        elif r == 6:  # PPUADDR
            if self.w == 0:
                self.t = (self.t & 0x00FF) | ((val & 0x3F) << 8)
                self.w = 1
            else:
                self.t = (self.t & 0x7F00) | val
                self.v = self.t
                self.w = 0
        elif r == 7:  # PPUDATA
            self.ppu_write(self.v, val & 0xFF)
            self.v = (self.v + (32 if (self.ppuctrl & 0x04) else 1)) & 0x7FFF

    # --- VRAM access (with mirroring) ---
    def _mirror_nt_addr(self, addr: int) -> int:
        # Map 0x2000-0x2FFF to 2KB VRAM using mirroring
        a = (addr - 0x2000) & 0x0FFF
        table = a // 0x400  # 0..3
        offset = a % 0x400
        if self.mirroring == 'V':
            # NT0,NT2 are unique; NT1 mirrors NT0; NT3 mirrors NT2
            if table in (0,1): base = 0x000
            else: base = 0x400
        else:
            # Horizontal: NT0,NT1 unique; NT2 mirrors NT0; NT3 mirrors NT1
            if table in (0,2): base = 0x000
            else: base = 0x400
        return (base + offset) & 0x7FF

    def ppu_read(self, addr: int) -> int:
        a = addr & 0x3FFF
        if a < 0x2000:
            return self.nes.mapper.ppu_read(a)
        elif a < 0x3F00:
            return self.vram[self._mirror_nt_addr(a)]
        elif a < 0x4000:
            idx = a & 0x1F
            if idx in (0x10,0x14,0x18,0x1C): idx -= 0x10  # mirrors
            return self.palette_ram[idx]
        return 0

    def ppu_write(self, addr: int, val: int):
        a = addr & 0x3FFF
        v = val & 0xFF
        if a < 0x2000:
            self.nes.mapper.ppu_write(a, v)
        elif a < 0x3F00:
            self.vram[self._mirror_nt_addr(a)] = v
        elif a < 0x4000:
            idx = a & 0x1F
            if idx in (0x10,0x14,0x18,0x1C): idx -= 0x10
            self.palette_ram[idx] = v

    def do_oam_dma(self, page: int):
        start = (page & 0xFF) << 8
        for i in range(256):
            self.oam[(self.oamaddr + i) & 0xFF] = self.nes.cpu.read(start + i)

    # --- Timing (very simplified) ---
    def step(self, cpu_cycles: int):
        # Advance PPU ~3x CPU
        self.cycle += (cpu_cycles * 3)
        while self.cycle >= 341:
            self.cycle -= 341
            self.scanline += 1
            if self.scanline == 241:
                # Enter VBlank
                self.ppustatus |= 0x80
                if self.ppuctrl & 0x80:
                    self.nes.cpu.nmi()
            elif self.scanline >= 262:
                # End of frame
                self.scanline = 0
                self.ppustatus &= ~0x80  # clear VBlank
                # Pre-render scanline: clear sprite 0 hit, overflow if used (not implemented)

    # --- Rendering (per-frame software renderer) ---
    def render_frame(self) -> np.ndarray:
        # If background/sprites disabled in PPUMASK, we still show picture for convenience
        bg_enable = (self.ppumask & 0x08) != 0
        spr_enable = (self.ppumask & 0x10) != 0

        # Resolve scroll from v register / fine x
        scroll_x = ((self.v & 0x001F) << 3) | (self.x & 0x07)
        scroll_y = (((self.v & 0x03E0) >> 5) << 3) | ((self.v & 0x7000) >> 12)

        # --- Render Background ---
        fb = self.framebuffer
        fb[:, :] = NES_PALETTE[self.palette_ram[0] & 0x3F]  # universal bg

        name_table_base = 0x2000 | (self.v & 0x0C00)
        attr_base = name_table_base + 0x03C0
        pattern_base = self.bg_pattern_table

        # Draw 32x30 tiles
        for ty in range(30):   # tile rows
            for tx in range(32):  # tile columns
                nt_x = (tx + ((scroll_x // 8) % 32)) % 32
                nt_y = (ty + ((scroll_y // 8) % 30)) % 30
                nt_addr = name_table_base + nt_y * 32 + nt_x
                tile_index = self.ppu_read(nt_addr)

                # Attribute: 4x4 tile attribute table; select upper bits of palette
                at_x = nt_x // 4
                at_y = nt_y // 4
                at_addr = attr_base + at_y * 8 + at_x
                at = self.ppu_read(at_addr)
                # determine quadrant
                qx = (nt_x % 4) // 2
                qy = (nt_y % 4) // 2
                shift = (qy * 2 + qx) * 2
                palette_hi = (at >> shift) & 0x03

                # Fetch tile pattern rows
                tile_base = pattern_base + tile_index * 16
                # Render 8x8 pixels
                for row in range(8):
                    lo_ = self.nes.mapper.ppu_read(tile_base + row)
                    hi_ = self.nes.mapper.ppu_read(tile_base + row + 8)
                    py = (ty * 8 + row) - (scroll_y % 8)
                    if py < 0 or py >= 240: continue
                    # Compose row pixels
                    for col in range(8):
                        bit = 7 - col
                        p = ((lo_ >> bit) & 1) | (((hi_ >> bit) & 1) << 1)
                        if p == 0:  # background color
                            continue
                        px = (tx * 8 + col) - (scroll_x % 8)
                        if px < 0 or px >= 256: continue
                        pal_idx = 0x3F00 + (palette_hi << 2) + p
                        color = NES_PALETTE[self.ppu_read(pal_idx) & 0x3F]
                        fb[py, px] = color

        # --- Render Sprites (8x8 only) ---
        if spr_enable:
            for i in range(63, -1, -1):  # draw in reverse order for priority
                y = self.oam[i*4 + 0] + 1  # sprites are offset by 1
                tile = self.oam[i*4 + 1]
                attr = self.oam[i*4 + 2]
                x = self.oam[i*4 + 3]
                flip_h = (attr & 0x40) != 0
                flip_v = (attr & 0x80) != 0
                pal = (attr & 0x03)
                priority_back = (attr & 0x20) != 0  # if true, behind background
                # Only 8x8 sprites in this build
                pattern_base = self.sprite_pattern_table

                for row in range(8):
                    sy = (7 - row) if flip_v else row
                    lo_ = self.nes.mapper.ppu_read(pattern_base + tile * 16 + sy)
                    hi_ = self.nes.mapper.ppu_read(pattern_base + tile * 16 + sy + 8)
                    py = y + row
                    if py < 0 or py >= 240: continue
                    for col in range(8):
                        sx = (7 - col) if flip_h else col
                        bit = 7 - sx
                        p = ((lo_ >> bit) & 1) | (((hi_ >> bit) & 1) << 1)
                        if p == 0:
                            continue
                        px = x + col
                        if px < 0 or px >= 256: continue
                        if priority_back and (fb[py, px] != NES_PALETTE[self.palette_ram[0] & 0x3F]).any():
                            # behind non-zero background
                            continue
                        pal_idx = 0x3F10 + (pal << 2) + p  # sprite palettes
                        color = NES_PALETTE[self.ppu_read(pal_idx) & 0x3F]
                        fb[py, px] = color

        return fb

# ────────────────────────────────────────────────────────────────────────────────────
# APU (stub)
# ────────────────────────────────────────────────────────────────────────────────────

class APU:
    def __init__(self):
        pass
    def step(self): pass
    def write_reg(self, addr: int, val: int): pass
    def read_reg(self, addr: int) -> int: return 0

# ────────────────────────────────────────────────────────────────────────────────────
# NES Backend
# ────────────────────────────────────────────────────────────────────────────────────

class NESBackend:
    def __init__(self):
        self.cpu = CPU(self)
        self.ppu = PPU(self)
        self.apu = APU()
        self.mapper: BaseMapper = None  # type: ignore
        self.ram = bytearray(0x800)
        self.sram = bytearray(0x2000)  # 8KB battery RAM
        self.cycles = 0
        self.frame_count = 0
        self.running = False
        self.controller1 = Controller(self)
        self.controller2 = Controller(self)

        self.input_state = {'A': False, 'B': False, 'SELECT': False, 'START': False, 'UP': False, 'DOWN': False, 'LEFT': False, 'RIGHT': False}
        self.key_map = {'z': 'A','x':'B','Return':'START','Shift_R':'SELECT','Up':'UP','Down':'DOWN','Left':'LEFT','Right':'RIGHT'}

    def load_rom(self, path: str) -> bool:
        try:
            with open(path, 'rb') as f:
                header = f.read(16)
                if header[0:4] != b'NES\x1A':
                    messagebox.showerror("Load Error", "Not a valid iNES file.")
                    return False

                prg_count = header[4]
                chr_count = header[5]
                flag6 = header[6]
                flag7 = header[7]

                has_trainer = (flag6 & 0x04) != 0
                if has_trainer:
                    f.read(512)

                prg_size = prg_count * 0x4000
                chr_size = chr_count * 0x2000
                prg_data = f.read(prg_size)
                chr_data = f.read(chr_size) if chr_size else bytes()

                mapper_id = ((flag7 & 0xF0) | (flag6 >> 4)) & 0xFF
                mirroring = 'V' if (flag6 & 0x01) else 'H'
                chr_is_ram = (chr_size == 0)

                self.mapper = make_mapper(self, mapper_id, prg_data, chr_data, mirroring, chr_is_ram)
                self.ppu.set_mirroring(mirroring)

                self.ram[:] = b'\x00' * len(self.ram)
                self.sram[:] = b'\x00' * len(self.sram)
                self.cpu.reset()
                self.running = True

                print(f"Loaded ROM: PRG={prg_size//1024}KB, CHR={'RAM' if chr_is_ram else str(chr_size//1024)+'KB'}, Mapper={mapper_id}, Mirror={mirroring}")
                return True
        except Exception as e:
            messagebox.showerror("Load Error", f"Failed to load ROM: {e}")
            self.running = False
            return False

    def step_frame(self) -> np.ndarray:
        if not self.running:
            return self.ppu.framebuffer

        self.cycles = 0
        while self.cycles < CPU_CYCLES_PER_FRAME:
            cyc = self.cpu.step()
            self.ppu.step(cyc)
            self.apu.step()
            self.cycles += cyc

        self.frame_count += 1
        return self.ppu.render_frame()

    def inject_cheat(self, addr: int, value: int):
        if 0 <= addr < 0x800:
            self.ram[addr] = value & 0xFF
            print(f"Cheat: RAM[0x{addr:04X}] = 0x{value:02X}")

    def debug_ram(self, addr: int) -> int:
        if addr < 0x2000: return self.ram[addr & 0x7FF]
        if 0x6000 <= addr <= 0x7FFF: return self.sram[addr-0x6000]
        return self.cpu.read(addr)

    def set_key_state(self, key: str, pressed: bool):
        if key in self.key_map:
            button = self.key_map[key]
            self.input_state[button] = pressed
            self.controller1.set_button(button, pressed)

# ────────────────────────────────────────────────────────────────────────────────────
# GUI
# ────────────────────────────────────────────────────────────────────────────────────

class GUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Cat's FCEUX 0.2")
        self.geometry("512x480")  # 256x240 scaled 2x
        self.resizable(False, False)

        self.nes = NESBackend()

        self.create_menu()

        # Canvas for video
        self.canvas = tk.Canvas(self, width=512, height=480, bg="black", highlightthickness=0)
        self.canvas.pack()

        # Framebuffer image
        self.image = Image.new('RGB', (256, 240))
        self.photo_image = ImageTk.PhotoImage(self.image.resize((512, 480), Image.NEAREST))
        self.image_on_canvas = self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo_image)

        # Bind keys
        self.bind("<KeyPress>", self.on_key_press)
        self.bind("<KeyRelease>", self.on_key_release)

        self.paused = False
        self.after(16, self.update_game)

    def create_menu(self):
        menu_bar = Menu(self)
        self.config(menu=menu_bar)

        file_menu = Menu(menu_bar, tearoff=0)
        file_menu.add_command(label="Open ROM...", command=self.open_rom)
        file_menu.add_separator()
        file_menu.add_command(label="Reset", command=self.reset_rom)
        file_menu.add_command(label="Pause/Resume", command=self.toggle_pause)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.quit)
        menu_bar.add_cascade(label="File", menu=file_menu)

        tools_menu = Menu(menu_bar, tearoff=0)
        tools_menu.add_command(label="Cheats...", command=self.open_cheats)
        tools_menu.add_command(label="Debug...", command=self.open_debug)
        menu_bar.add_cascade(label="Tools", menu=tools_menu)

        help_menu = Menu(menu_bar, tearoff=0)
        help_menu.add_command(label="About...", command=self.show_about)
        menu_bar.add_cascade(label="Help", menu=help_menu)

    def open_rom(self):
        path = filedialog.askopenfilename(
            title="Open NES ROM",
            filetypes=(("NES ROMs", "*.nes"), ("All Files", "*.*"))
        )
        if path:
            if self.nes.load_rom(path):
                self.paused = False

    def reset_rom(self):
        if self.nes.mapper:
            self.nes.cpu.reset()

    def toggle_pause(self):
        self.paused = not self.paused

    def open_cheats(self):
        cheat_code = simpledialog.askstring("Inject Cheat", "Enter cheat (e.g., 0400:FF):")
        if cheat_code:
            try:
                addr_str, val_str = cheat_code.split(':')
                addr = int(addr_str, 16)
                value = int(val_str, 16)
                self.nes.inject_cheat(addr, value)
            except Exception as e:
                messagebox.showerror("Cheat Error", f"Invalid cheat format. Use ADDR:VAL (hex).\n{e}")

    def open_debug(self):
        addr_str = simpledialog.askstring("Debug RAM/Bus", "Enter address (hex):")
        if addr_str:
            try:
                addr = int(addr_str, 16)
                value = self.nes.debug_ram(addr)
                messagebox.showinfo("Debug", f"Value at 0x{addr:04X}: 0x{value:02X} ({value})")
            except Exception as e:
                messagebox.showerror("Debug Error", f"Invalid address.\n{e}")

    def show_about(self):
        messagebox.showinfo("About",
            "Cat's FCEUX 0.2\n"
            "Homebrew-focused single-file NES emulator\n"
            "[C] 2025 Samsoft / Cat-san\n"
            "Mappers: NROM(0), UxROM(2), CNROM(3)\n"
            "PPU: BG+Sprites, palettes, mirroring\n"
            "APU: stub (no audio)"
        )

    def on_key_press(self, event):
        self.nes.set_key_state(event.keysym, True)

    def on_key_release(self, event):
        self.nes.set_key_state(event.keysym, False)

    def update_game(self):
        if not self.paused:
            frame = self.nes.step_frame()
            # Update screen
            self.image = Image.fromarray(frame, 'RGB')
            self.photo_image = ImageTk.PhotoImage(self.image.resize((512, 480), Image.NEAREST))
            self.canvas.itemconfig(self.image_on_canvas, image=self.photo_image)
        self.after(16, self.update_game)

# ────────────────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = GUI()
    app.mainloop()
