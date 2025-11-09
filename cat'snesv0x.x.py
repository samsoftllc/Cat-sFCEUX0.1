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

    def prg_write(self, addr: int, value: int):
        pass

    def chr_read(self, addr: int) -> int:
        return self.cartridge.chr_rom[addr]

    def chr_write(self, addr: int, value: int):
        pass

class Cartridge:
    def __init__(self, rom_data: bytes):
        if rom_data[0:4] != b'NES\x1A':
            raise ValueError("Invalid NES ROM header")
        prg_banks = rom_data[4]
        chr_banks = rom_data[5]
        flag6 = rom_data[6]
        flag7 = rom_data[7]
        self.mapper_type = (flag6 >> 4) | (flag7 & 0xF0)
        if flag6 & 0x08:
            self.mirroring = MirrorType.FOUR_SCREEN
        else:
            self.mirroring = MirrorType.VERTICAL if flag6 & 0x01 else MirrorType.HORIZONTAL
        prg_size = prg_banks * 0x4000
        chr_size = chr_banks * 0x2000
        offset = 16 + (512 if flag6 & 0x04 else 0)
        self.prg_rom = rom_data[offset:offset + prg_size]
        self.chr_rom = rom_data[offset + prg_size:offset + prg_size + chr_size]
        self.prg_banks = prg_banks
        self.chr_banks = chr_banks

class Memory:
    def __init__(self, cartridge: Optional[Cartridge] = None):
        self.ram = [0] * 0x800
        self.vram = [0] * 0x1000
        self.palette_ram = [0] * 0x20
        self.oam = [0] * 0x100
        self.cartridge = cartridge
        self.mapper = Mapper(cartridge) if cartridge else None
        self.controller = None

class Emulator:
    def __init__(self, rom_path: str):
        with open(rom_path, 'rb') as f:
            rom_data = f.read()
        self.cartridge = Cartridge(rom_data)
        self.memory = Memory(self.cartridge)
        self.running = True

    def run_frame(self):
        pass

    def set_controller_input(self, player: int, buttons: int):
        pass

    def get_frame(self) -> np.ndarray:
        return np.zeros((240, 256, 3), dtype=np.uint8)

class NESEmulator:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Cat's NES 1.0 with Enhanced Engine")
        self.root.geometry("1024x768")
        self.root.configure(bg='gray20')
        self.running = False
        self.fullscreen_state = False
        self.emulator = None
        self.rom_path = None
        self.keys = set()

        # Menu bar
        menubar = tk.Menu(self.root, bg='gray20', fg='white', tearoff=0)
        self.root.config(menu=menubar)
        file_menu = tk.Menu(menubar, tearoff=0, bg='gray20', fg='white')
        file_menu.add_command(label="Load ROM", command=self.load_rom)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        emulation_menu = tk.Menu(menubar, tearoff=0, bg='gray20', fg='white')
        emulation_menu.add_command(label="Run/Pause", command=self.toggle_run)
        emulation_menu.add_command(label="Reset", command=self.reset)
        emulation_menu.add_command(label="Frame Advance", command=self.frame_advance)
        menubar.add_cascade(label="Emulation", menu=emulation_menu)

        # Toolbar
        toolbar = tk.Frame(self.root, bg='gray30', height=30)
        toolbar.pack(side=tk.TOP, fill=tk.X)
        tk.Button(toolbar, text="Load ROM", command=self.load_rom, bg='gray40', fg='white').pack(side=tk.LEFT, padx=2)
        self.rom_var = tk.StringVar(value="No ROM loaded")
        self.rom_combo = ttk.Combobox(toolbar, textvariable=self.rom_var, state="readonly", width=40)
        self.rom_combo.pack(side=tk.LEFT, padx=2)
        self.run_button = tk.Button(toolbar, text="▶ Run", bg='green', fg='white', command=self.toggle_run)
        self.run_button.pack(side=tk.LEFT, padx=2)
        tk.Button(toolbar, text="Reset", command=self.reset, bg='gray40', fg='white').pack(side=tk.LEFT, padx=2)
        tk.Button(toolbar, text="Frame Advance", command=self.frame_advance, bg='gray40', fg='white').pack(side=tk.LEFT, padx=2)
        tk.Button(toolbar, text="Fullscreen", command=self.fullscreen, bg='gray40', fg='white').pack(side=tk.LEFT, padx=2)

        # ───────────────────────────────────────────────
        # Fixed Screen + Sidebar layout
        # ───────────────────────────────────────────────
        main_frame = tk.Frame(self.root, bg='gray20')
        main_frame.pack(expand=True, fill=tk.BOTH)

        # Left: NES Screen
        screen_frame = tk.Frame(main_frame, bg='black')
        screen_frame.pack(side=tk.LEFT, expand=True, fill=tk.BOTH)
        self.screen = tk.Canvas(screen_frame, bg='black', width=512, height=480, highlightthickness=0)
        self.screen.pack(expand=True)

        # Right: Sidebar
        sidebar = tk.Frame(main_frame, bg='gray20', width=300)
        sidebar.pack(side=tk.RIGHT, fill=tk.Y)
        sidebar.pack_propagate(False)

        tk.Label(sidebar, text="Memory", bg='gray20', fg='white').pack(anchor=tk.W)
        self.mem_text = tk.Text(sidebar, height=15, width=25, bg='black', fg='green', font=('Courier', 8))
        self.mem_text.pack(fill=tk.X, pady=2)
        self.mem_text.insert(tk.END, "0981 010\n0982 004\n0983 104\n0984 037\n0985 145")

        for panel in ["Palette", "Tiles", "Sprites", "Waveforms", "OAM", "PPU Viewer"]:
            tk.Label(sidebar, text=panel, bg='gray20', fg='white').pack(anchor=tk.W, pady=2)
        tk.Button(sidebar, text="Find", bg='gray40', fg='white', command=self.find_dialog).pack(fill=tk.X, pady=2)
        tk.Button(sidebar, text="Cheats", bg='gray40', fg='white', command=self.cheats_dialog).pack(fill=tk.X, pady=2)

        # Status bar
        status = tk.Frame(self.root, bg='gray30', height=20)
        status.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_label = tk.Label(status, text="PC=0000 A=00 X=00 Y=00 Flags=00", bg='gray30', fg='white')
        self.status_label.pack(side=tk.LEFT, padx=5)
        tk.Label(status, text="Press F12 for menu", bg='gray30', fg='white').pack(side=tk.RIGHT, padx=5)

        # Key bindings
        self.root.bind('<F12>', lambda e: self.root.quit())
        self.root.bind('<KeyPress>', self.key_press)
        self.root.bind('<KeyRelease>', self.key_release)

    def key_press(self, e):
        self.keys.add(e.keysym)

    def key_release(self, e):
        self.keys.discard(e.keysym)

    def load_rom(self):
        file = filedialog.askopenfilename(title="Load NES ROM", filetypes=[("NES ROMs", "*.nes")])
        if file:
            try:
                self.emulator = Emulator(file)
                self.rom_path = file
                self.rom_var.set(os.path.basename(file))
                messagebox.showinfo("ROM Loaded", f"Loaded ROM:\n{file}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load ROM: {e}")

    def toggle_run(self):
        if not self.emulator:
            messagebox.showwarning("No ROM", "Please load a ROM first.")
            return
        self.running = not self.running
        self.run_button.config(text="❚❚ Pause" if self.running else "▶ Run", bg='red' if self.running else 'green')

    def reset(self):
        messagebox.showinfo("Reset", "Emulator reset (stub).")

    def frame_advance(self):
        messagebox.showinfo("Frame Advance", "Frame advanced (stub).")

    def fullscreen(self):
        self.fullscreen_state = not self.fullscreen_state
        self.root.attributes('-fullscreen', self.fullscreen_state)

    def find_dialog(self):
        messagebox.showinfo("Find", "Find feature (Stub)")

    def cheats_dialog(self):
        messagebox.showinfo("Cheats", "Cheats panel (Stub)")

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    emu = NESEmulator()
    emu.run()
