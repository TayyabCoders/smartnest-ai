import face_recognition
import cv2
import os
import numpy as np

class SimpleFacerec:
    def __init__(self):
        self.known_face_encodings = []
        self.known_face_names = []

    def load_encoding_images(self, images_path):
        for img_name in os.listdir(images_path):
            img_path = os.path.join(images_path, img_name)
            img = face_recognition.load_image_file(img_path)

            encodings = face_recognition.face_encodings(img)
            if len(encodings) > 0:
                self.known_face_encodings.append(encodings[0])
                self.known_face_names.append(os.path.splitext(img_name)[0])

        print("Images loaded successfully")

    def detect_known_faces(self, frame):
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        face_locations = face_recognition.face_locations(rgb_frame)
        face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)

        face_names = []
        for face_encoding in face_encodings:
            matches = face_recognition.compare_faces(
                self.known_face_encodings, face_encoding
            )
            name = "Unknown"

            face_distances = face_recognition.face_distance(
                self.known_face_encodings, face_encoding
            )

            if len(face_distances) > 0:
                best_match = np.argmin(face_distances)
                if matches[best_match]:
                    name = self.known_face_names[best_match]

            face_names.append(name)

        return face_locations, face_names
