from picamera2 import Picamera2, Preview
from picamera2.encoders import H264Encoder
from libcamera import Transform
import cv2
import math
import os
import time



def main():
	picam2 = Picamera2()
	mode_index = 7
	mode = picam2.sensor_modes[mode_index]
	print(f"FPS: {mode['fps']}")
	config = picam2.create_preview_configuration(
		main={"size": mode["size"]},
		sensor={"output_size": mode["size"], "bit_depth": mode["bit_depth"]},
	)
	picam2.align_configuration(config)
	picam2.configure(config)
	
	frame_duration_us = math.ceil(1_000_000 / mode["fps"])
	picam2.set_controls({
		"FrameDurationLimits": (frame_duration_us, frame_duration_us),
	})
	
	






if __name__ == "__main__":
	main()
