import tkinter as tk
from tkinter import ttk, messagebox
import threading
import struct
import time
import ipaddress
import json
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs
from datetime import datetime

try:
    import websocket
except ImportError:
    websocket = None


# ============================================================
# ATR-1000 PROTOCOL
# ============================================================

TUNER_PORT = 60001
SCMD_SYNC = 1
SCMD_METER_STATUS = 2
SCMD_RELAY_STATUS = 5


# ============================================================
# APPLICATION
# ============================================================

class ProtectionMonitor:
    def __init__(self, root):
        self.root = root
        self.root.title("ATR-1000 / TCI Protection Monitor")
        self.root.geometry("730x980")
        self.root.minsize(660, 820)

        self.app_closing = threading.Event()

        # ATR connection state
        self.tuner_stop = threading.Event()
        self.tuner_ws = None
        self.tuner_worker = None

        # TCI connection state
        self.tci_stop = threading.Event()
        self.tci_ws = None
        self.tci_worker = None
        self.tci_send_lock = threading.Lock()

        # ----------------------------
        # User settings
        # ----------------------------
        self.tuner_ip_var = tk.StringVar(value="192.168.1.238")

        self.radio_ip_var = tk.StringVar(value="127.0.0.1")
        self.radio_port_var = tk.IntVar(value=50001)

        self.auto_protection_enabled = tk.BooleanVar(value=False)
        self.swr_protection_enabled = tk.BooleanVar(value=True)
        self.swr_limit_var = tk.DoubleVar(value=3.0)
        self.safe_drive_var = tk.IntVar(value=10)

        # ----------------------------
        # ATR live state
        # ----------------------------
        self.tuner_connection_var = tk.StringVar(value="DISCONNECTED")
        self.tuner_state_var = tk.StringVar(value="UNKNOWN")
        self.swr_var = tk.StringVar(value="--")
        self.power_var = tk.StringVar(value="-- W")
        self.network_var = tk.StringVar(value="--")
        self.inductance_var = tk.StringVar(value="-- uH")
        self.capacitance_var = tk.StringVar(value="-- pF")
        self.tuner_update_var = tk.StringVar(value="Never")

        self.current_swr = None
        self.current_power = 0
        self.current_tuner_state = "UNKNOWN"

        # ----------------------------
        # TCI live state
        # ----------------------------
        self.tci_connection_var = tk.StringVar(value="DISCONNECTED")
        self.radio_device_var = tk.StringVar(value="--")
        self.radio_protocol_var = tk.StringVar(value="--")
        self.radio_tx_var = tk.StringVar(value="UNKNOWN")
        self.radio_tune_var = tk.StringVar(value="UNKNOWN")
        self.radio_drive_var = tk.StringVar(value="--")
        self.radio_update_var = tk.StringVar(value="Never")

        self.tci_connected = False
        self.radio_tx_active = False
        self.radio_tune_active = None
        self.radio_drive = None

        # Protection state
        self.protection_var = tk.StringVar(value="DISARMED")
        self.last_action_var = tk.StringVar(value="None")
        self.message_var = tk.StringVar(value="Ready")

        # ----------------------------
        # Web server
        # ----------------------------
        self.web_port_var = tk.IntVar(value=8080)
        self.web_status_var = tk.StringVar(value="STOPPED")
        self.web_url_var = tk.StringVar(value="--")
        self.web_server = None
        self.web_thread = None

        # Avoid repeated command spam for the same condition
        self.bypass_action_sent = False
        self.swr_trip_action_sent = False

        self.build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        if websocket is None:
            messagebox.showwarning(
                "Missing package",
                "The websocket-client package is not installed.\n\n"
                "Run:\n\npip install websocket-client"
            )
            self.tuner_connect_button.configure(state="disabled")
            self.tci_connect_button.configure(state="disabled")

        self.evaluate_protection()

    # ========================================================
    # UI
    # ========================================================

    def build_ui(self):
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)

        ttk.Label(
            outer,
            text="ATR-1000 / TCI Protection Monitor",
            font=("Segoe UI", 18, "bold")
        ).pack(pady=(0, 10))

        tuner_conn = ttk.LabelFrame(
            outer, text="ATR-1000 Connection", padding=10
        )
        tuner_conn.pack(fill="x")

        ttk.Label(tuner_conn, text="Tuner IP:").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )

        self.tuner_ip_entry = ttk.Entry(
            tuner_conn,
            textvariable=self.tuner_ip_var,
            width=20
        )
        self.tuner_ip_entry.grid(row=0, column=1, sticky="ew")

        self.tuner_connect_button = ttk.Button(
            tuner_conn,
            text="Connect",
            command=self.connect_tuner
        )
        self.tuner_connect_button.grid(row=0, column=2, padx=(8, 4))

        self.tuner_disconnect_button = ttk.Button(
            tuner_conn,
            text="Disconnect",
            command=self.disconnect_tuner_clicked,
            state="disabled"
        )
        self.tuner_disconnect_button.grid(row=0, column=3, padx=4)

        tuner_conn.columnconfigure(1, weight=1)

        tuner_status = ttk.LabelFrame(
            outer, text="Tuner Status", padding=10
        )
        tuner_status.pack(fill="x", pady=(10, 0))

        self.tuner_connection_label = self.add_row(
            tuner_status, 0, "Connection", self.tuner_connection_var
        )
        self.tuner_state_label = self.add_row(
            tuner_status, 1, "Tuner state", self.tuner_state_var
        )
        self.swr_label = self.add_row(
            tuner_status, 2, "SWR", self.swr_var
        )
        self.add_row(tuner_status, 3, "Forward power", self.power_var)
        self.add_row(tuner_status, 4, "Network", self.network_var)
        self.add_row(tuner_status, 5, "Inductance", self.inductance_var)
        self.add_row(tuner_status, 6, "Capacitance", self.capacitance_var)
        self.add_row(tuner_status, 7, "Last update", self.tuner_update_var)

        tci_conn = ttk.LabelFrame(
            outer, text="Radio TCI Connection", padding=10
        )
        tci_conn.pack(fill="x", pady=(10, 0))

        ttk.Label(tci_conn, text="Radio IP:").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )

        self.radio_ip_entry = ttk.Entry(
            tci_conn,
            textvariable=self.radio_ip_var,
            width=18
        )
        self.radio_ip_entry.grid(row=0, column=1, sticky="ew")

        ttk.Label(tci_conn, text="Port:").grid(
            row=0, column=2, sticky="e", padx=(10, 4)
        )

        self.radio_port_entry = ttk.Entry(
            tci_conn,
            textvariable=self.radio_port_var,
            width=8
        )
        self.radio_port_entry.grid(row=0, column=3)

        self.tci_connect_button = ttk.Button(
            tci_conn,
            text="Connect",
            command=self.connect_tci
        )
        self.tci_connect_button.grid(row=0, column=4, padx=(8, 4))

        self.tci_disconnect_button = ttk.Button(
            tci_conn,
            text="Disconnect",
            command=self.disconnect_tci_clicked,
            state="disabled"
        )
        self.tci_disconnect_button.grid(row=0, column=5, padx=4)

        tci_conn.columnconfigure(1, weight=1)

        radio_status = ttk.LabelFrame(
            outer, text="Radio Status", padding=10
        )
        radio_status.pack(fill="x", pady=(10, 0))

        self.tci_connection_label = self.add_row(
            radio_status, 0, "TCI connection", self.tci_connection_var
        )
        self.add_row(radio_status, 1, "Protocol", self.radio_protocol_var)
        self.add_row(radio_status, 2, "Device", self.radio_device_var)
        self.radio_tx_label = self.add_row(
            radio_status, 3, "TX state", self.radio_tx_var
        )
        self.radio_tune_label = self.add_row(
            radio_status, 4, "Tune state", self.radio_tune_var
        )
        self.add_row(radio_status, 5, "Drive", self.radio_drive_var)
        self.add_row(radio_status, 6, "Last update", self.radio_update_var)

        self.tune_button = ttk.Button(
            radio_status,
            text="TUNE ON",
            command=self.toggle_radio_tune,
            state="disabled"
        )
        self.tune_button.grid(
            row=7, column=0, columnspan=4,
            sticky="ew", pady=(8, 2)
        )

        protect = ttk.LabelFrame(
            outer, text="Protection Settings", padding=10
        )
        protect.pack(fill="x", pady=(10, 0))

        self.auto_check = ttk.Checkbutton(
            protect,
            text="Enable automatic radio protection",
            variable=self.auto_protection_enabled,
            command=self.evaluate_protection
        )
        self.auto_check.grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 8)
        )

        ttk.Label(protect, text="BYPASS safe drive:").grid(
            row=1, column=0, sticky="w"
        )

        self.safe_drive_spin = ttk.Spinbox(
            protect,
            from_=0,
            to=100,
            increment=1,
            textvariable=self.safe_drive_var,
            width=7,
            command=self.evaluate_protection
        )
        self.safe_drive_spin.grid(row=1, column=1, sticky="w", padx=(8, 4))

        ttk.Label(
            protect,
            text="%  (TCI drive setting — not guaranteed watts)"
        ).grid(row=1, column=2, columnspan=2, sticky="w")

        self.swr_check = ttk.Checkbutton(
            protect,
            text="Enable high-SWR emergency TX stop",
            variable=self.swr_protection_enabled,
            command=self.evaluate_protection
        )
        self.swr_check.grid(
            row=2, column=0, columnspan=4, sticky="w", pady=(8, 4)
        )

        ttk.Label(protect, text="Stop TX if SWR exceeds:").grid(
            row=3, column=0, sticky="w"
        )

        self.swr_limit_spin = ttk.Spinbox(
            protect,
            from_=1.1,
            to=10.0,
            increment=0.1,
            textvariable=self.swr_limit_var,
            width=7,
            command=self.evaluate_protection
        )
        self.swr_limit_spin.grid(row=3, column=1, sticky="w", padx=(8, 4))

        ttk.Label(protect, text=": 1").grid(
            row=3, column=2, sticky="w"
        )

        self.protection_label = self.add_row(
            protect, 4, "Protection state", self.protection_var
        )
        self.add_row(
            protect, 5, "Last protection action", self.last_action_var
        )

        self.safe_drive_spin.bind(
            "<FocusOut>", lambda e: self.evaluate_protection()
        )
        self.safe_drive_spin.bind(
            "<Return>", lambda e: self.evaluate_protection()
        )
        self.swr_limit_spin.bind(
            "<FocusOut>", lambda e: self.evaluate_protection()
        )
        self.swr_limit_spin.bind(
            "<Return>", lambda e: self.evaluate_protection()
        )

        web_frame = ttk.LabelFrame(
            outer, text="Simple Web Control", padding=10
        )
        web_frame.pack(fill="x", pady=(10, 0))

        ttk.Label(web_frame, text="Port:").grid(
            row=0, column=0, sticky="w"
        )

        self.web_port_entry = ttk.Entry(
            web_frame,
            textvariable=self.web_port_var,
            width=8
        )
        self.web_port_entry.grid(row=0, column=1, sticky="w", padx=(6, 14))

        self.web_start_button = ttk.Button(
            web_frame, text="Start Web Server", command=self.start_web_server
        )
        self.web_start_button.grid(row=0, column=2, padx=4)

        self.web_stop_button = ttk.Button(
            web_frame, text="Stop", command=self.stop_web_server, state="disabled"
        )
        self.web_stop_button.grid(row=0, column=3, padx=4)

        self.web_status_label = self.add_row(
            web_frame, 1, "Web server", self.web_status_var
        )
        self.add_row(
            web_frame, 2, "Web address", self.web_url_var
        )

        ttk.Label(
            web_frame,
            text=(
                "No login is required. Use this page only on your trusted closed internal network; "
                "do not port-forward this HTTP server to the public internet."
            ),
            wraplength=650,
            justify="left",
            font=("Segoe UI", 9)
        ).grid(row=3, column=0, columnspan=4, sticky="w", pady=(6, 0))

        web_frame.columnconfigure(3, weight=1)

        ttk.Label(
            outer,
            text=(
                "Behaviour: BYPASS lowers TCI drive to the selected safe value. "
                "High SWR immediately sends TCI RX/TX-off commands. "
                "The program never automatically raises drive again after a protection action."
            ),
            wraplength=680,
            justify="left",
            font=("Segoe UI", 9)
        ).pack(fill="x", pady=(10, 4))

        ttk.Label(
            outer,
            textvariable=self.message_var,
            wraplength=680,
            justify="left",
            font=("Segoe UI", 9)
        ).pack(fill="x", pady=(4, 0))

    def add_row(self, parent, row, name, variable):
        ttk.Label(
            parent,
            text=name + ":",
            font=("Segoe UI", 10)
        ).grid(row=row, column=0, sticky="w", padx=(0, 16), pady=2)

        label = ttk.Label(
            parent,
            textvariable=variable,
            font=("Segoe UI", 10, "bold")
        )
        label.grid(
            row=row, column=1, columnspan=3,
            sticky="w", pady=2
        )

        parent.columnconfigure(1, weight=1)
        return label

    def safe_ui(self, func, *args):
        if not self.app_closing.is_set():
            try:
                self.root.after(0, func, *args)
            except tk.TclError:
                pass

    def set_message(self, text):
        self.message_var.set(text)

    def valid_ip(self, value, title):
        value = value.strip()
        try:
            ipaddress.ip_address(value)
        except ValueError:
            messagebox.showerror(
                title,
                f"'{value}' is not a valid IP address."
            )
            return None
        return value

    def connect_tuner(self):
        if websocket is None:
            return

        ip = self.valid_ip(
            self.tuner_ip_var.get(),
            "Invalid tuner IP"
        )
        if ip is None:
            return

        self.disconnect_tuner(False)
        self.tuner_stop = threading.Event()

        self.current_swr = None
        self.current_tuner_state = "UNKNOWN"
        self.bypass_action_sent = False
        self.swr_trip_action_sent = False

        self.tuner_connection_var.set("CONNECTING...")
        self.tuner_connection_label.configure(foreground="dark orange")
        self.tuner_ip_entry.configure(state="disabled")
        self.tuner_connect_button.configure(state="disabled")
        self.tuner_disconnect_button.configure(state="normal")

        self.tuner_worker = threading.Thread(
            target=self.tuner_loop,
            args=(ip, self.tuner_stop),
            daemon=True
        )
        self.tuner_worker.start()

    def disconnect_tuner_clicked(self):
        self.disconnect_tuner(False)
        self.set_tuner_connected(False, "Tuner disconnected by user")

    def disconnect_tuner(self, wait=False):
        self.tuner_stop.set()

        ws = self.tuner_ws
        self.tuner_ws = None

        if ws:
            try:
                ws.close()
            except Exception:
                pass

        if wait and self.tuner_worker and self.tuner_worker.is_alive():
            self.tuner_worker.join(timeout=2)

    def set_tuner_connected(self, connected, message=None):
        if connected:
            self.tuner_connection_var.set("CONNECTED")
            self.tuner_connection_label.configure(foreground="green")
            self.tuner_ip_entry.configure(state="disabled")
            self.tuner_connect_button.configure(state="disabled")
            self.tuner_disconnect_button.configure(state="normal")
        else:
            self.tuner_connection_var.set("DISCONNECTED")
            self.tuner_connection_label.configure(foreground="red")
            self.current_tuner_state = "UNKNOWN"
            self.tuner_state_var.set("UNKNOWN")
            self.tuner_state_label.configure(foreground="dark orange")
            self.tuner_ip_entry.configure(state="normal")
            self.tuner_connect_button.configure(state="normal")
            self.tuner_disconnect_button.configure(state="disabled")

        if message:
            self.set_message(message)

        self.evaluate_protection()

    def tuner_send_sync(self):
        ws = self.tuner_ws
        if ws:
            ws.send_binary(bytes([0xFF, SCMD_SYNC, 0x00]))

    def tuner_loop(self, ip, stop_event):
        url = f"ws://{ip}:{TUNER_PORT}/"

        try:
            ws = websocket.create_connection(url, timeout=2)

            if stop_event.is_set():
                ws.close()
                return

            self.tuner_ws = ws
            self.safe_ui(
                self.set_tuner_connected,
                True,
                f"ATR-1000 connected at {ip}:{TUNER_PORT}"
            )

            self.tuner_send_sync()
            last_sync = time.monotonic()

            while not stop_event.is_set():
                try:
                    data = ws.recv()

                    if data:
                        self.process_tuner_packet(data)

                    if time.monotonic() - last_sync >= 2:
                        self.tuner_send_sync()
                        last_sync = time.monotonic()

                except websocket.WebSocketTimeoutException:
                    self.tuner_send_sync()
                    last_sync = time.monotonic()

        except Exception as error:
            if not stop_event.is_set():
                self.safe_ui(
                    self.set_tuner_connected,
                    False,
                    f"ATR-1000 connection failed: {error}"
                )

        finally:
            try:
                if self.tuner_ws:
                    self.tuner_ws.close()
            except Exception:
                pass

            self.tuner_ws = None

            if not stop_event.is_set():
                self.safe_ui(self.set_tuner_connected, False)

    def process_tuner_packet(self, data):
        if not isinstance(data, bytes) or len(data) < 3:
            return

        if data[0] != 0xFF:
            return

        cmd = data[1]

        if cmd == SCMD_RELAY_STATUS and len(data) >= 10:
            network = data[3]
            relay_l = data[4]
            relay_c = data[5]

            inductance = struct.unpack_from("<H", data, 6)[0] / 100
            capacitance = struct.unpack_from("<H", data, 8)[0]

            state = "TUNED" if (relay_l > 0 or relay_c > 0) else "BYPASS"
            self.current_tuner_state = state

            self.safe_ui(self.update_tuner_state, state)
            self.safe_ui(
                self.network_var.set,
                "LC" if network == 0 else "CL"
            )
            self.safe_ui(
                self.inductance_var.set,
                f"{inductance:g} uH"
            )
            self.safe_ui(
                self.capacitance_var.set,
                f"{capacitance} pF"
            )
            self.safe_ui(
                self.tuner_update_var.set,
                datetime.now().strftime("%H:%M:%S")
            )
            self.safe_ui(self.evaluate_protection)

        elif cmd == SCMD_METER_STATUS and len(data) >= 10:
            swr_raw = struct.unpack_from("<H", data, 4)[0]
            forward = struct.unpack_from("<H", data, 6)[0]

            swr = swr_raw / 100.0 if swr_raw >= 100 else float(swr_raw)

            self.current_swr = swr
            self.current_power = forward

            swr_text = f"{swr:.2f}" if swr_raw >= 100 else str(swr_raw)

            self.safe_ui(self.swr_var.set, swr_text)
            self.safe_ui(self.power_var.set, f"{forward} W")
            self.safe_ui(
                self.tuner_update_var.set,
                datetime.now().strftime("%H:%M:%S")
            )
            self.safe_ui(self.evaluate_protection)

    def update_tuner_state(self, state):
        self.tuner_state_var.set(state)

        if state == "TUNED":
            self.tuner_state_label.configure(foreground="green")
        elif state == "BYPASS":
            self.tuner_state_label.configure(foreground="red")
        else:
            self.tuner_state_label.configure(foreground="dark orange")

    def connect_tci(self):
        if websocket is None:
            return

        ip = self.valid_ip(
            self.radio_ip_var.get(),
            "Invalid radio IP"
        )
        if ip is None:
            return

        try:
            port = int(self.radio_port_var.get())
            if not 1 <= port <= 65535:
                raise ValueError
        except Exception:
            messagebox.showerror(
                "Invalid TCI port",
                "TCI port must be between 1 and 65535."
            )
            return

        self.disconnect_tci(False)
        self.tci_stop = threading.Event()

        self.tci_connection_var.set("CONNECTING...")
        self.tci_connection_label.configure(foreground="dark orange")
        self.radio_ip_entry.configure(state="disabled")
        self.radio_port_entry.configure(state="disabled")
        self.tci_connect_button.configure(state="disabled")
        self.tci_disconnect_button.configure(state="normal")

        self.tci_worker = threading.Thread(
            target=self.tci_loop,
            args=(ip, port, self.tci_stop),
            daemon=True
        )
        self.tci_worker.start()

    def disconnect_tci_clicked(self):
        self.disconnect_tci(False)
        self.set_tci_connected(False, "TCI disconnected by user")

    def disconnect_tci(self, wait=False):
        self.tci_stop.set()

        ws = self.tci_ws
        self.tci_ws = None

        if ws:
            try:
                ws.close()
            except Exception:
                pass

        if wait and self.tci_worker and self.tci_worker.is_alive():
            self.tci_worker.join(timeout=2)

    def set_tci_connected(self, connected, message=None):
        self.tci_connected = connected

        if connected:
            self.tci_connection_var.set("CONNECTED")
            self.tci_connection_label.configure(foreground="green")
            self.radio_ip_entry.configure(state="disabled")
            self.radio_port_entry.configure(state="disabled")
            self.tci_connect_button.configure(state="disabled")
            self.tci_disconnect_button.configure(state="normal")
            self.tune_button.configure(state="disabled")
        else:
            self.tci_connection_var.set("DISCONNECTED")
            self.tci_connection_label.configure(foreground="red")
            self.radio_tx_var.set("UNKNOWN")
            self.radio_tx_label.configure(foreground="dark orange")
            self.radio_tune_active = None
            self.radio_tune_var.set("UNKNOWN")
            self.radio_tune_label.configure(foreground="dark orange")
            self.tune_button.configure(text="TUNE ON", state="disabled")
            self.radio_ip_entry.configure(state="normal")
            self.radio_port_entry.configure(state="normal")
            self.tci_connect_button.configure(state="normal")
            self.tci_disconnect_button.configure(state="disabled")

        if message:
            self.set_message(message)

        self.evaluate_protection()

    def tci_loop(self, ip, port, stop_event):
        url = f"ws://{ip}:{port}/"

        try:
            ws = websocket.create_connection(url, timeout=3)

            if stop_event.is_set():
                ws.close()
                return

            self.tci_ws = ws
            self.safe_ui(
                self.set_tci_connected,
                True,
                f"TCI connected at {ip}:{port}"
            )

            while not stop_event.is_set():
                try:
                    message = ws.recv()
                    if message:
                        self.process_tci_message(message)
                except websocket.WebSocketTimeoutException:
                    continue

        except Exception as error:
            if not stop_event.is_set():
                self.safe_ui(
                    self.set_tci_connected,
                    False,
                    f"TCI connection failed: {error}"
                )

        finally:
            try:
                if self.tci_ws:
                    self.tci_ws.close()
            except Exception:
                pass

            self.tci_ws = None

            if not stop_event.is_set():
                self.safe_ui(self.set_tci_connected, False)

    def process_tci_message(self, message):
        if isinstance(message, bytes):
            try:
                message = message.decode("utf-8", errors="ignore")
            except Exception:
                return

        for item in message.split(";"):
            item = item.strip()
            if not item:
                continue

            if item.startswith("protocol:"):
                value = item.split(":", 1)[1]
                self.safe_ui(self.radio_protocol_var.set, value)

            elif item.startswith("device:"):
                value = item.split(":", 1)[1]
                self.safe_ui(self.radio_device_var.set, value)

            elif item.startswith("drive:"):
                try:
                    payload = item.split(":", 1)[1]
                    rx_text, drive_text = payload.split(",", 1)
                    rx = int(rx_text)
                    drive = int(float(drive_text))

                    if rx == 0:
                        self.radio_drive = drive
                        self.safe_ui(
                            self.radio_drive_var.set,
                            f"{drive}%"
                        )
                except Exception:
                    pass

            elif item.startswith("trx:"):
                try:
                    payload = item.split(":", 1)[1]
                    parts = payload.split(",")
                    rx = int(parts[0])
                    active = parts[1].lower() == "true"

                    if rx == 0:
                        self.radio_tx_active = active
                        self.safe_ui(
                            self.set_radio_tx_state,
                            active
                        )
                except Exception:
                    pass

            elif item.startswith("tune:"):
                try:
                    payload = item.split(":", 1)[1]
                    parts = payload.split(",")
                    rx = int(parts[0])
                    active = parts[1].lower() == "true"

                    if rx == 0:
                        self.radio_tune_active = active
                        self.safe_ui(
                            self.set_radio_tune_state,
                            active
                        )
                except Exception:
                    pass

            self.safe_ui(
                self.radio_update_var.set,
                datetime.now().strftime("%H:%M:%S")
            )

    def set_radio_tx_state(self, active):
        self.radio_tx_var.set("TRANSMITTING" if active else "RECEIVE")
        self.radio_tx_label.configure(
            foreground="red" if active else "green"
        )

    def set_radio_tune_state(self, active):
        self.radio_tune_active = active
        self.radio_tune_var.set("ON" if active else "OFF")
        self.radio_tune_label.configure(
            foreground="red" if active else "green"
        )
        self.tune_button.configure(
            text="TUNE OFF" if active else "TUNE ON",
            state="normal" if self.tci_connected else "disabled"
        )

    def toggle_radio_tune(self):
        if not self.tci_connected:
            self.set_message("Cannot toggle Tune: TCI is not connected.")
            return False

        if self.radio_tune_active is None:
            self.set_message(
                "Cannot toggle Tune yet: waiting for the radio to report its Tune state."
            )
            return False

        new_state = not self.radio_tune_active
        command = f"tune:0,{str(new_state).lower()};"

        if self.tci_send(command):
            self.set_message(
                "TCI Tune command sent: " + ("ON" if new_state else "OFF")
            )
            self.tune_button.configure(state="disabled")
            return True

        return False

    def tci_send(self, command):
        ws = self.tci_ws

        if not self.tci_connected or ws is None:
            return False

        try:
            with self.tci_send_lock:
                ws.send(command)
            return True
        except Exception as error:
            self.safe_ui(
                self.set_message,
                f"TCI send failed: {error}"
            )
            return False

    def send_safe_drive(self, drive):
        ok0 = self.tci_send(f"drive:0,{drive};")
        ok1 = self.tci_send(f"drive:1,{drive};")

        if ok0 or ok1:
            self.last_action_var.set(
                f"Reduced radio drive to {drive}% because tuner is BYPASS"
            )
            self.set_message(
                f"Protection action: tuner BYPASS — radio drive commanded to {drive}%."
            )
            return True

        return False

    def emergency_stop_tx(self, reason):
        commands = [
            "trx:0,false;",
            "tune:0,false;",
            "trx:1,false;",
            "tune:1,false;",
        ]

        sent_any = False
        for command in commands:
            if self.tci_send(command):
                sent_any = True

        if sent_any:
            self.set_radio_tune_state(False)
            self.last_action_var.set(
                f"EMERGENCY TX STOP — {reason}"
            )
            self.set_message(
                f"EMERGENCY PROTECTION: {reason}. "
                "TCI commands sent to stop TX and Tune."
            )
            return True

        return False

    def get_safe_drive(self):
        try:
            value = int(self.safe_drive_var.get())
        except Exception:
            return None
        return max(0, min(100, value))

    def get_swr_limit(self):
        try:
            value = float(self.swr_limit_var.get())
        except Exception:
            return None
        return max(1.1, min(10.0, value))

    def evaluate_protection(self):
        if not self.auto_protection_enabled.get():
            self.protection_var.set("DISARMED")
            self.protection_label.configure(foreground="gray")
            self.bypass_action_sent = False
            self.swr_trip_action_sent = False
            return

        safe_drive = self.get_safe_drive()
        swr_limit = self.get_swr_limit()

        if safe_drive is None:
            self.protection_var.set("INVALID SAFE DRIVE")
            self.protection_label.configure(foreground="red")
            return

        if swr_limit is None:
            self.protection_var.set("INVALID SWR LIMIT")
            self.protection_label.configure(foreground="red")
            return

        if not self.tci_connected:
            self.protection_var.set("ARMED BUT TCI NOT CONNECTED")
            self.protection_label.configure(foreground="dark orange")
            return

        if (
            self.swr_protection_enabled.get()
            and self.current_swr is not None
            and self.current_swr > 0
            and self.current_swr > swr_limit
        ):
            self.protection_var.set(
                f"EMERGENCY TX STOP — SWR {self.current_swr:.2f}:1"
            )
            self.protection_label.configure(foreground="red")

            if not self.swr_trip_action_sent:
                if self.emergency_stop_tx(
                    f"SWR {self.current_swr:.2f}:1 > {swr_limit:.1f}:1"
                ):
                    self.swr_trip_action_sent = True

            return
        else:
            self.swr_trip_action_sent = False

        if self.current_tuner_state == "BYPASS":
            self.protection_var.set(
                f"BYPASS — REDUCE DRIVE TO {safe_drive}%"
            )
            self.protection_label.configure(foreground="dark orange")

            if not self.bypass_action_sent:
                if self.send_safe_drive(safe_drive):
                    self.bypass_action_sent = True

            return
        else:
            self.bypass_action_sent = False

        if self.current_tuner_state == "TUNED":
            if self.current_swr is None or self.current_swr <= 0:
                self.protection_var.set("ARMED — TUNER TUNED")
            else:
                self.protection_var.set(
                    f"ARMED — TUNED, SWR {self.current_swr:.2f}:1"
                )
            self.protection_label.configure(foreground="green")
        else:
            self.protection_var.set("ARMED — WAITING FOR TUNER STATUS")
            self.protection_label.configure(foreground="dark orange")

    def get_local_ip(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.connect(("8.8.8.8", 80))
            address = sock.getsockname()[0]
            sock.close()
            return address
        except Exception:
            try:
                return socket.gethostbyname(socket.gethostname())
            except Exception:
                return "127.0.0.1"

    def run_on_ui_thread_sync(self, func, timeout=2.0):
        done = threading.Event()
        result = {"value": None, "error": None}

        def wrapper():
            try:
                result["value"] = func()
            except Exception as exc:
                result["error"] = exc
            finally:
                done.set()

        try:
            self.root.after(0, wrapper)
        except tk.TclError:
            return None

        if not done.wait(timeout):
            return None

        if result["error"] is not None:
            raise result["error"]

        return result["value"]

    def web_status_snapshot(self):
        try:
            safe_drive = int(self.safe_drive_var.get())
        except Exception:
            safe_drive = None

        try:
            swr_limit = float(self.swr_limit_var.get())
        except Exception:
            swr_limit = None

        return {
            "tuner_ip": self.tuner_ip_var.get(),
            "tuner_connection": self.tuner_connection_var.get(),
            "tuner_state": self.tuner_state_var.get(),
            "swr": self.swr_var.get(),
            "forward_power": self.power_var.get(),
            "network": self.network_var.get(),
            "inductance": self.inductance_var.get(),
            "capacitance": self.capacitance_var.get(),
            "radio_ip": self.radio_ip_var.get(),
            "radio_port": self.radio_port_var.get(),
            "tci_connection": self.tci_connection_var.get(),
            "radio_device": self.radio_device_var.get(),
            "radio_tx": self.radio_tx_var.get(),
            "radio_tune": self.radio_tune_var.get(),
            "radio_drive": self.radio_drive_var.get(),
            "protection_enabled": bool(self.auto_protection_enabled.get()),
            "protection_state": self.protection_var.get(),
            "safe_drive": safe_drive,
            "swr_limit": swr_limit,
            "last_action": self.last_action_var.get(),
            "message": self.message_var.get(),
        }

    def web_apply_settings(self, fields):
        tuner_ip = fields.get("tuner_ip", [self.tuner_ip_var.get()])[0].strip()
        radio_ip = fields.get("radio_ip", [self.radio_ip_var.get()])[0].strip()

        try:
            ipaddress.ip_address(tuner_ip)
            ipaddress.ip_address(radio_ip)
        except ValueError:
            self.set_message("Web settings rejected: invalid IP address.")
            return False

        try:
            radio_port = int(fields.get("radio_port", [self.radio_port_var.get()])[0])
            safe_drive = int(fields.get("safe_drive", [self.safe_drive_var.get()])[0])
            swr_limit = float(fields.get("swr_limit", [self.swr_limit_var.get()])[0])
        except Exception:
            self.set_message("Web settings rejected: invalid numeric setting.")
            return False

        if not 1 <= radio_port <= 65535:
            self.set_message("Web settings rejected: invalid TCI port.")
            return False

        safe_drive = max(0, min(100, safe_drive))
        swr_limit = max(1.1, min(10.0, swr_limit))

        if self.tuner_connection_var.get() == "DISCONNECTED":
            self.tuner_ip_var.set(tuner_ip)

        if self.tci_connection_var.get() == "DISCONNECTED":
            self.radio_ip_var.set(radio_ip)
            self.radio_port_var.set(radio_port)

        self.safe_drive_var.set(safe_drive)
        self.swr_limit_var.set(swr_limit)
        self.evaluate_protection()
        self.set_message("Settings updated from web page.")
        return True

    def web_action(self, action, fields):
        if action == "update":
            self.web_apply_settings(fields)
        elif action == "tuner_connect":
            self.web_apply_settings(fields)
            self.connect_tuner()
        elif action == "tuner_disconnect":
            self.disconnect_tuner_clicked()
        elif action == "tci_connect":
            self.web_apply_settings(fields)
            self.connect_tci()
        elif action == "tci_disconnect":
            self.disconnect_tci_clicked()
        elif action == "arm":
            self.auto_protection_enabled.set(True)
            self.evaluate_protection()
            self.set_message("Automatic protection ARMED from web page.")
        elif action == "disarm":
            self.auto_protection_enabled.set(False)
            self.evaluate_protection()
            self.set_message("Automatic protection DISARMED from web page.")
        elif action == "emergency_stop":
            self.emergency_stop_tx("Manual web emergency stop")
        elif action == "toggle_tune":
            self.toggle_radio_tune()
        return True

    def start_web_server(self):
        if self.web_server is not None:
            return

        try:
            port = int(self.web_port_var.get())
            if not 1 <= port <= 65535:
                raise ValueError
        except Exception:
            messagebox.showerror(
                "Invalid web port",
                "Web server port must be between 1 and 65535."
            )
            return

        app = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "ATR1000Web/1.0"

            def log_message(self, format, *args):
                return

            def send_bytes(self, body, content_type, status=200):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/api/status":
                    snapshot = app.run_on_ui_thread_sync(app.web_status_snapshot)
                    body = json.dumps(snapshot or {}).encode("utf-8")
                    self.send_bytes(body, "application/json; charset=utf-8")
                    return

                if self.path != "/":
                    self.send_bytes(b"Not found", "text/plain; charset=utf-8", 404)
                    return

                page = app.make_web_page().encode("utf-8")
                self.send_bytes(page, "text/html; charset=utf-8")

            def do_POST(self):
                if self.path != "/action":
                    self.send_bytes(b"Not found", "text/plain; charset=utf-8", 404)
                    return

                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = 0

                raw = self.rfile.read(min(length, 8192)).decode(
                    "utf-8", errors="replace"
                )
                fields = parse_qs(raw)
                action = fields.get("action", [""])[0]

                app.run_on_ui_thread_sync(
                    lambda: app.web_action(action, fields)
                )

                self.send_response(303)
                self.send_header("Location", "/")
                self.end_headers()

        try:
            self.web_server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
            self.web_server.daemon_threads = True
        except Exception as error:
            self.web_server = None
            messagebox.showerror(
                "Web server error",
                f"Could not start web server:\n\n{error}"
            )
            return

        self.web_thread = threading.Thread(
            target=self.web_server.serve_forever,
            daemon=True
        )
        self.web_thread.start()

        local_ip = self.get_local_ip()
        self.web_status_var.set("RUNNING")
        self.web_status_label.configure(foreground="green")
        self.web_url_var.set(f"http://{local_ip}:{port}/")
        self.web_port_entry.configure(state="disabled")
        self.web_start_button.configure(state="disabled")
        self.web_stop_button.configure(state="normal")
        self.set_message(
            f"Web control started at http://{local_ip}:{port}/"
        )

    def stop_web_server(self):
        server = self.web_server
        self.web_server = None

        if server is not None:
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                pass

        self.web_status_var.set("STOPPED")
        self.web_status_label.configure(foreground="red")
        self.web_url_var.set("--")
        self.web_port_entry.configure(state="normal")
        self.web_start_button.configure(state="normal")
        self.web_stop_button.configure(state="disabled")
        self.set_message("Web control server stopped.")

    def make_web_page(self):
        return r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ATR-1000 Radio Protection</title>
<style>
body{font-family:Arial,sans-serif;background:#f3f4f6;color:#111;margin:0;padding:18px}
main{max-width:760px;margin:auto}
.card{background:white;border:1px solid #d1d5db;border-radius:8px;padding:16px;margin-bottom:14px}
h1{font-size:24px;margin:0 0 14px} h2{font-size:18px;margin:0 0 10px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:7px 16px}
.value{font-weight:bold}.good{color:#08783e}.bad{color:#b42318}.warn{color:#9a6700}
button{min-height:42px;padding:8px 14px;margin:4px 5px 4px 0;font-size:15px}
input{font-size:16px;padding:7px;width:150px;max-width:90%}
label{display:block;margin:7px 0}
.stop{background:#b42318;color:white;border:0;border-radius:5px;font-weight:bold}
.arm{background:#08783e;color:white;border:0;border-radius:5px}
.small{font-size:13px;color:#555}.message{word-break:break-word}
@media(max-width:520px){.grid{grid-template-columns:1fr} body{padding:10px}}
</style>
</head>
<body>
<main>
<h1>ATR-1000 / Radio Protection</h1>

<div class="card">
<h2>Live Status</h2>
<div class="grid">
<div>Tuner connection</div><div id="tuner_connection" class="value">--</div>
<div>Tuner state</div><div id="tuner_state" class="value">--</div>
<div>SWR</div><div id="swr" class="value">--</div>
<div>Forward power</div><div id="forward_power" class="value">--</div>
<div>TCI connection</div><div id="tci_connection" class="value">--</div>
<div>Radio TX</div><div id="radio_tx" class="value">--</div>
<div>Radio Tune</div><div id="radio_tune" class="value">--</div>
<div>Radio drive</div><div id="radio_drive" class="value">--</div>
<div>Protection</div><div id="protection_state" class="value">--</div>
<div>Last action</div><div id="last_action" class="value">--</div>
</div>
</div>

<div class="card">
<h2>Connections & Settings</h2>
<form method="post" action="/action">
<label>Tuner IP <input name="tuner_ip" id="tuner_ip"></label>
<label>Radio IP <input name="radio_ip" id="radio_ip"></label>
<label>TCI Port <input name="radio_port" id="radio_port" type="number"></label>
<label>BYPASS safe drive % <input name="safe_drive" id="safe_drive" type="number" min="0" max="100"></label>
<label>SWR TX-stop limit <input name="swr_limit" id="swr_limit" type="number" min="1.1" max="10" step="0.1"></label>
<button name="action" value="update">Save Settings</button>
<button name="action" value="tuner_connect">Connect Tuner</button>
<button name="action" value="tuner_disconnect">Disconnect Tuner</button>
<button name="action" value="tci_connect">Connect Radio TCI</button>
<button name="action" value="tci_disconnect">Disconnect Radio TCI</button>
</form>
</div>

<div class="card">
<h2>Protection Control</h2>
<form method="post" action="/action">
<button class="arm" name="action" value="arm">ARM Protection</button>
<button name="action" value="disarm">DISARM Protection</button>
<button id="tune_button" name="action" value="toggle_tune" disabled>TUNE</button>
<button class="stop" name="action" value="emergency_stop">EMERGENCY STOP TX</button>
</form>
<p class="small">TUNE toggles the radio's TCI Tune state on RX0. The emergency button always sends TX/Tune-off commands. The web page cannot raise radio drive automatically.</p>
</div>

<div class="card">
<div id="message" class="message">--</div>
<p class="small">Status refreshes every second.</p>
</div>
</main>

<script>
let first=true;
function setText(id,value){
  const el=document.getElementById(id);
  if(el) el.textContent=(value===null||value===undefined)?"--":value;
}
function setClass(id,value){
  const el=document.getElementById(id); if(!el)return;
  el.className="value";
  const t=String(value||"").toUpperCase();
  if(t.includes("CONNECTED")||t==="TUNED"||t==="RECEIVE"||t==="OFF"||t.includes("ARMED")) el.classList.add("good");
  if(t.includes("BYPASS")||t.includes("TRANSMITTING")||t==="ON"||t.includes("EMERGENCY")) el.classList.add("bad");
  if(t.includes("UNKNOWN")||t.includes("DISCONNECTED")||t.includes("DISARMED")) el.classList.add("warn");
}
async function refresh(){
  try{
    const r=await fetch("/api/status",{cache:"no-store"});
    const s=await r.json();
    ["tuner_connection","tuner_state","swr","forward_power","tci_connection",
     "radio_tx","radio_tune","radio_drive","protection_state","last_action","message"].forEach(k=>{
       setText(k,s[k]); setClass(k,s[k]);
     });

    const tuneButton=document.getElementById("tune_button");
    if(tuneButton){
      const known=(s.radio_tune==="ON" || s.radio_tune==="OFF");
      tuneButton.disabled=(s.tci_connection!=="CONNECTED" || !known);
      tuneButton.textContent=(s.radio_tune==="ON") ? "TUNE OFF" : "TUNE ON";
    }
    if(first){
      ["tuner_ip","radio_ip","radio_port","safe_drive","swr_limit"].forEach(k=>{
        const el=document.getElementById(k);
        if(el && s[k]!==undefined && s[k]!==null) el.value=s[k];
      });
      first=false;
    }
  }catch(e){
    setText("message","Web status connection lost.");
  }
}
refresh(); setInterval(refresh,1000);
</script>
</body>
</html>"""

    def on_close(self):
        self.app_closing.set()
        self.disconnect_tuner(False)
        self.disconnect_tci(False)

        server = self.web_server
        self.web_server = None
        if server is not None:
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                pass

        self.root.destroy()


def main():
    root = tk.Tk()

    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass

    ProtectionMonitor(root)
    root.mainloop()


if __name__ == "__main__":
    main()
