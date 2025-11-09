# program.py - Cat's FCEUX 0.1.2 (Homebrew NES Frontend)
# [C] 2025 Samsoft / Cat-san
#
# Teaching / demo mock of a FCEUX-style frontend shell.
# Safe for homebrew testing and research visualization.
# Not a commercial emulator core.

# ──────────────────────────────
# Imports
# ──────────────────────────────
import os
import time
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import numpy as np
from PIL import Image, ImageTk
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, List, Set

# ──────────────────────────────
# Constants
# ──────────────────────────────
APP_TITLE = "Cat’s FCEUX 0.1.2"
BASE_WIDTH, BASE_HEIGHT = 256, 240
DEFAULT_SCALE = 2

# ──────────────────────────────
# Basic Enums / Mapper
# ──────────────────────────────
class MirrorType(Enum):
    HORIZONTAL = 1
    VERTICAL = 2
    FOUR_SCREEN = 3
    SINGLE_SCREEN_LOWER = 4
    SINGLE_SCREEN_UPPER = 5


class Mapper0:
    """NROM Mapper"""
    def __init__(self, cart): self.cart = cart
    def prg_read(self, addr):
        addr -= 0x8000
        if self.cart.prg_banks == 1:
            addr %= 0x4000
        return self.cart.prg_rom[addr]
    def prg_write(self, addr, val): pass
    def chr_read(self, addr):
        return self.cart.chr_rom[addr] if not self.cart.has_chr_ram else self.cart.chr_ram[addr]
    def chr_write(self, addr, val):
        if self.cart.has_chr_ram:
            self.cart.chr_ram[addr] = val & 0xFF


# ──────────────────────────────
# Cartridge
# ──────────────────────────────
class Cartridge:
    def __init__(self, data: bytes):
        if data[0:4] != b"NES\x1A":
            raise ValueError("Invalid NES ROM header")
        prg_banks = data[4]; chr_banks = data[5]; flag6 = data[6]; flag7 = data[7]
        self.mapper_type = (flag7 & 0xF0) | (flag6 >> 4)
        self.mirroring = MirrorType.FOUR_SCREEN if flag6 & 0x08 else (
            MirrorType.VERTICAL if flag6 & 0x01 else MirrorType.HORIZONTAL
        )
        prg_size = prg_banks * 0x4000; chr_size = chr_banks * 0x2000
        offset = 16 + (512 if flag6 & 0x04 else 0)
        self.prg_rom = data[offset:offset + prg_size]
        chr_start = offset + prg_size
        self.chr_rom = data[chr_start:chr_start + chr_size] if chr_size else bytes()
        self.prg_banks, self.chr_banks = prg_banks, chr_banks
        self.has_chr_ram = chr_banks == 0
        self.chr_ram = [0]*0x2000 if self.has_chr_ram else []


# ──────────────────────────────
# Memory / CPU / PPU
# ──────────────────────────────
class Memory:
    def __init__(self, cart=None):
        self.ram = [0]*0x800; self.palette_ram = [0]*0x20
        self.cart = cart; self.mapper = Mapper0(cart) if cart else None
    def read(self, addr):
        addr &= 0xFFFF
        if addr < 0x2000: return self.ram[addr % 0x800]
        if 0x8000 <= addr < 0x10000 and self.mapper: return self.mapper.prg_read(addr)
        return 0
    def write(self, addr, val):
        addr &= 0xFFFF; val &= 0xFF
        if addr < 0x2000: self.ram[addr % 0x800] = val
        elif 0x8000 <= addr < 0x10000 and self.mapper: self.mapper.prg_write(addr, val)


class CPU:
    def __init__(self, mem):
        self.memory = mem; self.pc = 0x8000; self.sp = 0xFD
        self.a = self.x = self.y = 0; self.flags = 0x24; self.cycles = 0
        self.last_opcode = 0; self.last_pc = self.pc; self.listeners=[]
    def reset(self):
        low = self.memory.read(0xFFFC); high = self.memory.read(0xFFFD)
        self.pc = ((high << 8) | low) if (low or high) else 0x8000
        self.sp, self.a, self.x, self.y, self.flags, self.cycles = 0xFD, 0, 0, 0, 0x24, 0
    def step(self):
        self.last_pc = self.pc
        op = self.memory.read(self.pc)
        self.pc = (self.pc + 1) & 0xFFFF
        self.last_opcode = op; self.cycles += 2
        for f in self.listeners:
            try: f(self, op)
            except: pass
    def exec_instructions(self, count): [self.step() for _ in range(count)]


class PPU:
    def __init__(self):
        self.framebuffer = np.zeros((BASE_HEIGHT, BASE_WIDTH, 3), np.uint8)
    def get_framebuffer(self): return self.framebuffer.copy()


# ──────────────────────────────
# Emulator Core
# ──────────────────────────────
class Emulator:
    def __init__(self, path):
        with open(path, "rb") as f: data = f.read()
        self.path = path; self.cart = Cartridge(data)
        self.memory = Memory(self.cart); self.cpu = CPU(self.memory)
        self.ppu = PPU(); self.cpu.reset()
        self.instructions_per_frame = 2000
    def run_frame(self): self.cpu.exec_instructions(self.instructions_per_frame)
    def get_frame(self): return self.ppu.get_framebuffer()


# ──────────────────────────────
# GUI Frontend
# ──────────────────────────────
class CatsFCEUXApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.configure(bg="#111")
        self.scale = DEFAULT_SCALE; self.running = False
        self.emu: Optional[Emulator] = None
        self.speed = 1.0; self.limit_fps = True
        self.trace_log=[]; self.frames=0; self.fps=0; self.last_time=time.time()
        self._build_ui(); self._bind_hotkeys()

    def _build_ui(self):
        menubar = tk.Menu(self.root, bg="#222", fg="white")
        self.root.config(menu=menubar)
        file_menu = tk.Menu(menubar, tearoff=0, bg="#222", fg="white")
        file_menu.add_command(label="Open ROM", command=self.open_rom)
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        emu_menu = tk.Menu(menubar, tearoff=0, bg="#222", fg="white")
        emu_menu.add_command(label="Run / Pause", command=self.toggle_run)
        menubar.add_cascade(label="Emulation", menu=emu_menu)

        help_menu = tk.Menu(menubar, tearoff=0, bg="#222", fg="white")
        help_menu.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        # Single canvas
        self.canvas = tk.Canvas(
            self.root, bg="black",
            width=BASE_WIDTH*self.scale, height=BASE_HEIGHT*self.scale+40,
            highlightthickness=0
        )
        self.canvas.pack(fill="both", expand=True)
        self.status = tk.StringVar(value="No ROM loaded")
        ttk.Label(self.root, textvariable=self.status, anchor="w").pack(fill="x")

    def _bind_hotkeys(self):
        self.root.bind("<space>", lambda e: self.toggle_run())
        self.root.bind("<Control-o>", lambda e: self.open_rom())

    def open_rom(self):
        path = filedialog.askopenfilename(filetypes=[("NES ROM", "*.nes")])
        if not path: return
        try:
            self.emu = Emulator(path)
            self.status.set(f"Loaded: {os.path.basename(path)} | Mapper {self.emu.cart.mapper_type}")
            self.update_canvas(force=True)
        except Exception as e:
            messagebox.showerror("Load Error", str(e))

    def toggle_run(self):
        if not self.emu:
            self.open_rom()
            if not self.emu:
                return
        self.running = not self.running
        if self.running: self.run_loop()

    def show_about(self):
        messagebox.showinfo("About",
            "Cat’s FCEUX 0.1.2\n"
            "Homebrew educational frontend for NES visualization.\n"
            "© 2025 Samsoft / Cat-san"
        )

    def run_loop(self):
        if not self.running or not self.emu: return
        self.emu.run_frame()
        self.update_canvas()
        now=time.time()
        if now-self.last_time>0.5:
            self.fps=self.frames/(now-self.last_time)
            self.frames=0; self.last_time=now
            self.status.set(f"Running • {self.fps:.1f} FPS")
        self.frames+=1
        delay = 16 if self.limit_fps else 1
        self.root.after(delay, self.run_loop)

    def update_canvas(self, force=False):
        self.canvas.delete("all")
        if not self.emu:
            self.canvas.create_text(
                (BASE_WIDTH*self.scale)//2,
                (BASE_HEIGHT*self.scale)//2,
                fill="gray",
                text="No ROM Loaded",
                font=("Consolas",16)
            )
            return

        frame = self.emu.get_frame()
        pil = Image.fromarray(frame).resize(
            (BASE_WIDTH*self.scale, BASE_HEIGHT*self.scale), Image.NEAREST
        )
        img = ImageTk.PhotoImage(pil)
        self.canvas.image = img
        self.canvas.create_image(0,0,anchor="nw",image=img)
        self.canvas.create_rectangle(
            0, BASE_HEIGHT*self.scale,
            BASE_WIDTH*self.scale, BASE_HEIGHT*self.scale+40,
            fill="#111", outline="#333"
        )
        cpu=self.emu.cpu
        hud=f"PC=${cpu.pc:04X}  OPCODE=${cpu.last_opcode:02X}  CYC={cpu.cycles}"
        self.canvas.create_text(6, BASE_HEIGHT*self.scale+20,
            text=hud, fill="#7CFC00", font=("Consolas",11), anchor="w"
        )

    def run(self):
        self.update_canvas(force=True)
        self.root.mainloop()


# ──────────────────────────────
# Run
# ──────────────────────────────
if __name__ == "__main__":
    CatsFCEUXApp().run()c
