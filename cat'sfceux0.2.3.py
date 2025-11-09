# program.py - Cat's FCEUX 0.1.3 (Unified Canvas Edition)
# [C] 2025 Samsoft / Cat-san
#
# Educational homebrew prototype with basic 6502, Mapper0/1, and simple PPU renderer.
# Single-canvas GUI for visualization. Not a commercial emulator.

# ──────────────────────────────
# Imports
# ──────────────────────────────
import os, time, threading, tkinter as tk
from tkinter import filedialog, ttk, messagebox
import numpy as np
from PIL import Image, ImageTk
from enum import Enum
from typing import Optional

# ──────────────────────────────
# Constants
# ──────────────────────────────
APP_TITLE = "Cat’s FCEUX 0.1.3"
BASE_WIDTH, BASE_HEIGHT = 256, 240
DEFAULT_SCALE = 2

NES_PALETTE = np.array([
    [124,124,124],[0,0,252],[0,0,188],[68,40,188],
    [148,0,132],[168,0,32],[168,16,0],[136,20,0],
    [80,48,0],[0,120,0],[0,104,0],[0,88,0],
    [0,64,88],[0,0,0],[0,0,0],[0,0,0]
], dtype=np.uint8)

# ──────────────────────────────
# Enums
# ──────────────────────────────
class MirrorType(Enum):
    HORIZONTAL = 1
    VERTICAL = 2
    FOUR_SCREEN = 3

# ──────────────────────────────
# CPU
# ──────────────────────────────
class CPU:
    def __init__(self, mem):
        self.memory = mem
        self.pc = 0; self.sp = 0xFD
        self.a = self.x = self.y = 0
        self.flags = 0x24
        self.cycles = 0
        self.opcodes = self._build_opcode_table()

    def _build_opcode_table(self):
        t = {}
        t[0xA9] = lambda: self._imm(lambda v: setattr(self, 'a', v))
        t[0xA5] = lambda: self._zp('a')
        t[0x00] = self._brk
        return t

    def _imm(self, op):
        val = self.memory.read(self.pc); self.pc += 1
        op(val); self._set_flags(self.a); self.cycles += 2
    def _zp(self, reg):
        addr = self.memory.read(self.pc); self.pc += 1
        val = self.memory.read(addr); setattr(self, reg, val)
        self._set_flags(val); self.cycles += 3
    def _brk(self):
        self.flags |= 0x10; self.pc += 1; self.cycles += 7
    def _set_flags(self,val):
        self.flags = (self.flags & 0x7D) | ((val==0)<<1) | (1 if val&0x80 else 0<<5)
    def reset(self):
        self.pc = self.memory.read(0xFFFC) | (self.memory.read(0xFFFD)<<8)
        self.sp = 0xFD; self.a=self.x=self.y=0; self.flags=0x24; self.cycles=0
    def step(self):
        op=self.memory.read(self.pc); self.pc+=1
        self.opcodes.get(op, lambda: None)(); self.cycles+=1
    def exec_instructions(self,count):
        for _ in range(count): self.step()

# ──────────────────────────────
# Mappers
# ──────────────────────────────
class Mapper0:
    def __init__(self,cart): self.cart=cart
    def prg_read(self,addr): return self.cart.prg_rom[(addr-0x8000)%len(self.cart.prg_rom)]
    def prg_write(self,addr,val): pass
    def chr_read(self,addr): return self.cart.chr_rom[addr] if self.cart.chr_rom else 0
    def chr_write(self,addr,val): pass

class Mapper1:
    def __init__(self,cart):
        self.cart=cart; self.shift_reg=0; self.shift_count=0
        self.prg_mode=0; self.prg_bank=0
    def prg_write(self,addr,val):
        pass
    def prg_read(self,addr):
        bank=self.prg_bank
        return self.cart.prg_rom[(addr-0x8000)+bank*0x4000]
    def chr_read(self,addr): return self.cart.chr_rom[addr]

# ──────────────────────────────
# Cartridge
# ──────────────────────────────
class Cartridge:
    def __init__(self,data:bytes):
        if data[:4]!=b'NES\x1A': raise ValueError("Invalid NES ROM")
        prg_banks, chr_banks=data[4], data[5]
        flag6,flag7=data[6],data[7]
        self.mapper_type=((flag7&0xF0)|(flag6>>4))&0xFF
        self.mirroring=MirrorType.VERTICAL if flag6&1 else MirrorType.HORIZONTAL
        prg_size,chr_size=prg_banks*0x4000,chr_banks*0x2000
        offset=16+(512 if flag6&4 else 0)
        self.prg_rom=data[offset:offset+prg_size]
        self.chr_rom=data[offset+prg_size:offset+prg_size+chr_size] if chr_size else bytes(0x2000)
        self.mapper=Mapper0(self) if self.mapper_type==0 else Mapper1(self)

# ──────────────────────────────
# Memory
# ──────────────────────────────
class Memory:
    def __init__(self,cart=None):
        self.ram=bytearray(0x800)
        self.vram=bytearray(0x1000)
        self.cart=cart; self.mapper=cart.mapper if cart else None
    def read(self,addr):
        addr&=0xFFFF
        if addr<0x2000: return self.ram[addr%0x800]
        if 0x2000<=addr<0x4000: return self.vram[(addr%0x1000)%0x400]
        if 0x8000<=addr<0x10000 and self.mapper: return self.mapper.prg_read(addr)
        return 0
    def write(self,addr,val):
        addr&=0xFFFF; val&=0xFF
        if addr<0x2000: self.ram[addr%0x800]=val
        if 0x2000<=addr<0x4000: self.vram[(addr%0x1000)%0x400]=val
        if 0x8000<=addr<0x10000 and self.mapper: self.mapper.prg_write(addr,val)

# ──────────────────────────────
# PPU
# ──────────────────────────────
class PPU:
    def __init__(self,mem):
        self.memory=mem
        self.framebuffer=np.zeros((BASE_HEIGHT,BASE_WIDTH,3),np.uint8)
    def render_frame(self):
        for y in range(30):
            for x in range(32):
                tile=self.memory.read(0x2000+y*32+x)
                for py in range(8):
                    for px in range(8):
                        bit0=(self.memory.read(0x0000+tile*16+py)>>(7-px))&1
                        bit1=(self.memory.read(0x0000+tile*16+py+8)>>(7-px))&1
                        color=(bit1<<1)|bit0
                        pal=NES_PALETTE[color%len(NES_PALETTE)]
                        self.framebuffer[y*8+py,x*8+px]=pal
        return self.framebuffer
    def get_framebuffer(self): return self.render_frame().copy()

# ──────────────────────────────
# Emulator Core
# ──────────────────────────────
class Emulator:
    def __init__(self,path):
        with open(path,"rb") as f: data=f.read()
        self.cart=Cartridge(data)
        self.memory=Memory(self.cart)
        self.cpu=CPU(self.memory)
        self.ppu=PPU(self.memory)
        self.cpu.reset()
        self.instructions_per_frame=29780
    def run_frame(self):
        self.cpu.exec_instructions(self.instructions_per_frame//3)
        self.ppu.render_frame()
    def get_frame(self): return self.ppu.get_framebuffer()

# ──────────────────────────────
# GUI: Unified Single-Canvas
# ──────────────────────────────
class CatsFCEUXApp:
    def __init__(self):
        self.root=tk.Tk()
        self.root.title(APP_TITLE)
        self.root.configure(bg='gray12')
        self.canvas=tk.Canvas(self.root,width=BASE_WIDTH*DEFAULT_SCALE,
                              height=BASE_HEIGHT*DEFAULT_SCALE,bg='black',highlightthickness=0)
        self.canvas.pack(padx=10,pady=10)
        self.status=tk.Label(self.root,text="No ROM loaded",fg='white',bg='gray12')
        self.status.pack()
        self.emu=None
        self.running=False
        self.image=None
        self._build_menu()
    def _build_menu(self):
        menubar=tk.Menu(self.root,bg='gray20',fg='white')
        filemenu=tk.Menu(menubar,tearoff=0,bg='gray20',fg='white')
        filemenu.add_command(label="Load ROM",command=self.open_rom)
        filemenu.add_separator()
        filemenu.add_command(label="Exit",command=self.root.quit)
        menubar.add_cascade(label="File",menu=filemenu)
        self.root.config(menu=menubar)
    def open_rom(self):
        path=filedialog.askopenfilename(title="Open NES ROM",filetypes=[("NES ROMs","*.nes")])
        if not path: return
        try:
            self.emu=Emulator(path)
            self.status.config(text=f"Loaded: {os.path.basename(path)}")
            self.toggle_run()
        except Exception as e:
            messagebox.showerror("Error",str(e))
    def toggle_run(self):
        if self.emu and not self.running:
            self.running=True
            threading.Thread(target=self._loop,daemon=True).start()
    def _loop(self):
        while self.running:
            self.emu.run_frame()
            frame=self.emu.get_frame()
            img=Image.fromarray(frame).resize((BASE_WIDTH*DEFAULT_SCALE,BASE_HEIGHT*DEFAULT_SCALE))
            self.image=ImageTk.PhotoImage(img)
            self.canvas.create_image(0,0,anchor='nw',image=self.image)
            self.root.update_idletasks(); self.root.update()
            time.sleep(1/60)
    def run(self): self.root.mainloop()

# ──────────────────────────────
# Entry Point
# ──────────────────────────────
if __name__=="__main__":
    CatsFCEUXApp().run()
