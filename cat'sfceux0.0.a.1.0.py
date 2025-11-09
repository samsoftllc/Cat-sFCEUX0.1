import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import numpy as np
from PIL import Image, ImageTk
import struct, os
from enum import Enum
from typing import Optional

class MirrorType(Enum):
    HORIZONTAL = 1
    VERTICAL = 2
    FOUR_SCREEN = 3
    SINGLE_SCREEN_LOWER = 4
    SINGLE_SCREEN_UPPER = 5

# ──────────────────────────────
# Mapper & Cartridge
# ──────────────────────────────
class Mapper:
    def __init__(self, cartridge): self.cartridge = cartridge
    def prg_read(self, addr: int) -> int:
        addr -= 0x8000
        # Safe mirroring for NROM-128
        if self.cartridge.prg_banks == 1:
            addr %= 0x4000
        else:
            addr %= len(self.cartridge.prg_rom)
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

# ──────────────────────────────
# Memory / CPU / PPU
# ──────────────────────────────
class Memory:
    def __init__(self, cartridge: Optional[Cartridge] = None):
        self.ram = [0]*0x800
        self.palette_ram = [0]*0x20
        self.cartridge = cartridge
        self.mapper = Mapper(cartridge) if cartridge else None
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
        self.a = self.x = self.y = 0
        self.sp = 0xFD; self.pc = 0x8000
        self.flags = 0x24; self.cycles = 0
        self.opcodes = {0xEA: self.nop}
        self.last_opcode = 0
    def reset(self):
        low = self.memory.read(0xFFFC)
        high = self.memory.read(0xFFFD)
        self.pc = (high << 8) | low if (low or high) else 0x8000
    def execute_instruction(self):
        opcode = self.memory.read(self.pc)
        self.pc = (self.pc + 1) & 0xFFFF
        self.last_opcode = opcode
        func = self.opcodes.get(opcode, self.nop)
        func(0, 0, 'imp')
        self.cycles += 2
    def nop(self, v,a,m): pass

class PPU:
    def __init__(self): self.framebuffer = np.zeros((240,256,3),dtype=np.uint8)
    def get_framebuffer(self): return self.framebuffer.copy()

# ──────────────────────────────
# Emulator core
# ──────────────────────────────
class Emulator:
    def __init__(self, rom_path: str):
        with open(rom_path, 'rb') as f: rom_data = f.read()
        self.cartridge = Cartridge(rom_data)
        self.memory = Memory(self.cartridge)
        self.cpu = CPU(self.memory)
        self.ppu = PPU()
        self.cpu.reset()
    def run_frame(self):
        self.cpu.execute_instruction()
    def get_frame(self): return self.ppu.get_framebuffer()

# ──────────────────────────────
# GUI / Unified Canvas
# ──────────────────────────────
class NESEmulator:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Cat's NES 1.1 — Unified Canvas")
        self.root.configure(bg='black')
        self.running = False
        self.emulator = None

        menubar = tk.Menu(self.root,bg='gray20',fg='white')
        self.root.config(menu=menubar)
        file_menu = tk.Menu(menubar,tearoff=0,bg='gray20',fg='white')
        file_menu.add_command(label="Load ROM",command=self.load_rom)
        file_menu.add_command(label="Exit",command=self.root.quit)
        menubar.add_cascade(label="File",menu=file_menu)
        emu_menu = tk.Menu(menubar,tearoff=0,bg='gray20',fg='white')
        emu_menu.add_command(label="Run/Pause",command=self.toggle_run)
        menubar.add_cascade(label="Emulation",menu=emu_menu)

        # One canvas for everything
        self.canvas = tk.Canvas(self.root,bg='black',width=512,height=520,highlightthickness=0)
        self.canvas.pack(expand=True)

    def load_rom(self):
        file = filedialog.askopenfilename(title="Load NES ROM",filetypes=[("NES ROMs","*.nes")])
        if file:
            self.emulator = Emulator(file)
            messagebox.showinfo("ROM Loaded",f"Loaded {os.path.basename(file)}")

    def toggle_run(self):
        if not self.emulator:
            messagebox.showwarning("No ROM","Please load a ROM first.")
            return
        self.running = not self.running
        if self.running: self.step_emulation()

    def step_emulation(self):
        if not self.running: return
        self.emulator.run_frame()
        self.update_canvas()
        self.root.after(16,self.step_emulation)

    def update_canvas(self):
        emu = self.emulator
        frame = emu.get_frame()
        img = Image.fromarray(frame,'RGB').resize((512,480),Image.NEAREST)
        photo = ImageTk.PhotoImage(img)
        self.canvas.image = photo
        self.canvas.delete("all")
        self.canvas.create_image(0,0,anchor=tk.NW,image=photo)

        # backend / debug info
        cpu = emu.cpu
        text = (
            f"PC=${cpu.pc:04X}  OPCODE=${cpu.last_opcode:02X}  "
            f"A={cpu.a:02X} X={cpu.x:02X} Y={cpu.y:02X}  "
            f"SP={cpu.sp:02X}  CYCLES={cpu.cycles}"
        )
        self.canvas.create_text(256,500,text=text,fill="lime",font=("Consolas",12,"bold"))

    def run(self): self.root.mainloop()

if __name__ == "__main__":
    NESEmulator().run()
