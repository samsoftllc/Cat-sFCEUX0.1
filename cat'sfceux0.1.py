# Cat's FCEUX 0.1 - Fixed Canvas Edition (PhotoImage Blitter)
# [C] 2025 Samsoft - Shadow fork of FCEUX 0.1

import tkinter as tk
from tkinter import Menu, messagebox, filedialog, simpledialog
import struct
import numpy as np
from typing import Optional

# ───────────────────────────────────────────────
# NES Backend Skeleton
# ───────────────────────────────────────────────
class NESBackend:
    def __init__(self):
        self.cpu = CPU()
        self.ppu = PPU()
        self.apu = APU()
        self.mapper = Mapper(0)
        self.ram = bytearray(0x800)
        self.vram = bytearray(0x1000)
        self.rom_prg = None
        self.rom_chr = None
        self.cycles = 0
        self.frame_count = 0
        self.running = False
        self.input_state = {k: False for k in
                            ['A','B','SELECT','START','UP','DOWN','LEFT','RIGHT']}

    def load_rom(self, path: str) -> bool:
        try:
            with open(path, 'rb') as f:
                header = f.read(0x10)
                if header[0:4] != b'NES\x1A':
                    return False
                prg_size = header[4] * 0x4000
                chr_size = header[5] * 0x2000
                mapper_id = ((header[6] >> 4) | (header[7] & 0xF0))
                self.mapper = Mapper(mapper_id)
                self.rom_prg = f.read(prg_size)
                self.rom_chr = f.read(chr_size) if chr_size else bytearray(0x2000)
                self.cpu.reset(self.rom_prg, self.mapper)
                self.ppu.load_chr(self.rom_chr)
                return True
        except Exception as e:
            print("ROM load error:", e)
            return False

    def step_frame(self) -> np.ndarray:
        self.running = True
        target_cycles = 29781
        self.cycles = 0
        while self.cycles < target_cycles:
            self.cpu.step(self.ram, self.ppu, self.mapper, self.input_state)
            self.ppu.step(self.cycles % 3)
            self.apu.step()
            self.cycles += 1
        self.frame_count += 1
        return self.ppu.render_frame(self.vram)

    def inject_cheat(self, addr: int, value: int):
        if 0 <= addr < len(self.ram):
            self.ram[addr] = value

    def debug_ram(self, addr: int) -> int:
        return self.ram[addr] if addr < len(self.ram) else 0


# ───────────────────────────────────────────────
# CPU / PPU / APU / Mapper
# ───────────────────────────────────────────────
class CPU:
    def __init__(self):
        self.pc = 0x0000
        self.sp = 0xFD
        self.a = self.x = self.y = 0
        self.flags = 0x24
        self.cycles = 0

    def reset(self, prg: bytes, mapper):
        self.mapper = mapper
        self.mapper.prg_bank = prg
        # NES reset vector: bytes at 0x7FFC/0x7FFD in PRG
        if len(prg) >= 0x8000:
            self.pc = struct.unpack('<H', prg[-6:-4])[0]
        else:
            self.pc = 0x8000

    def step(self, ram, ppu, mapper, input_state):
        # minimal no-op loop
        opcode = self.fetch(ram, mapper)
        if opcode == 0xA9:  # LDA imm
            self.a = self.fetch(ram, mapper)
            self.cycles += 2
        else:
            self.cycles += 2

    def fetch(self, ram, mapper):
        val = mapper.read_prg(self.pc, ram)
        self.pc = (self.pc + 1) & 0xFFFF
        return val


class PPU:
    def __init__(self):
        self.scanline = 0
        self.cycle = 0
        self.ctrl = self.mask = self.status = 0
        self.chr = bytearray(0x2000)
        self.framebuffer = np.zeros((240, 256, 3), dtype=np.uint8)
        self.nmi = False

    def load_chr(self, chr_data: bytes):
        self.chr = bytearray(chr_data)

    def step(self, cpu_cycle: int):
        self.cycle += 1
        if self.cycle >= 341:
            self.cycle = 0
            self.scanline += 1
            if self.scanline >= 262:
                self.scanline = 0

    def render_frame(self, vram: bytearray) -> np.ndarray:
        # generate grayscale pattern as placeholder
        for y in range(240):
            shade = (y * 255) // 239
            self.framebuffer[y, :, :] = [shade, shade, shade]
        return self.framebuffer


class APU:
    def step(self): pass
    def read(self, reg: int) -> int: return 0


class Mapper:
    def __init__(self, id: int):
        self.id = id
        self.prg_bank = bytearray()

    def read_prg(self, addr: int, ram: bytearray) -> int:
        if not self.prg_bank:
            return ram[addr % len(ram)]
        offset = addr - 0x8000
        return self.prg_bank[offset % len(self.prg_bank)]


# ───────────────────────────────────────────────
# Tkinter Frontend (fixed)
# ───────────────────────────────────────────────
class CatsFCEUX:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Cat's FCEUX 0.1")
        self.root.geometry("800x600")
        self.root.configure(bg="black")

        self.nes = NESBackend()
        self.rom_path = None
        self.after_id = None
        self.paused = False

        menubar = Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open ROM", command=self.load_rom)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        options_menu = Menu(menubar, tearoff=0)
        options_menu.add_checkbutton(label="Pause", command=self.toggle_pause)
        menubar.add_cascade(label="Options", menu=options_menu)

        tools_menu = Menu(menubar, tearoff=0)
        tools_menu.add_command(label="Debugger", command=self.show_debugger)
        menubar.add_cascade(label="Tools", menu=tools_menu)

        help_menu = Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        # Canvas optimized with PhotoImage
        self.canvas = tk.Label(self.root, bg="black")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.photo = tk.PhotoImage(width=256, height=240)
        self.canvas.config(image=self.photo)

        self.root.bind("<Escape>", lambda e: self.root.quit())

    # ─── File / ROM ──────────────────────────────
    def load_rom(self):
        path = filedialog.askopenfilename(filetypes=[("NES ROM", "*.nes")])
        if path and self.nes.load_rom(path):
            self.rom_path = path
            messagebox.showinfo("Loaded", f"ROM loaded: {path.split('/')[-1]}")
            self.run_emulation()
        else:
            messagebox.showerror("Error", "Invalid or unreadable ROM file.")

    # ─── Emulation Loop ──────────────────────────
    def run_emulation(self):
        if not self.paused and self.rom_path:
            frame = self.nes.step_frame()
            # Update PhotoImage buffer
            rgb = (frame[:, :, 0] << 16) | (frame[:, :, 1] << 8) | frame[:, :, 2]
            hex_data = " ".join(f"#{r:06x}" for r in rgb.flatten())
            self.photo.put("{" + hex_data + "}", to=(0, 0))
            self.after_id = self.root.after(16, self.run_emulation)
        elif self.after_id:
            self.root.after_cancel(self.after_id)

    def toggle_pause(self):
        self.paused = not self.paused
        if not self.paused:
            self.run_emulation()

    def show_debugger(self):
        addr = simpledialog.askinteger("Debugger", "RAM Addr (hex):")
        if addr is not None:
            val = self.nes.debug_ram(addr)
            messagebox.showinfo("Debug", f"RAM[0x{addr:02X}] = 0x{val:02X}")

    def show_about(self):
        messagebox.showinfo(
            "About",
            "Cat's FCEUX 0.1\nMinimal Tkinter-based NES emulator frontend.\n"
            "CPU: 6502 stub | PPU: grayscale test | APU: muted.\n"
            "© Samsoft 2025"
        )

    def run(self):
        self.root.mainloop()


# ───────────────────────────────────────────────
if __name__ == "__main__":
    app = CatsFCEUX()
    app.run()
