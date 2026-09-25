"""Capture sensor raw frames and make simple files for inspection.

Examples:
    python viewdata.py --frames 1
    python viewdata.py --duration 5 --output capture
"""

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
from picamera2 import Picamera2


def _viewable_image(raw_frames):
	"""Convert raw sensor values to an 8-bit grayscale image."""
	image = np.asarray(raw_frames[0], dtype=np.float32)
	low, high = np.percentile(image, (1, 99))
	if high <= low:
		low = float(image.min())
		high = float(image.max())
	if high <= low:
		return np.zeros(image.shape, dtype=np.uint8)

	return np.clip((image - low) * 255.0 / (high - low), 0, 255).astype(np.uint8)


def _save_png(image, path):
	try:
		from PIL import Image
	except ImportError as error:
		raise RuntimeError("Saving a PNG requires Pillow: python -m pip install Pillow") from error
	Image.fromarray(image, mode="L").save(path)


def capture_raw(picam2, frame_count=None, duration=None):
	frames = []
	start = time.monotonic()
	while (frame_count is None or len(frames) < frame_count) and (
		duration is None or time.monotonic() - start < duration
	):
		request = picam2.capture_request()
		try:
			frames.append(np.array(request.make_array("raw"), copy=True))
		finally:
			request.release()
	return np.stack(frames), time.monotonic() - start


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--output", type=Path, default=Path("raw_capture"))
	parser.add_argument("--frames", type=int, default=1)
	parser.add_argument("--duration", type=float, help="Capture until this many seconds have elapsed")
	parser.add_argument("--mode", type=int, default=0, help="Sensor mode index")
	args = parser.parse_args()
	if args.frames < 1 or (args.duration is not None and args.duration <= 0):
		parser.error("frames and duration must be positive")
	if args.duration is not None:
		frame_count = None
	else:
		frame_count = args.frames

	picam2 = Picamera2()
	try:
		mode = picam2.sensor_modes[args.mode]
		config = picam2.create_preview_configuration(
			main={"size": (320, 240), "format": "YUV420"},
			raw={"size": mode["size"], "format": mode["format"]},
			sensor={"output_size": mode["size"], "bit_depth": mode["bit_depth"]},
		)
		picam2.align_configuration(config)
		picam2.configure(config)
		frame_duration_us = math.ceil(1_000_000 / mode["fps"])
		picam2.set_controls({"FrameDurationLimits": (frame_duration_us, frame_duration_us)})

		picam2.start()
		try:
			# Discard startup frames while exposure and gain settle.
			for _ in range(30):
				request = picam2.capture_request()
				request.release()
			frames, elapsed = capture_raw(picam2, frame_count, args.duration)
		finally:
			picam2.stop()
	finally:
		picam2.close()

	args.output.parent.mkdir(parents=True, exist_ok=True)
	args.output.with_suffix(".npy").parent.mkdir(parents=True, exist_ok=True)
	#np.save(args.output.with_suffix(".npy"), frames)
	_save_png(_viewable_image(frames), args.output.with_suffix(".png"))
	metadata = {
		"shape": list(frames.shape),
		"dtype": str(frames.dtype),
		"elapsed_seconds": elapsed,
		"measured_fps": len(frames) / elapsed if elapsed else 0,
		"sensor_mode": mode,
	}
	#args.output.with_suffix(".json").write_text(json.dumps(metadata, indent=2, default=str) + "\n")
	#print(f"Saved {len(frames)} raw frames to {args.output.with_suffix('.npy')}")
	print(f"Saved normalized view to {args.output.with_suffix('.png')}")


if __name__ == "__main__":
	main()
