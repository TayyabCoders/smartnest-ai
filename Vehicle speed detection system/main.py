import cv2
import time
from tracker import *

# Create tracker object
tracker = EuclideanDistTracker()

# Path to video file. Replace with 0 for webcam or path to your video.
# VIDEO_SOURCE = "highway.mp4" 
# Example: Use a sample video if available, or webcam
VIDEO_SOURCE = "highway1.mp4.mp4" 
cap = cv2.VideoCapture("highway1.mp4.mp4")  # File ka poora naam extension ke sath

cap = cv2.VideoCapture(VIDEO_SOURCE)

# Object detection from Stable camera
object_detector = cv2.createBackgroundSubtractorMOG2(history=100, varThreshold=40)

# 1. Define ROI - Region of Interest
# You might need to adjust these coordinates based on your video resolution
#roi_x, roi_y, roi_w, roi_h = 340, 340, 500, 400

# Dictionary to store the time when a vehicle passes the first line
# {id: start_time}
vehicle_start_time = {}

# Dictionary to store the speed
vehicle_speed = {}

# Distance between the two lines in meters (real world distance)
# This needs to be calibrated/measured for the specific camera setup
DISTANCE_METERS = 5 

# Line positions (Y-coordinates)
# Adjust these based on your video
LINE_START_Y = 400
LINE_END_Y = 500

print(f"Opening video source: {VIDEO_SOURCE}")
if not cap.isOpened():
    print(f"Error: Could not open video source {VIDEO_SOURCE}")
    print("Please check if the file exists or if the camera index is correct.")
    print("You can change VIDEO_SOURCE in main.py to 0 for webcam or provide a valid video path.")
    exit()

print("Press 'Esc' to exit the video window.")

while True:
    ret, frame = cap.read()
    if not ret:
        break
        
    height, width, _ = frame.shape

    # Extract Region of Interest (ROI)
    # cropped_frame = frame[roi_y:roi_y+roi_h, roi_x:roi_x+roi_w]
    # For now, let's use the whole frame or a larger ROI
    roi = frame[300: 720, 300: 1000] # Adjust as needed

    # 1. Object Detection
    mask = object_detector.apply(roi)
    
    # Remove shadows and noise
    _, mask = cv2.threshold(mask, 254, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    
    detections = []
    
    for cnt in contours:
        # Calculate area and remove small elements
        area = cv2.contourArea(cnt)
        if area > 100: # Adjust threshold as needed
            x, y, w, h = cv2.boundingRect(cnt)
            detections.append([x, y, w, h])

    # 2. Object Tracking
    boxes_ids = tracker.update(detections)
    
    for box_id in boxes_ids:
        x, y, w, h, id = box_id
        
        # Calculate center y of the box regarding the ROI
        cy = y + h // 2
        
        # Adjust cy to match the original frame if we used ROI
        # global_cy = cy + 300 
        
        # In this loop x,y,w,h are relative to the ROI
        
        # Check if vehicle crosses the first line
        # Use a small range to account for frame skips
        # We use 'cy + 300' because our ROI starts at y=300 in the original frame
        global_cy = cy + 300

        if (LINE_START_Y - 15) < global_cy < (LINE_START_Y + 15):
            if id not in vehicle_start_time:
                vehicle_start_time[id] = time.time()

        # Check if vehicle crosses the second line
        if (LINE_END_Y - 15) < global_cy < (LINE_END_Y + 15):
             if id in vehicle_start_time and id not in vehicle_speed:
                elapsed_time = time.time() - vehicle_start_time[id]
                # Calculate speed: Speed = Distance / Time
                # convert m/s to km/h: * 3.6
                if elapsed_time > 0.1: # Avoid division by zero or extremely small times
                    speed_ms = DISTANCE_METERS / elapsed_time
                    speed_kmh = speed_ms * 3.6
                    vehicle_speed[id] = int(speed_kmh)

        # Draw detection box
        if id in vehicle_speed and vehicle_speed[id] > 20:
            cv2.rectangle(roi, (x, y), (x + w, y + h), (0, 0, 255), 2)
        else:
            cv2.rectangle(roi, (x, y), (x + w, y + h), (0, 255, 0), 2)
        
        # Display Speed
        if id in vehicle_speed:
            cv2.putText(roi, str(vehicle_speed[id]) + " Km/h", (x, y - 15), cv2.FONT_HERSHEY_PLAIN, 2, (255, 255, 0), 2)
        else:
             cv2.putText(roi, "ID: " + str(id), (x, y - 15), cv2.FONT_HERSHEY_PLAIN, 1, (255, 0, 0), 2)


    # Draw lines on the original frame (or rather, overlay ROI back? 
    # Easiest to just draw on ROI then show ROI)
    
    # Draw measurement lines (relative to ROI detection area)
    # Since we are drawing on 'roi', the Y coordinates need to be adjusted relative to the crop
    # Crop started at Y=300
    cv2.line(roi, (0, LINE_START_Y - 300), (width, LINE_START_Y - 300), (0, 0, 255), 2)
    cv2.line(roi, (0, LINE_END_Y - 300), (width, LINE_END_Y - 300), (0, 0, 255), 2)

    cv2.imshow("ROI", roi)
    # cv2.imshow("Frame", frame)
    # cv2.imshow("Mask", mask)

    key = cv2.waitKey(30)
    if key == 27:
        break

cap.release()
cv2.destroyAllWindows()
