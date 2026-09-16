from picamera2 import Picamera2
import math
import numpy as np
import time


def capture_raw(picam2, duration_seconds):
	mean_intensities = []

	picam2.start()
	try:
		# Let automatic exposure settle before processing the sample.
		for _ in range(30):
			request = picam2.capture_request()
			request.release()

		end_time = time.monotonic() + duration_seconds
		while time.monotonic() < end_time:
			request = picam2.capture_request()
			try:
				raw = request.make_array("raw")

				#Note: Performing the mean calculation does not affect the frame rate, as it is done after the frame has been captured and released. The frame rate is determined by the camera's settings and the time it takes to capture each frame, not by the processing done afterward.	
				mean_intensities.append(float(np.mean(raw)))
				
			finally:
				request.release()
	finally:
		picam2.stop()
	print(f"fps: {len(mean_intensities) / duration_seconds:.2f}")
	print(f"Captured {len(mean_intensities)} frames")
	print(f"Mean intensity: {np.mean(mean_intensities):.2f}")
	return mean_intensities


def main():
	picam2 = Picamera2()
	mode_index = 0


	mode = picam2.sensor_modes[mode_index]
	print(mode)
	
	config = picam2.create_preview_configuration(
		main={"size": (320, 240), "format": "YUV420"},
		raw={"size": mode["size"], "format": mode["format"]},
		sensor={"output_size": mode["size"], "bit_depth": mode["bit_depth"]},
	)
	picam2.align_configuration(config)
	picam2.configure(config)
	
	frame_duration_us = math.ceil(1_000_000 / mode["fps"])
	picam2.set_controls({
		"FrameDurationLimits": (frame_duration_us, frame_duration_us),
	})
	print(f"FPS: {mode['fps']}")
	capture_raw(picam2, duration_seconds=5)
	






if __name__ == "__main__":
	main()
