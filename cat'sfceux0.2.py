# program.py - Cat's FCEUX 0.2 (Homebrew-focused single-file NES emulator)
# [C] 2025 Samsoft / Cat-san

import tkinter as tk
from tkinter import Menu, messagebox, filedialog
import struct
import numpy as np
from PIL import Image, ImageTk

# ───────────────────────────────────────────────
# Constants
# ───────────────────────────────────────────────
CPU_CYCLES_PER_FRAME = 29781

NES_PALETTE = np.array([
    [84, 84, 84], [0, 30, 116], [8, 16, 144], [48, 0, 136],
    [68, 0, 100], [92, 0, 48], [84, 4, 0], [60, 24, 0],
    [32, 42, 0], [8, 58, 0], [0, 64, 0], [0, 60, 0],
    [0, 50, 60], [0, 0, 0], [0, 0, 0], [0, 0, 0],
    [152, 150, 152], [8, 76, 196], [48, 50, 236], [92, 30, 228],
    [136, 20, 176], [160, 20, 100], [152, 34, 32], [120, 60, 0],
    [84, 90, 0], [40, 114, 0], [8, 124, 0], [0, 118, 40],
    [0, 102, 120], [0, 0, 0], [0, 0, 0], [0, 0, 0],
    [236, 238, 236], [76, 154, 236], [120, 124, 236], [176, 98, 236],
    [228, 84, 236], [236, 88, 180], [236, 106, 100], [212, 136, 32],
    [160, 170, 0], [116, 196, 0], [76, 208, 32], [56, 204, 108],
    [56, 180, 204], [60, 60, 60], [0, 0, 0], [0, 0, 0],
])

# ───────────────────────────────────────────────
# Core Stub Classes
# ───────────────────────────────────────────────
class CPU:
    def __init__(self, nes):
        self.nes = nes
        self.reset()

    def reset(self):
        self.pc = 0xC000
        self.a = self.x = self.y = 0
        self.sp = 0xFD
        self.status = 0x24

    def step(self):
        # Simulate CPU stepping (stub)
        self.pc = (self.pc + 1) & 0xFFFF


class PPU:
    def __init__(self, nes):
        self.nes = nes
        self.framebuffer = np.zeros((240, 256, 3), dtype=np.uint8)

    def render_frame(self):
        # Simple test pattern if ROM is empty
        for y in range(240):
            for x in range(256):
                color = NES_PALETTE[(x // 16 + y // 16) % len(NES_PALETTE)]
                self.framebuffer[y, x] = color
        return self.framebuffer


class APU:
    def __init__(self):
        pass  # no sound for now


# ───────────────────────────────────────────────
# NES Backend
# ───────────────────────────────────────────────
class NESBackend:
    def __init__(self):
        self.cpu = CPU(self)
        self.ppu = PPU(self)
        self.apu = APU()
        self.running = False
        self.rom_loaded = False

    def load_rom(self, path):
        try:
            with open(path, "rb") as f:
                self.rom_data = f.read()
            self.rom_loaded = True
            return True
        except Exception as e:
            messagebox.showerror("Load Error", f"Could not load ROM: {e}")
            return False

    def reset(self):
        self.cpu.reset()

    def step_frame(self):
        if not self.rom_loaded:
            # show placeholder pattern
            return self.ppu.render_frame()
        else:
            # TODO: actual emulation
            return self.ppu.render_frame()


# ───────────────────────────────────────────────
# GUI
# ───────────────────────────────────────────────
class EmulatorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Cat's FCEUX 0.2 - Homebrew Emulator")
        self.root.geometry("512x480")

        self.nes = NESBackend()
        self.canvas = tk.Canvas(root, width=512, height=480, bg="black")
        self.canvas.pack()

        self.menu = Menu(root)
        file_menu = Menu(self.menu, tearoff=0)
        file_menu.add_command(label="Load ROM", command=self.load_rom)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=root.quit)
        self.menu.add_cascade(label="File", menu=file_menu)
        root.config(menu=self.menu)

        self.image_ref = None
        self.root.after(16, self.update_frame)

    def load_rom(self):
        path = filedialog.askopenfilename(
            title="Open NES ROM",
            filetypes=[("NES files", "*.nes"), ("All files", "*.*")]
        )
        if path and self.nes.load_rom(path):
            self.nes.reset()

    def update_frame(self):
        frame = self.nes.step_frame()
        img = Image.fromarray(frame, 'RGB').resize((512, 480))
        self.image_ref = ImageTk.PhotoImage(img)
        self.canvas.create_image(0, 0, anchor="nw", image=self.image_ref)
        self.root.after(16, self.update_frame)


# ───────────────────────────────────────────────
# Entry Point
# ───────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()
    EmulatorGUI(root)
    root.mainloop()
