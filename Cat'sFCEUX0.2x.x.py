import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import numpy as np
from PIL import Image, ImageTk
import sys
import os
import struct
from enum import Enum
from typing import Optional, List, Dict, Tuple

class MirrorType(Enum):
    HORIZONTAL = 1
    VERTICAL = 2
    FOUR_SCREEN = 3
    SINGLE_SCREEN_LOWER = 4
    SINGLE_SCREEN_UPPER = 5

class Mapper:
    def __init__(self, cartridge):
        self.cartridge = cartridge
    def prg_read(self, addr: int) -> int:
        addr -= 0x8000
        if self.cartridge.prg_banks == 1 and addr >= 0x4000:
            addr -= 0x4000
        return self.cartridge.prg_rom[addr]
    def prg_write(self, addr: int, value: int): pass
    def chr_read(self, addr: int) -> int: return self.cartridge.chr_rom[addr]
    def chr_write(self, addr: int, value: int): pass

class Cartridge:
    def __init__(self, rom_data: bytes):
        if rom_data[0:4] != b'NES\x1A':
            raise ValueError("Invalid NES ROM header")
        prg_banks = rom_data[4]; chr_banks = rom_data[5]
        flag6 = rom_data[6]; flag7 = rom_data[7]
        self.mapper_type = (flag6 >> 4) | (flag7 & 0xF0)
        if flag6 & 0x08:
            self.mirroring = MirrorType.FOUR_SCREEN
        else:
            self.mirroring = MirrorType.VERTICAL if flag6 & 0x01 else MirrorType.HORIZONTAL
        prg_size = prg_banks * 0x4000; chr_size = chr_banks * 0x2000
        offset = 16 + (512 if flag6 & 0x04 else 0)
        self.prg_rom = rom_data[offset:offset + prg_size]
        self.chr_rom = rom_data[offset + prg_size:offset + prg_size + chr_size]
        self.prg_banks = prg_banks; self.chr_banks = chr_banks

class Memory:
    def __init__(self, cartridge: Optional[Cartridge] = None):
        self.ram = [0] * 0x800
        self.vram = [0] * 0x1000
        self.palette_ram = [0] * 0x20
        self.oam = [0] * 0x100
        self.cartridge = cartridge
        self.mapper = Mapper(cartridge) if cartridge else None
        self.controller = None

    def mirror_vram_addr(self, addr: int) -> int:
        addr = addr & 0xFFF
        if self.cartridge.mirroring == MirrorType.VERTICAL:
            return addr & 0x7FF
        elif self.cartridge.mirroring == MirrorType.HORIZONTAL:
            return addr & 0xBFF
        elif self.cartridge.mirroring == MirrorType.FOUR_SCREEN:
            return addr
        return addr

    def read(self, addr: int) -> int:
        if 0x0000 <= addr < 0x2000:
            return self.ram[addr % 0x800]
        elif 0x8000 <= addr < 0x10000 and self.mapper:
            return self.mapper.prg_read(addr)
        return 0

    def write(self, addr: int, value: int):
        if 0x0000 <= addr < 0x2000:
            self.ram[addr % 0x800] = value
        elif 0x8000 <= addr < 0x10000 and self.mapper:
            self.mapper.prg_write(addr, value)

class CPU:
    def __init__(self, memory: Memory):
        self.memory = memory
        self.a = 0; self.x = 0; self.y = 0
        self.sp = 0xFD; self.pc = 0x8000
        self.flags = 0x24; self.cycles = 0
        self.nmi = False; self.irq = False
        self.opcodes = {0xEA: self.nop}
        self.cycle_table = [2] * 256

    def reset(self):
        self.pc = self.memory.read(0xFFFC) | (self.memory.read(0xFFFD) << 8)
        self.sp = 0xFD; self.a = 0; self.x = 0; self.y = 0; self.flags = 0x24

    def execute_instruction(self):
        if self.nmi:
            self.push(self.pc >> 8)
            self.push(self.pc & 0xFF)
            self.push(self.flags | 0x20)
            self.flags |= 0x04  # ← fixed operator
            self.pc = self.memory.read(0xFFFA) | (self.memory.read(0xFFFB) << 8)
            self.nmi = False
            self.cycles += 7
        opcode = self.memory.read(self.pc)
        self.pc += 1
        func = self.opcodes.get(opcode, self.nop)
        func(0, 0, 'imp')

    def push(self, value: int):
        self.memory.write(0x0100 + self.sp, value)
        self.sp = (self.sp - 1) & 0xFF

    def nop(self, v, a, m): pass

class PPU:
    def __init__(self, memory: Memory):
        self.memory = memory
        self.framebuffer = np.zeros((240, 256, 3), dtype=np.uint8)

    def read_vram(self, addr: int) -> int: return 0
    def write_vram(self, addr: int, value: int):
        if 0x3F00 <= addr < 0x4000:
            addr = addr & 0x1F
            if addr in (0x10, 0x14, 0x18, 0x1C):  # ← fixed
                addr -= 0x10
            self.memory.palette_ram[addr] = value
    def get_framebuffer(self): return self.framebuffer.copy()

class Controller:
    def __init__(self): self.buttons = 0
    def set_buttons(self, buttons: int): self.buttons = buttons

class APU:
    def __init__(self, memory: Memory): self.memory = memory
    def step(self): pass

class Emulator:
    def __init__(self, rom_path: str):
        with open(rom_path, 'rb') as f: rom_data = f.read()
        self.cartridge = Cartridge(rom_data)
        self.memory = Memory(self.cartridge)
        self.cpu = CPU(self.memory)
        self.ppu = PPU(self.memory)
        self.apu = APU(self.memory)
        self.controller = Controller()
        self.memory.controller = self.controller
        self.cpu.reset(); self.running = True

    def run_frame(self):
        self.cpu.execute_instruction()
    def set_controller_input(self, p, b): self.controller.set_buttons(b)
    def get_frame(self): return self.ppu.get_framebuffer()

class NESEmulator:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Cat's NES 1.0 with Enhanced Engine")
        self.root.geometry("1024x768")
        self.root.configure(bg='gray20')
        self.running = False; self.fullscreen_state = False
        self.emulator = None; self.rom_path = None; self.keys = set()

        menubar = tk.Menu(self.root, bg='gray20', fg='white', tearoff=0)
        self.root.config(menu=menubar)
        file_menu = tk.Menu(menubar, tearoff=0, bg='gray20', fg='white')
        file_menu.add_command(label="Load ROM", command=self.load_rom)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        emulation_menu = tk.Menu(menubar, tearoff=0, bg='gray20', fg='white')
        emulation_menu.add_command(label="Run/Pause", command=self.toggle_run)
        menubar.add_cascade(label="Emulation", menu=emulation_menu)

        toolbar = tk.Frame(self.root, bg='gray30', height=30)
        toolbar.pack(side=tk.TOP, fill=tk.X)
        tk.Button(toolbar, text="Load ROM", command=self.load_rom,
                  bg='gray40', fg='white').pack(side=tk.LEFT, padx=2)
        self.rom_var = tk.StringVar(value="No ROM loaded")
        self.rom_combo = ttk.Combobox(toolbar, textvariable=self.rom_var,
                                      state="readonly", width=40)
        self.rom_combo.pack(side=tk.LEFT, padx=2)
        self.run_button = tk.Button(toolbar, text="▶ Run", bg='green', fg='white',
                                    command=self.toggle_run)
        self.run_button.pack(side=tk.LEFT, padx=2)

        screen_frame = tk.Frame(self.root, bg='black')
        screen_frame.pack(expand=True, fill=tk.BOTH)
        self.screen = tk.Canvas(screen_frame, bg='black',
                                width=512, height=480, highlightthickness=0)
        self.screen.pack(expand=True)

        self.root.bind('<KeyPress>', self.key_press)
        self.root.bind('<KeyRelease>', self.key_release)

    def key_press(self, e):
        self.keys.add(e.keysym); self.update_controller()
    def key_release(self, e):
        if e.keysym in self.keys: self.keys.remove(e.keysym); self.update_controller()
    def update_controller(self):
        if not self.emulator: return
        b = 0
        if 's' in self.keys: b |= 0x80
        if 'a' in self.keys: b |= 0x40
        if 'space' in self.keys: b |= 0x20
        if 'Return' in self.keys: b |= 0x10
        if 'Up' in self.keys: b |= 0x08
        if 'Down' in self.keys: b |= 0x04
        if 'Left' in self.keys: b |= 0x02
        if 'Right' in self.keys: b |= 0x01
        self.emulator.set_controller_input(1, b)

    def load_rom(self):
        file = filedialog.askopenfilename(title="Load NES ROM",
                                          filetypes=[("NES ROMs", "*.nes")])
        if file:
            self.emulator = Emulator(file)
            self.rom_path = file
            self.rom_var.set(os.path.basename(file))
            messagebox.showinfo("ROM Loaded", f"Loaded ROM:\n{file}")

    def toggle_run(self):
        if not self.emulator:
            messagebox.showwarning("No ROM", "Please load a ROM first.")
            return
        self.running = not self.running
        self.run_button.config(text="❚❚ Pause" if self.running else "▶ Run",
                               bg='red' if self.running else 'green')
        if self.running: self.emulation_step()

    def emulation_step(self):
        if not self.running or not self.emulator: return
        self.emulator.run_frame()
        self.update_screen()
        self.root.after(16, self.emulation_step)

    def update_screen(self):
        if self.emulator:
            frame = self.emulator.get_frame()
            img = Image.fromarray(frame, 'RGB').resize((512, 480), Image.NEAREST)
            photo = ImageTk.PhotoImage(img)
            self.screen.delete("all")
            self.screen.image = photo           # store ref
            self.screen.create_image(0, 0, anchor=tk.NW, image=self.screen.image)  # stable

    def run(self): self.root.mainloop()

if __name__ == "__main__":
    NESEmulator().run()
