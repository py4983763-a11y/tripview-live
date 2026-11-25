import os
import gc
import json
import threading
import cv2
import torch
import config

_yolo_model = None
_yolo_device = "cuda" if torch.cuda.is_available() else "cpu"
_scan_lock = threading.Lock()
_active_scans = set()


def get_yolo_model():
    global _yolo_model
    if _yolo_model is None:
        from ultralytics import YOLO
        if os.path.exists(config.CUSTOM_MODEL_PATH):
            print(f"[VisionEngine] Loading Custom Model: {config.CUSTOM_MODEL_PATH} on {_yolo_device.upper()}", flush=True)
            _yolo_model = YOLO(config.CUSTOM_MODEL_PATH)
        else:
            for model_name in [config.DEFAULT_MODEL_NAME, config.FALLBACK_MODEL_NAME, "yolov8n.pt"]:
                try:
                    print(f"[VisionEngine] Loading {model_name} on {_yolo_device.upper()}...", flush=True)
                    _yolo_model = YOLO(model_name)
                    print(f"[VisionEngine] Successfully loaded {model_name}!", flush=True)
                    break
                except Exception as e:
                    print(f"[VisionEngine] Could not load {model_name} ({e}), trying next...", flush=True)
    return _yolo_model


def scan_video_frame_by_frame(trip_id, video_name, force_rescan=False):
    cache_file = os.path.join(config.CACHE_DIR, f"{trip_id}_ai_v2.json")
    if os.path.exists(cache_file) and not force_rescan:
        with open(cache_file, "r") as f:
            return json.load(f)

    # Prevent duplicate concurrent scans of the same trip
    with _scan_lock:
        model = get_yolo_model()

    video_path = os.path.join(config.VIDEO_DIR, video_name)
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError("Could not open video file.")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1280
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720
    duration_sec = max(1, int(total_frames / fps)) if fps > 0 else 60

    class_names = model.names
    sample_fps = config.SAMPLE_FPS
    total_steps = max(1, int(duration_sec * sample_fps))
    print(f"[VisionEngine] Auto-Scanning {video_name} ({duration_sec}s @ {sample_fps} FPS)...", flush=True)

    frames_detections = []
    timeline_counts = []
    ai_events = []
    unique_tracks_by_class = {}

    for step_idx in range(total_steps):
        timestamp = round(step_idx / sample_fps, 2)
        sec = int(timestamp)
        frame_idx = min(total_frames - 1, int(timestamp * fps))

        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            break

        results = model.track(
            frame,
            persist=True,
            tracker="bytetrack.yaml",
            classes=None,
            conf=config.YOLO_CONF_THRESHOLD,
            iou=config.YOLO_IOU_THRESHOLD,
            imgsz=config.YOLO_IMG_SIZE,
            device=_yolo_device,
            verbose=False
        )

        boxes = results[0].boxes
        frame_objs = []
        sec_class_counts = {}

        if boxes is not None and len(boxes) > 0:
            xyxyn_list = boxes.xyxyn.tolist()
            cls_list = boxes.cls.tolist()
            conf_list = boxes.conf.tolist()
            id_list = boxes.id.tolist() if boxes.id is not None else [step_idx * 1000 + i for i in range(len(cls_list))]

            for box, cls_id, conf, track_id in zip(xyxyn_list, cls_list, conf_list, id_list):
                cid = int(cls_id)
                tid = int(track_id)
                label = str(class_names.get(cid, f"Class_{cid}"))

                unique_tracks_by_class.setdefault(label, set()).add(tid)
                sec_class_counts[label] = sec_class_counts.get(label, 0) + 1

                frame_objs.append({
                    "id": tid,
                    "label": label,
                    "conf": round(float(conf), 2),
                    "bbox": [round(float(c), 4) for c in box]
                })

        frames_detections.append({
            "t": timestamp,
            "sec": sec,
            "objects": frame_objs
        })

        if step_idx % sample_fps == 0:
            total_objs = len(frame_objs)
            timeline_counts.append(total_objs)

            ped_count = sec_class_counts.get("person", 0) + sec_class_counts.get("Pedestrian", 0)
            hazard_count = (
                sec_class_counts.get("Pothole", 0)
                + sec_class_counts.get("High_Breaker", 0)
                + sec_class_counts.get("dog", 0)
                + sec_class_counts.get("cow", 0)
                + sec_class_counts.get("Animal", 0)
            )

            if hazard_count > 0:
                ai_events.append({
                    "sec": sec,
                    "type": "AI: Road Hazard / Animal",
                    "severity": "high",
                    "detail": f"Detected road hazard/animal ({', '.join(f'{k}:{v}' for k, v in sec_class_counts.items())})"
                })
            elif ped_count > 0:
                ai_events.append({
                    "sec": sec,
                    "type": "AI: Pedestrian Alert",
                    "severity": "high",
                    "detail": f"Spotted {ped_count} pedestrian(s) in active field of view"
                })
            elif total_objs >= 5:
                summary_str = ", ".join(f"{v} {k}" for k, v in list(sec_class_counts.items())[:4])
                ai_events.append({
                    "sec": sec,
                    "type": "AI: Dense Scene Activity",
                    "severity": "medium",
                    "detail": f"{total_objs} objects tracked ({summary_str})"
                })

    cap.release()
    gc.collect()
    print(f"[VisionEngine] Completed: {video_name}", flush=True)

    class_totals = {k: len(v) for k, v in sorted(unique_tracks_by_class.items(), key=lambda x: len(x[1]), reverse=True)}

    totals = {
        "cars": class_totals.get("car", 0) + class_totals.get("4W_Car", 0),
        "two_wheelers": class_totals.get("motorcycle", 0) + class_totals.get("bicycle", 0) + class_totals.get("2W_Gear", 0) + class_totals.get("2W_NonGear", 0),
        "heavy_vehicles": class_totals.get("truck", 0) + class_totals.get("bus", 0) + class_totals.get("Truck", 0) + class_totals.get("Bus", 0),
        "pedestrians": class_totals.get("person", 0) + class_totals.get("Pedestrian", 0),
        "all_classes": class_totals
    }

    loaded_name = getattr(model, "ckpt_path", None)
    model_label = os.path.basename(loaded_name) if loaded_name else config.DEFAULT_MODEL_NAME

    ai_data = {
        "model_used": model_label,
        "video_meta": {"width": width, "height": height, "fps": round(fps, 2), "duration": duration_sec, "sample_fps": sample_fps},
        "totals": totals,
        "timeline_counts": timeline_counts,
        "ai_events": ai_events,
        "frames": frames_detections
    }

    with open(cache_file, "w") as f:
        json.dump(ai_data, f)

    return ai_data


def start_background_preindexer(gps_df, find_video_fn):
    """Automatically scans all uncached trip videos in a background thread on server startup (disabled on Render)."""
    if not getattr(config, "ENABLE_BACKGROUND_PREINDEX", True):
        print("[VisionEngine] Background pre-indexer disabled for production server.", flush=True)
        return

    def _worker():
        if gps_df.empty:
            return
        for filename in gps_df["Filename"].unique():
            trip_id = str(filename).replace("CH1-", "").replace(".NMEA", "").replace(".csv", "")
            cache_file = os.path.join(config.CACHE_DIR, f"{trip_id}_ai_v2.json")
            if os.path.exists(cache_file):
                continue
            video_name = find_video_fn(trip_id)
            if video_name:
                try:
                    scan_video_frame_by_frame(trip_id, video_name, force_rescan=False)
                except Exception as e:
                    print(f"[VisionEngine] Background scan skipped for {trip_id}: {e}", flush=True)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()