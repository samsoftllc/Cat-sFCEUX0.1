c
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
