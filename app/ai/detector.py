"""
Object Detector: Supports Ultralytics YOLOv8/YOLO11, OpenCV DNN MobileNetSSD,
and HOG fallback for ultra-lightweight Raspberry Pi execution.
Includes optional privacy face blurring.
"""

import time
import os
import cv2
import numpy as np
from typing import List, Dict, Any, Tuple
from app.config.settings import load_config


class ObjectDetector:
    """Multi-backend object detector with automatic fallback."""

    def __init__(self):
        self.model = None
        self.backend = "none"
        self.classes_filter = ["person", "chair", "table", "knife", "bottle", "tv", "laptop"]
        self.confidence_threshold = 0.45
        self.iou_threshold = 0.45
        self.target_size = (320, 320)
        self.last_inference_time_ms = 0.0

        # Haar cascade for optional face blurring
        self._face_cascade = None
        self._init_face_cascade()

        self._load_backend()

    def _init_face_cascade(self):
        """Load Haar cascade classifier for privacy face blurring."""
        try:
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            if os.path.exists(cascade_path):
                self._face_cascade = cv2.CascadeClassifier(cascade_path)
        except Exception:
            self._face_cascade = None

    def _load_backend(self):
        """Attempt to load preferred AI backend or fallback gracefully."""
        cfg = load_config()
        ai_cfg = cfg.get("ai", {})
        preferred_backend = ai_cfg.get("backend", "auto").lower()
        model_name = ai_cfg.get("model_name", "yolov8n.pt")
        self.confidence_threshold = float(ai_cfg.get("confidence_threshold", 0.45))
        self.classes_filter = ai_cfg.get("classes", self.classes_filter)
        ts = ai_cfg.get("target_size", [320, 320])
        self.target_size = (int(ts[0]), int(ts[1]))

        # Try Ultralytics YOLO if requested or auto
        if preferred_backend in ["ultralytics", "auto"]:
            try:
                from ultralytics import YOLO
                print(f"[Detector] Loading Ultralytics YOLO ({model_name})...")
                self.model = YOLO(model_name)
                self.backend = "ultralytics"
                print("[Detector] Ultralytics YOLO loaded successfully.")
                return
            except Exception as e:
                print(f"[Detector] Ultralytics unavailable: {e}. Falling back to OpenCV HOG/Heuristic detector.")

        # Fallback: OpenCV HOG Person Detector (no extra downloads required, fast on RPi)
        try:
            self.model = cv2.HOGDescriptor()
            self.model.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
            self.backend = "opencv_hog"
            print("[Detector] OpenCV HOG People Detector initialized as fallback.")
        except Exception as e:
            self.backend = "heuristic"
            print(f"[Detector] HOG initialization failed ({e}), using Motion/Color Heuristics.")

    def detect(self, frame: np.ndarray) -> List[Dict[str, Any]]:
        """
        Run object detection on frame.
        Returns list of detections: [{"class_name": str, "confidence": float, "box": [x1, y1, x2, y2]}]
        """
        if frame is None:
            return []

        start_time = time.time()
        detections: List[Dict[str, Any]] = []
        h, w = frame.shape[:2]

        if self.backend == "ultralytics" and self.model is not None:
            try:
                # Resize for low CPU usage on Raspberry Pi
                results = self.model.predict(
                    source=frame,
                    imgsz=self.target_size[0],
                    conf=self.confidence_threshold,
                    iou=self.iou_threshold,
                    verbose=False
                )
                for r in results:
                    boxes = r.boxes
                    for box in boxes:
                        cls_id = int(box.cls[0].item())
                        cls_name = r.names.get(cls_id, "unknown")
                        conf = float(box.conf[0].item())
                        xyxy = box.xyxy[0].tolist()
                        x1, y1, x2, y2 = [int(v) for v in xyxy]

                        # Clamp to frame bounds
                        x1, y1 = max(0, x1), max(0, y1)
                        x2, y2 = min(w, x2), min(h, y2)

                        if cls_name in self.classes_filter or not self.classes_filter:
                            detections.append({
                                "class_name": cls_name,
                                "confidence": round(conf, 2),
                                "box": [x1, y1, x2, y2]
                            })
            except Exception as e:
                print(f"[Detector] Inference error: {e}")

        elif self.backend == "opencv_hog" and self.model is not None:
            try:
                # Downscale frame for speed
                scale_w = 400.0 / w if w > 400 else 1.0
                small_frame = cv2.resize(frame, (0, 0), fx=scale_w, fy=scale_w)
                gray = cv2.cvtColor(small_frame, cv2.COLOR_BGR2GRAY)
                rects, weights = self.model.detectMultiScale(
                    gray,
                    winStride=(8, 8),
                    padding=(8, 8),
                    scale=1.05
                )
                for (rx, ry, rw, rh), weight in zip(rects, weights):
                    x1 = int(rx / scale_w)
                    y1 = int(ry / scale_w)
                    x2 = int((rx + rw) / scale_w)
                    y2 = int((ry + rh) / scale_w)
                    conf = min(1.0, max(0.4, float(weight[0] if isinstance(weight, (list, np.ndarray)) else weight)))
                    detections.append({
                        "class_name": "person",
                        "confidence": round(conf, 2),
                        "box": [max(0, x1), max(0, y1), min(w, x2), min(h, y2)]
                    })
            except Exception as e:
                print(f"[Detector] HOG detection error: {e}")

        # Only check for synthetic demo actor if running in demo simulation mode AND no AI model is loaded
        cfg = load_config()
        cam_src = cfg.get("camera", {}).get("source_type", "demo").lower()
        if not detections and self.backend == "none" and cam_src == "demo" and h > 200 and w > 200:
            detections = self._heuristic_fallback_detect(frame)

        # Filter out tiny noise / false-positive specks that cannot be a human child
        cleaned_detections = []
        for det in detections:
            bx1, by1, bx2, by2 = det["box"]
            bw = bx2 - bx1
            bh = by2 - by1
            if det["class_name"] == "person":
                # Real child/person in 480p is at least 35px high and 18px wide
                if bh < 35 or bw < 18 or (bw * bh) < 700:
                    continue
                # Require >= 0.48 confidence for person to avoid false positive shadows
                if det["confidence"] < 0.48:
                    continue
            cleaned_detections.append(det)

        detections = cleaned_detections

        self.last_inference_time_ms = round((time.time() - start_time) * 1000.0, 1)

        # Apply face blurring if enabled in config
        if cfg.get("privacy", {}).get("face_blur", False):
            self.apply_face_blur(frame, detections)

        return detections

    def _heuristic_fallback_detect(self, frame: np.ndarray) -> List[Dict[str, Any]]:
        """Fallback detector using color contrast/contour bounding boxes for demo or low-spec nodes."""
        h, w = frame.shape[:2]
        # Look for the child actor drawn with skin and shirt color tones
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array([0, 30, 40]), np.array([180, 255, 255]))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        dets = []
        for c in contours:
            area = cv2.contourArea(c)
            if 600 < area < (w * h * 0.4):
                bx, by, bw, bh = cv2.boundingRect(c)
                # Ignore background furniture boxes if too wide
                if bh > 25 or bw > 25:
                    dets.append({
                        "class_name": "person",
                        "confidence": 0.85,
                        "box": [bx, by, bx + bw, by + bh]
                    })
        return dets

    def apply_face_blur(self, frame: np.ndarray, detections: List[Dict[str, Any]]):
        """Blur face area of detected persons for privacy."""
        h, w = frame.shape[:2]
        for det in detections:
            if det["class_name"] != "person":
                continue
            x1, y1, x2, y2 = det["box"]
            person_roi = frame[y1:y2, x1:x2]
            if person_roi.shape[0] < 20 or person_roi.shape[1] < 20:
                continue

            blurred = False
            if self._face_cascade is not None:
                gray = cv2.cvtColor(person_roi, cv2.COLOR_BGR2GRAY)
                faces = self._face_cascade.detectMultiScale(gray, 1.2, 4)
                for (fx, fy, fw, fh) in faces:
                    sub_face = person_roi[fy:fy + fh, fx:fx + fw]
                    if sub_face.size > 0:
                        blurred_face = cv2.GaussianBlur(sub_face, (27, 27), 30)
                        person_roi[fy:fy + fh, fx:fx + fw] = blurred_face
                        blurred = True

            # If Haar didn't hit, blur top 25% of person bounding box (head region)
            if not blurred:
                head_h = max(10, int((y2 - y1) * 0.25))
                sub_head = frame[y1:y1 + head_h, x1:x2]
                if sub_head.size > 0:
                    ksize = (sub_head.shape[1] // 4 * 2 + 1, sub_head.shape[0] // 4 * 2 + 1)
                    ksize = (max(5, ksize[0]), max(5, ksize[1]))
                    frame[y1:y1 + head_h, x1:x2] = cv2.GaussianBlur(sub_head, ksize, 20)
