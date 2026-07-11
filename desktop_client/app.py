import tkinter as tk
from tkinter import ttk
import queue
import mss
from PIL import Image, ImageTk
import keyboard
import threading
from api_client import translate_image

SOURCE_LANGUAGES = {
    "Inglês": "en",
}

TARGET_LANGUAGES = {
    "Português": "pt-BR",
    "Inglês": "en",
}

POSITIONS = [
    "Perto do mouse",
    "Topo da tela",
    "Rodapé da tela",
    "Centro da tela"
]

class SnippingTool:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("G.R.C TRANSLATOR")
        self.root.geometry("350x250")
        self.root.resizable(False, False)
        
        # Keep window on top (optional, user can minimize)
        self.root.attributes('-topmost', True)

        self.result_window = None
        self.snip_window = None
        self._ui_events = queue.Queue()
        self._request_id = 0
        self._closing = False
        self.monitor_left = 0
        self.monitor_top = 0
        self.monitor_width = 0
        self.monitor_height = 0
        
        self.setup_ui()
        self._hotkey = keyboard.add_hotkey('ctrl+shift+q', self.on_hotkey)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(50, self.process_ui_events)
        
        self.root.mainloop()

    def setup_ui(self):
        frame = tk.Frame(self.root, padx=20, pady=20)
        frame.pack(fill="both", expand=True)

        # Source Language
        tk.Label(frame, text="Idioma do Jogo (OCR em inglês):", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.source_var = tk.StringVar(value="Inglês")
        self.source_cb = ttk.Combobox(frame, textvariable=self.source_var, values=list(SOURCE_LANGUAGES.keys()), state="readonly")
        self.source_cb.pack(fill="x", pady=(0, 10))

        # Target Language
        tk.Label(frame, text="Traduzir para:", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.target_var = tk.StringVar(value="Português")
        self.target_cb = ttk.Combobox(frame, textvariable=self.target_var, values=list(TARGET_LANGUAGES.keys()), state="readonly")
        self.target_cb.pack(fill="x", pady=(0, 10))

        # Position
        tk.Label(frame, text="Posição da Tradução:", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.position_var = tk.StringVar(value="Perto do mouse")
        self.position_cb = ttk.Combobox(frame, textvariable=self.position_var, values=POSITIONS, state="readonly")
        self.position_cb.pack(fill="x", pady=(0, 15))

        # Info
        info_label = tk.Label(frame, text="Aperte Ctrl+Shift+Q para capturar!", fg="gray", font=("Segoe UI", 9))
        info_label.pack(side="bottom")

    def on_hotkey(self):
        if not self._closing:
            self._ui_events.put(("start_snip",))

    def process_ui_events(self):
        while True:
            try:
                event = self._ui_events.get_nowait()
            except queue.Empty:
                break

            if event[0] == "start_snip":
                self.start_snip()
            elif event[0] == "translation_result":
                _, request_id, result, x, y, position = event
                if request_id == self._request_id:
                    self.show_translation(result, x, y, position)

        if not self._closing:
            self.root.after(50, self.process_ui_events)

    @staticmethod
    def window_exists(window):
        try:
            return window is not None and bool(window.winfo_exists())
        except tk.TclError:
            return False

    def start_snip(self):
        if self._closing or self.window_exists(self.snip_window):
            return

        self._request_id += 1
        try:
            with mss.mss() as sct:
                monitor = sct.monitors[1]
                self.monitor_left = monitor["left"]
                self.monitor_top = monitor["top"]
                self.monitor_width = monitor["width"]
                self.monitor_height = monitor["height"]
                screenshot = sct.grab(monitor)
                self.img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
        except (OSError, mss.exception.ScreenShotError):
            self.monitor_left = 0
            self.monitor_top = 0
            self.monitor_width = self.root.winfo_screenwidth()
            self.monitor_height = self.root.winfo_screenheight()
            self.show_translation("Não foi possível capturar a tela.", 20, 20, "Perto do mouse")
            return

        window = tk.Toplevel(self.root)
        self.snip_window = window
        window.overrideredirect(True)
        window.geometry(self.geometry_at(self.monitor_left, self.monitor_top, self.monitor_width, self.monitor_height))
        window.attributes("-topmost", True)
        window.configure(cursor="cross")
        window.focus_force()

        window.bind("<ButtonPress-1>", self.on_press)
        window.bind("<B1-Motion>", self.on_drag)
        window.bind("<ButtonRelease-1>", self.on_release)
        window.bind("<Escape>", lambda _event: self.cancel_snip())

        self.canvas = tk.Canvas(window, width=self.monitor_width, height=self.monitor_height, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        dark_img = Image.new("RGBA", self.img.size, (0, 0, 0, 100))
        self.display_img = Image.alpha_composite(self.img.convert("RGBA"), dark_img)
        self.tk_img = ImageTk.PhotoImage(self.display_img)
        self.canvas.create_image(0, 0, anchor="nw", image=self.tk_img)
        self.rect_item = None
        self.start_x = 0
        self.start_y = 0

    @staticmethod
    def geometry_at(x, y, width, height):
        x_part = f"+{x}" if x >= 0 else str(x)
        y_part = f"+{y}" if y >= 0 else str(y)
        return f"{width}x{height}{x_part}{y_part}"

    def cancel_snip(self):
        window = self.snip_window
        self.snip_window = None
        if self.window_exists(window):
            window.destroy()

    def on_press(self, event):
        if not self.window_exists(self.snip_window):
            return
        self.start_x = event.x
        self.start_y = event.y
        if self.rect_item:
            self.canvas.delete(self.rect_item)
        self.rect_item = self.canvas.create_rectangle(self.start_x, self.start_y, self.start_x, self.start_y, outline="red", width=2)
        
    def on_drag(self, event):
        if self.rect_item:
            self.canvas.coords(self.rect_item, self.start_x, self.start_y, event.x, event.y)
        
    def on_release(self, event):
        if not self.window_exists(self.snip_window):
            return

        end_x = event.x
        end_y = event.y
        x1 = min(self.start_x, end_x)
        y1 = min(self.start_y, end_y)
        x2 = max(self.start_x, end_x)
        y2 = max(self.start_y, end_y)
        request_id = self._request_id
        self.cancel_snip()

        if x2 - x1 > 10 and y2 - y1 > 10:
            cropped = self.img.crop((x1, y1, x2, y2))
            source_code = SOURCE_LANGUAGES.get(self.source_var.get(), "en")
            target_code = TARGET_LANGUAGES.get(self.target_var.get(), "pt-BR")
            position = self.position_var.get()
            anchor_x = self.monitor_left + x2
            anchor_y = self.monitor_top + y2

            self.show_translation("Traduzindo...", anchor_x, anchor_y, position)
            worker = threading.Thread(
                target=self.translate_in_background,
                args=(request_id, cropped, source_code, target_code, anchor_x, anchor_y, position),
                daemon=True,
            )
            worker.start()

    def translate_in_background(self, request_id, cropped, source_code, target_code, x, y, position):
        try:
            result = translate_image(
                cropped,
                source_lang=source_code,
                target_lang=target_code,
                request_id=request_id,
            )
        except Exception:
            result = "Ocorreu um erro inesperado ao traduzir a imagem."
        self._ui_events.put(("translation_result", request_id, result, x, y, position))

    def show_translation(self, text, x, y, position):
        self.close_result_window()

        result_window = tk.Toplevel(self.root)
        self.result_window = result_window
        result_window.overrideredirect(True)
        result_window.attributes("-topmost", True)

        label = tk.Label(result_window, text=text, bg="#2b2b2b", fg="white", 
                         font=("Segoe UI", 14), padx=20, pady=15, wraplength=500, 
                         justify="center", relief="solid", borderwidth=2)
        label.pack()

        result_window.update_idletasks()
        win_width = result_window.winfo_width()
        win_height = result_window.winfo_height()
        monitor_left = self.monitor_left
        monitor_top = self.monitor_top
        monitor_width = self.monitor_width or self.root.winfo_screenwidth()
        monitor_height = self.monitor_height or self.root.winfo_screenheight()

        if position == "Topo da tela":
            pos_x = monitor_left + (monitor_width - win_width) // 2
            pos_y = monitor_top + 20
        elif position == "Rodapé da tela":
            pos_x = monitor_left + (monitor_width - win_width) // 2
            pos_y = monitor_top + monitor_height - win_height - 60
        elif position == "Centro da tela":
            pos_x = monitor_left + (monitor_width - win_width) // 2
            pos_y = monitor_top + (monitor_height - win_height) // 2
        else:
            pos_x = x + 10
            pos_y = y + 10
        max_x = max(monitor_left, monitor_left + monitor_width - win_width - 10)
        max_y = max(monitor_top, monitor_top + monitor_height - win_height - 10)
        pos_x = min(max(pos_x, monitor_left), max_x)
        pos_y = min(max(pos_y, monitor_top), max_y)
        result_window.geometry(self.geometry_at(pos_x, pos_y, win_width, win_height))

        label.bind("<Button-1>", lambda _event: self.close_result_window(result_window))
        result_window.after(15000, lambda: self.close_result_window(result_window))

    def close_result_window(self, window=None):
        target = window or self.result_window
        if self.window_exists(target):
            target.destroy()
        if self.result_window is target:
            self.result_window = None

    def on_close(self):
        self._closing = True
        self._request_id += 1
        try:
            keyboard.remove_hotkey(self._hotkey)
        except (KeyError, ValueError):
            pass
        self.cancel_snip()
        self.close_result_window()
        self.root.destroy()

if __name__ == "__main__":
    SnippingTool()
