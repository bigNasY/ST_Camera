"""Preview a Picamera2 sensor mode and continuously save raw frames."""

import base64
import json
import math
import queue
import struct
import threading
import tkinter as tk
import zlib
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import numpy as np
from picamera2 import Picamera2


class CameraCaptureUI:
	def __init__(self, root):
		self.root = root
		self.root.title("Camera Raw Capture")
		self.root.minsize(720, 560)

		self.camera = Picamera2()
		self.sensor_modes = self.camera.sensor_modes
		self.mode_labels = [self._mode_label(mode, index) for index, mode in enumerate(self.sensor_modes)]
		self.selected_mode = 0
		self.output_path = tk.StringVar(value=str(Path.cwd() / "raw_capture"))
		self.status = tk.StringVar(value="Starting camera...")
		self.preview_photo = None
		self.latest_preview = None
		self.preview_lock = threading.Lock()
		self.mode_lock = threading.Lock()
		self.capture_enabled = threading.Event()
		self.shutdown = threading.Event()
		self.worker_done = threading.Event()
		self.messages = queue.Queue()
		self.current_run = None
		self.saved_frames = 0

		self._build_ui()
		self.worker = threading.Thread(target=self._camera_loop, daemon=True)
		self.worker.start()
		self.root.protocol("WM_DELETE_WINDOW", self._close)
		self.root.after(50, self._refresh_ui)

	@staticmethod
	def _mode_label(mode, index):
		width, height = mode["size"]
		return f"{index}: {width}x{height}, {mode['fps']:.1f} fps, {mode['bit_depth']}-bit"

	def _build_ui(self):
		self.root.columnconfigure(0, weight=1)
		self.root.rowconfigure(1, weight=1)

		controls = ttk.Frame(self.root, padding=(12, 10))
		controls.grid(row=0, column=0, sticky="ew")
		controls.columnconfigure(1, weight=1)

		ttk.Label(controls, text="Camera mode").grid(row=0, column=0, padx=(0, 8), sticky="w")
		self.mode_box = ttk.Combobox(controls, state="readonly", values=self.mode_labels)
		self.mode_box.current(0)
		self.mode_box.grid(row=0, column=1, sticky="ew")
		self.mode_box.bind("<<ComboboxSelected>>", self._mode_changed)

		ttk.Label(controls, text="Save to").grid(row=1, column=0, padx=(0, 8), pady=(10, 0), sticky="w")
		self.path_entry = ttk.Entry(controls, textvariable=self.output_path)
		self.path_entry.grid(row=1, column=1, pady=(10, 0), sticky="ew")
		self.browse_button = ttk.Button(controls, text="Browse...", command=self._browse)
		self.browse_button.grid(row=1, column=2, padx=(8, 0), pady=(10, 0))

		preview_frame = ttk.LabelFrame(self.root, text="Live preview", padding=8)
		preview_frame.grid(row=1, column=0, padx=12, pady=(0, 10), sticky="nsew")
		preview_frame.columnconfigure(0, weight=1)
		preview_frame.rowconfigure(0, weight=1)
		self.preview_label = ttk.Label(preview_frame, anchor="center", text="Waiting for camera...")
		self.preview_label.grid(row=0, column=0, sticky="nsew")

		footer = ttk.Frame(self.root, padding=(12, 0, 12, 12))
		footer.grid(row=2, column=0, sticky="ew")
		footer.columnconfigure(0, weight=1)
		self.status_label = ttk.Label(footer, textvariable=self.status)
		self.status_label.grid(row=0, column=0, sticky="w")
		self.start_button = ttk.Button(footer, text="Start collecting", command=self._start_capture)
		self.start_button.grid(row=0, column=1, padx=(8, 0))
		self.start_button.configure(state="disabled")
		self.stop_button = ttk.Button(footer, text="Stop", command=self._stop_capture, state="disabled")
		self.stop_button.grid(row=0, column=2, padx=(8, 0))

	def _mode_changed(self, _event=None):
		with self.mode_lock:
			self.selected_mode = _event.widget.current()
		self.start_button.configure(state="disabled")
		self.status.set("Applying camera mode...")

	def _browse(self):
		selected = filedialog.askdirectory(initialdir=self.output_path.get() or str(Path.cwd()))
		if selected:
			self.output_path.set(selected)

	def _start_capture(self):
		output_root = Path(self.output_path.get()).expanduser()
		try:
			output_root.mkdir(parents=True, exist_ok=True)
			run_path = output_root / datetime.now().strftime("capture_%Y%m%d_%H%M%S_%f")
			run_path.mkdir()
		except OSError as error:
			messagebox.showerror("Cannot start capture", str(error), parent=self.root)
			return

		mode = self.sensor_modes[self.mode_box.current()]
		metadata = {
			"sensor_mode": {
				"index": self.mode_box.current(),
				"size": list(mode["size"]),
				"format": str(mode["format"]),
				"bit_depth": mode["bit_depth"],
				"fps": mode["fps"],
			},
			"frame_files": "Numbered .npy files containing raw sensor arrays",
		}
		(run_path / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
		self.current_run = run_path
		self.saved_frames = 0
		self.capture_enabled.set()
		self._set_capturing_ui(True)
		self.status.set(f"Collecting to {run_path}")

	def _stop_capture(self):
		self.capture_enabled.clear()
		self._set_capturing_ui(False)
		self.status.set(f"Stopped. Saved {self.saved_frames} frames to {self.current_run}")

	def _set_capturing_ui(self, capturing):
		self.start_button.configure(state="disabled" if capturing else "normal")
		self.stop_button.configure(state="normal" if capturing else "disabled")
		self.mode_box.configure(state="disabled" if capturing else "readonly")
		self.path_entry.configure(state="disabled" if capturing else "normal")
		self.browse_button.configure(state="disabled" if capturing else "normal")

	def _configure_camera(self, mode):
		config = self.camera.create_preview_configuration(
			main={"size": (640, 480), "format": "YUV420"},
			raw={"size": mode["size"], "format": mode["format"]},
			sensor={"output_size": mode["size"], "bit_depth": mode["bit_depth"]},
		)
		self.camera.align_configuration(config)
		self.camera.configure(config)
		frame_duration_us = math.ceil(1_000_000 / mode["fps"])
		self.camera.set_controls({"FrameDurationLimits": (frame_duration_us, frame_duration_us)})
		self.camera.start()

	def _camera_loop(self):
		camera_started = False
		current_mode = None
		try:
			while not self.shutdown.is_set():
				with self.mode_lock:
					requested_mode = self.selected_mode
				if requested_mode != current_mode:
					if camera_started:
						self.camera.stop()
						camera_started = False
					self._configure_camera(self.sensor_modes[requested_mode])
					camera_started = True
					current_mode = requested_mode
					self.messages.put(("mode_ready", current_mode))

				request = self.camera.capture_request()
				try:
					preview = np.array(request.make_array("main"), copy=True)
					if self.capture_enabled.is_set() and self.current_run is not None:
						raw = request.make_array("raw")
						frame_path = self.current_run / f"frame_{self.saved_frames:06d}.npy"
						with frame_path.open("wb") as frame_file:
							np.save(frame_file, raw)
						self.saved_frames += 1
				finally:
					request.release()
				with self.preview_lock:
					self.latest_preview = preview
		except Exception as error:
			self.messages.put(("error", str(error)))
		finally:
			if camera_started:
				self.camera.stop()
			self.camera.close()
			self.worker_done.set()

	@staticmethod
	def _preview_data(frame):
		height = frame.shape[0] * 2 // 3
		gray = np.ascontiguousarray(frame[:height, :])
		width = gray.shape[1]
		scanlines = b"".join(b"\x00" + gray[row].tobytes() for row in range(height))

		def chunk(kind, data):
			payload = kind + data
			return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)

		png = (
			b"\x89PNG\r\n\x1a\n"
			+ chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
			+ chunk(b"IDAT", zlib.compress(scanlines))
			+ chunk(b"IEND", b"")
		)
		return base64.b64encode(png).decode("ascii")

	def _refresh_ui(self):
		while True:
			try:
				kind, message = self.messages.get_nowait()
			except queue.Empty:
				break
			if kind == "status":
				if not self.capture_enabled.is_set():
					self.status.set(message)
			elif kind == "mode_ready":
				with self.mode_lock:
					requested_mode = self.selected_mode
				if message == requested_mode and not self.capture_enabled.is_set():
					self.start_button.configure(state="normal")
					self.status.set(f"Previewing {self.mode_labels[message]}")
			elif kind == "error":
				self.capture_enabled.clear()
				self._set_capturing_ui(False)
				self.status.set(f"Camera error: {message}")
				messagebox.showerror("Camera error", message, parent=self.root)

		with self.preview_lock:
			preview = self.latest_preview
			self.latest_preview = None
		if preview is not None:
			self.preview_photo = tk.PhotoImage(data=self._preview_data(preview), format="PNG")
			self.preview_label.configure(image=self.preview_photo, text="")
		if self.capture_enabled.is_set():
			self.status.set(f"Collecting: {self.saved_frames} frames saved")
		if not self.worker_done.is_set():
			self.root.after(50, self._refresh_ui)
		else:
			self.start_button.configure(state="disabled")
			self.stop_button.configure(state="disabled")

	def _close(self):
		self.capture_enabled.clear()
		self.shutdown.set()
		self.root.after(50, self._finish_close)

	def _finish_close(self):
		if self.worker_done.is_set():
			self.root.destroy()
		else:
			self.root.after(50, self._finish_close)


def main():
	root = tk.Tk()
	try:
		CameraCaptureUI(root)
		root.mainloop()
	except Exception as error:
		messagebox.showerror("Camera startup failed", str(error), parent=root)
		root.destroy()


if __name__ == "__main__":
	main()
