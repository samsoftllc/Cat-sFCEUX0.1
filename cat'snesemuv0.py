# program.py - Full NES Emulator in Python with Minimal FCEUX 0.1 GUI
# [C] 2025 Samsoft / Cat-san

import tkinter as tk
from tkinter import Menu, messagebox, filedialog, simpledialog
import struct
import numpy as np
from typing import Optional
from PIL import Image, ImageTk # Added for rendering the frame

# ────────────────────────────────────────────────────────────────────────────────────
# NES Backend
# ────────────────────────────────────────────────────────────────────────────────────
class NESBackend:
    def __init__(self):
        self.cpu = CPU(self)
        self.ppu = PPU(self)
        self.apu = APU()
        self.mapper = None
        self.ram = bytearray(0x800)
        self.vram = bytearray(0x1000)
        self.rom_prg = bytearray()
        self.rom_chr = bytearray()
        self.cycles = 0
        self.frame_count = 0
        self.running = False
        self.input_state = {'A': False, 'B': False, 'SELECT': False, 'START': False, 'UP': False, 'DOWN': False, 'LEFT': False, 'RIGHT': False}
        self.key_map = {
            'z': 'A', 'x': 'B',
            'Return': 'START', 'Shift_R': 'SELECT',
            'Up': 'UP', 'Down': 'DOWN', 'Left': 'LEFT', 'Right': 'RIGHT'
        }


    def load_rom(self, path: str) -> bool:
        try:
            with open(path, 'rb') as f:
                header = f.read(16)
                if header[0:4] != b'NES\x1A':
                    messagebox.showerror("Load Error", "Not a valid iNES file.")
                    return False
                prg_size = header[4] * 0x4000
                chr_size = header[5] * 0x2000
                mapper_id = (header[6] >> 4) | (header[7] & 0xF0)
                prg_data = f.read(prg_size)
                chr_data = f.read(chr_size) if chr_size else bytearray(0x2000)

                self.mapper = Mapper(mapper_id, self)
                self.rom_prg = prg_data
                self.rom_chr = chr_data
                self.cpu.reset()
                self.ppu.load_chr(self.rom_chr)
                self.running = True
                print(f"Loaded ROM: PRG={prg_size//1024}KB, CHR={chr_size//1024}KB, Mapper={mapper_id}")
                return True
        except Exception as e:
            messagebox.showerror("Load Error", f"Failed to load ROM: {e}")
            self.running = False
            return False

    def step_frame(self) -> np.ndarray:
        if not self.running:
            return self.ppu.framebuffer
            
        target_cycles = 29781  # Approx cycles per frame
        self.cycles = 0
        while self.cycles < target_cycles:
            cycles = self.cpu.step()
            self.ppu.step(cycles * 3)
            self.apu.step()
            self.cycles += cycles
        self.frame_count += 1
        return self.ppu.render_frame()

    def inject_cheat(self, addr: int, value: int):
        if 0 <= addr < len(self.ram):
            self.ram[addr] = value
            print(f"Cheat injected: RAM[0x{addr:04X}] = 0x{value:02X}")

    def debug_ram(self, addr: int) -> int:
        return self.ram[addr % 0x800] if addr < 0x2000 else 0
        
    def set_key_state(self, key: str, pressed: bool):
        if key in self.key_map:
            button = self.key_map[key]
            self.input_state[button] = pressed
            # print(f"{button} {'Pressed' if pressed else 'Released'}") # For debugging input

# ────────────────────────────────────────────────────────────────────────────────────
# Mapper
# ────────────────────────────────────────────────────────────────────────────────────
class Mapper:
    def __init__(self, id: int, nes: NESBackend):
        self.id = id
        self.nes = nes
        self.prg_banks = max(1, len(nes.rom_prg) // 0x4000)
        self.chr_banks = max(1, len(nes.rom_chr) // 0x2000)
        self.prg_bank0 = 0
        self.prg_bank1 = self.prg_banks - 1
        print(f"Mapper {id} initialized. PRG Banks: {self.prg_banks}")

    def read_prg(self, addr: int) -> int:
        if self.id == 0 and self.nes.rom_prg:
            if 0x8000 <= addr <= 0xBFFF:
                # First 16KB bank (or mirror of last if only 1 bank)
                offset = self.prg_bank0 * 0x4000 + (addr - 0x8000)
            elif 0xC000 <= addr <= 0xFFFF:
                # Last 16KB bank
                offset = self.prg_bank1 * 0x4000 + (addr - 0xC000)
            else:
                return 0
            return self.nes.rom_prg[offset % len(self.nes.rom_prg)]
        return 0

    def write_prg(self, addr: int, value: int): 
        # Mapper 0 (NROM) has no PRG writing, but other mappers would.
        pass
        
    def read_chr(self, addr: int) -> int: 
        # Mapper 0 uses CHR-ROM
        return self.nes.rom_chr[addr % len(self.nes.rom_chr)] if self.nes.rom_chr else 0
        
    def write_chr(self, addr: int, value: int): 
        # Only for CHR-RAM
        if self.id == 0 and not self.nes.rom_chr:
             self.nes.rom_chr[addr % 0x2000] = value

# ────────────────────────────────────────────────────────────────────────────────────
# CPU (simplified example opcodes)
# ────────────────────────────────────────────────────────────────────────────────────
class CPU:
    def __init__(self, nes: NESBackend):
        self.nes = nes
        self.pc = 0
        self.sp = 0xFD
        self.a = 0
        self.x = 0
        self.y = 0
        self.flags = 0x24
        self.cycles = 0
        self.flag_mask = {'C':1,'Z':2,'I':4,'D':8,'B':16,'U':32,'V':64,'N':128}
        # Very minimal opcode set for demonstration
        self.opcodes = {
            0x00: self.brk,
            0xA9: self.lda_imm,
            0xAD: self.lda_abs,
            0x8D: self.sta_abs,
            0x4C: self.jmp_abs,
            # Add more opcodes here as needed
        }

    def reset(self):
        # For NROM, typically start at 0xC000
        # A full implementation would read the reset vector from 0xFFFC
        self.pc = self.read_word(0xFFFC)
        if self.pc < 0x8000: # Fallback for some test ROMs
            self.pc = 0xC000
        self.sp = 0xFD
        self.flags = 0x24
        print(f"CPU Reset. PC = 0x{self.pc:04X}")

    def step(self) -> int:
        opcode = self.read_byte(self.pc)
        self.pc += 1
        return self.opcodes.get(opcode, self.nop)()

    def read_byte(self, addr: int) -> int:
        if addr < 0x2000:
            return self.nes.ram[addr % 0x800]
        elif 0x2000 <= addr <= 0x3FFF:
            return self.nes.ppu.read_reg(addr % 8)
        elif 0x4016 == addr: # Controller 1
             return 0 # Stubbed controller read
        elif addr >= 0x8000:
            return self.nes.mapper.read_prg(addr)
        return 0

    def read_word(self, addr: int) -> int:
        lo = self.read_byte(addr)
        hi = self.read_byte(addr + 1)
        return (hi << 8) | lo

    def write_byte(self, addr: int, value: int):
        if addr < 0x2000:
            self.nes.ram[addr % 0x800] = value
        elif 0x2000 <= addr <= 0x3FFF:
            self.nes.ppu.write_reg(addr % 8, value)
        elif 0x4014 == addr: # OAM DMA
            self.nes.ppu.do_oam_dma(value)
        elif 0x4016 == addr: # Controller 1
            pass # Stubbed controller write
        elif addr >= 0x8000:
            self.nes.mapper.write_prg(addr, value)

    def set_flags(self, f, v):
        if v:
            self.flags |= self.flag_mask[f]
        else:
            self.flags &= ~self.flag_mask[f]

    def get_flag(self, f) -> bool:
        return (self.flags & self.flag_mask[f]) > 0
        
    # --- Example Opcodes ---

    def lda_imm(self) -> int:
        self.a = self.read_byte(self.pc)
        self.pc += 1
        self.set_flags('Z', self.a == 0)
        self.set_flags('N', self.a & 0x80)
        return 2

    def lda_abs(self) -> int:
        addr = self.read_word(self.pc)
        self.pc += 2
        self.a = self.read_byte(addr)
        self.set_flags('Z', self.a == 0)
        self.set_flags('N', self.a & 0x80)
        return 4

    def sta_abs(self) -> int:
        addr = self.read_word(self.pc)
        self.pc += 2
        self.write_byte(addr, self.a)
        return 4
        
    def jmp_abs(self) -> int:
        self.pc = self.read_word(self.pc)
        return 3

    def brk(self) -> int: return 7
    def nop(self) -> int: return 2

# ────────────────────────────────────────────────────────────────────────────────────
# PPU (stub render)
# ────────────────────────────────────────────────────────────────────────────────────
class PPU:
    def __init__(self, nes: NESBackend):
        self.nes = nes
        self.chr = bytearray(0x2000)
        self.palette = bytearray(0x20)
        self.oam = bytearray(0x100)
        self.framebuffer = np.zeros((240, 256, 3), dtype=np.uint8)
        self.scanline = 0
        self.cycle = 0
        
        # PPU Registers
        self.ppuctrl = 0
        self.ppumask = 0
        self.ppustatus = 0
        self.oamaddr = 0
        self.ppuaddr = 0
        self.ppudata_buf = 0
        self.vram_addr = 0 # Current VRAM address (15 bits)
        self.temp_vram_addr = 0 # Temporary VRAM address (15 bits)
        self.fine_x = 0 # Fine X scroll (3 bits)
        self.write_toggle = False # Address/scroll write toggle

    def load_chr(self, chr_data: bytes):
        self.chr = bytearray(chr_data)

    def step(self, cycles: int):
        # Simplified step: Just check for VBlank
        self.cycle += cycles
        if self.scanline < 240: # Visible scanlines
            if self.cycle >= 341:
                self.cycle -= 341
                self.scanline += 1
        elif self.scanline == 241: # VBlank start
            if self.cycle >= 1: # Start VBlank on 241st scanline, 1st cycle
                self.ppustatus |= 0x80 # Set VBlank flag
                if self.ppuctrl & 0x80:
                    # Trigger NMI
                    pass # self.nes.cpu.nmi()
        elif self.scanline < 261: # VBlank scanlines
             if self.cycle >= 341:
                self.cycle -= 341
                self.scanline += 1
        elif self.scanline == 261: # Pre-render scanline
            if self.cycle >= 1:
                self.ppustatus &= ~0x80 # Clear VBlank flag
            if self.cycle >= 341:
                self.cycle -= 341
                self.scanline = 0 # Wrap to first scanline
                

    def render_frame(self) -> np.ndarray:
        # Stub: just return a black (or gray) buffer
        # A real render would draw tiles here based on PPU state
        if self.nes.running:
             # Fill with a color to show it's "running"
             self.framebuffer[:, :] = [48, 48, 48] 
        else:
             # Fill with black when off
             self.framebuffer[:, :] = [0, 0, 0]
        return self.framebuffer

    def read_reg(self, addr: int) -> int:
        if addr == 2: # PPUSTATUS
            status = self.ppustatus
            self.ppustatus &= ~0x80 # Clear VBlank flag on read
            self.write_toggle = False
            return status
        if addr == 7: # PPUDATA
            value = self.read_vram(self.vram_addr)
            # Implement read buffer delay
            if self.vram_addr % 0x4000 < 0x3F00:
                buffered_val = self.ppudata_buf
                self.ppudata_buf = value
                value = buffered_val
            else:
                self.ppudata_buf = self.read_vram(self.vram_addr - 0x1000)
                
            self.vram_addr += (1 if (self.ppuctrl & 0x04) == 0 else 32)
            return value
        return 0

    def write_reg(self, addr: int, val: int):
        if addr == 0: # PPUCTRL
            self.ppuctrl = val
            self.temp_vram_addr = (self.temp_vram_addr & 0xF3FF) | ((val & 0x03) << 10)
        elif addr == 1: # PPUMASK
            self.ppumask = val
        elif addr == 3: # OAMADDR
            self.oamaddr = val
        elif addr == 4: # OAMDATA
            self.oam[self.oamaddr] = val
            self.oamaddr = (self.oamaddr + 1) & 0xFF
        elif addr == 5: # PPUSCROLL
            if not self.write_toggle:
                self.temp_vram_addr = (self.temp_vram_addr & 0xFFE0) | (val >> 3)
                self.fine_x = val & 0x07
            else:
                self.temp_vram_addr = (self.temp_vram_addr & 0x8C1F) | ((val & 0xF8) << 2) | ((val & 0x07) << 12)
            self.write_toggle = not self.write_toggle
        elif addr == 6: # PPUADDR
            if not self.write_toggle:
                self.temp_vram_addr = (self.temp_vram_addr & 0x00FF) | ((val & 0x3F) << 8)
            else:
                self.temp_vram_addr = (self.temp_vram_addr & 0xFF00) | val
                self.vram_addr = self.temp_vram_addr
            self.write_toggle = not self.write_toggle
        elif addr == 7: # PPUDATA
            self.write_vram(self.vram_addr, val)
            self.vram_addr += (1 if (self.ppuctrl & 0x04) == 0 else 32)
            
    def read_vram(self, addr: int) -> int:
        addr &= 0x3FFF
        if addr < 0x2000:
            return self.nes.mapper.read_chr(addr)
        elif addr < 0x3F00:
            return self.nes.vram[addr % 0x1000] # Nametables
        elif addr < 0x4000:
            addr = (addr & 0x1F)
            if addr in (0x10, 0x14, 0x18, 0x1C): addr -= 0x10 # Palette mirrors
            return self.palette[addr]
        return 0

    def write_vram(self, addr: int, val: int):
        addr &= 0x3FFF
        if addr < 0x2000:
            self.nes.mapper.write_chr(addr, val)
        elif addr < 0x3F00:
            self.nes.vram[addr % 0x1000] = val
        elif addr < 0x4000:
            addr = (addr & 0x1F)
            if addr in (0x10, 0x14, 0x18, 0x1C): addr -= 0x10 # Palette mirrors
            self.palette[addr] = val
            
    def do_oam_dma(self, page: int):
        # CPU transfers 256 bytes from RAM page `page` to OAM
        addr_start = page << 8
        for i in range(256):
            val = self.nes.cpu.read_byte(addr_start + i)
            self.oam[(self.oamaddr + i) & 0xFF] = val
        # This should also stall the CPU for 513/514 cycles
        # self.nes.cpu.cycles += 513 

# ────────────────────────────────────────────────────────────────────────────────────
# APU (stub)
# ────────────────────────────────────────────────────────────────────────────────────
class APU:
    def __init__(self):
        pass
    def step(self):
        pass
    def write_reg(self, addr: int, val: int):
        pass
    def read_reg(self, addr: int) -> int:
        return 0

# ────────────────────────────────────────────────────────────────────────────────────
# GUI (NEW CLASS)
# ────────────────────────────────────────────────────────────────────────────────────
class GUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Cat's FCEUX 0.1")
        self.geometry("512x480") # 256x240 scaled 2x
        self.resizable(False, False)
        
        self.nes = NESBackend()
        
        self.create_menu()
        
        # Create the canvas for rendering
        self.canvas = tk.Canvas(self, width=512, height=480, bg="black", highlightthickness=0)
        self.canvas.pack()
        
        # Prepare the image object for the framebuffer
        self.image = Image.new('RGB', (256, 240))
        self.photo_image = ImageTk.PhotoImage(self.image.resize((512, 480), Image.NEAREST))
        self.image_on_canvas = self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo_image)
        
        # Bind keyboard input
        self.bind("<KeyPress>", self.on_key_press)
        self.bind("<KeyRelease>", self.on_key_release)
        
        print("GUI Initialized. Starting game loop.")
        self.update_game()

    def create_menu(self):
        self.menu_bar = Menu(self)
        self.config(menu=self.menu_bar)
        
        # File Menu
        file_menu = Menu(self.menu_bar, tearoff=0)
        file_menu.add_command(label="Open ROM...", command=self.open_rom)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.quit)
        self.menu_bar.add_cascade(label="File", menu=file_menu)
        
        # Options Menu (stub)
        options_menu = Menu(self.menu_bar, tearoff=0)
        # Add options later
        self.menu_bar.add_cascade(label="Options", menu=options_menu)
        
        # Tools Menu
        tools_menu = Menu(self.menu_bar, tearoff=0)
        tools_menu.add_command(label="Cheats...", command=self.open_cheats)
        tools_menu.add_command(label="Debug...", command=self.open_debug)
        self.menu_bar.add_cascade(label="Tools", menu=tools_menu)
        
        # Help Menu
        help_menu = Menu(self.menu_bar, tearoff=0)
        help_menu.add_command(label="About...", command=self.show_about)
        self.menu_bar.add_cascade(label="Help", menu=help_menu)

    def open_rom(self):
        path = filedialog.askopenfilename(
            title="Open NES ROM",
            filetypes=(("NES ROMs", "*.nes"), ("All Files", "*.*"))
        )
        if path:
            print(f"Loading ROM from: {path}")
            self.nes.load_rom(path)

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
        addr_str = simpledialog.askstring("Debug RAM", "Enter RAM address (hex):")
        if addr_str:
            try:
                addr = int(addr_str, 16)
                value = self.nes.debug_ram(addr)
                messagebox.showinfo("Debug RAM", f"Value at 0x{addr:04X}: 0x{value:02X} ({value})")
            except Exception as e:
                messagebox.showerror("Debug Error", f"Invalid address.\n{e}")
    
    def show_about(self):
        messagebox.showinfo("About Cat's FCEUX 0.1",
                            "Minimal NES Emulator\n[C] 2025 Samsoft / Cat-san")

    def on_key_press(self, event):
        self.nes.set_key_state(event.keysym, True)

    def on_key_release(self, event):
        self.nes.set_key_state(event.keysym, False)

    def update_game(self):
        # Run one frame of the emulator
        frame = self.nes.step_frame()
        
        # Update the image on the canvas
        self.image = Image.fromarray(frame, 'RGB')
        self.photo_image = ImageTk.PhotoImage(self.image.resize((512, 480), Image.NEAREST))
        self.canvas.itemconfig(self.image_on_canvas, image=self.photo_image)
        
        # Schedule the next update (aims for ~60 FPS)
        self.after(16, self.update_game)

# ────────────────────────────────────────────────────────────────────────────────────
# Main Execution
# ────────────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = GUI()
    app.mainloop()
