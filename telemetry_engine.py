import os
import glob
import io
import csv
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import config


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlambda = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2.0) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2.0) ** 2
    return 2 * r * np.arctan2(np.sqrt(a), np.sqrt(1 - a))


def load_all_gps_data():
    csv_files = glob.glob(os.path.join(config.GPS_DATA_DIR, "*.csv"))
    if not csv_files:
        return pd.DataFrame(columns=["Filename", "Sentence", "Time", "Status", "Lat", "Lon", "Speed", "Date"])

    df_list = []
    for f in csv_files:
        try:
            temp = pd.read_csv(f)
            if "Sentence" in temp.columns and "Status" in temp.columns:
                rmc = temp[(temp["Sentence"] == "RMC") & (temp["Status"] == "A")]
                if not rmc.empty:
                    temp = rmc.copy()

            temp = temp.dropna(subset=["Lat", "Lon"]).copy()
            temp["Lat"] = pd.to_numeric(temp["Lat"], errors="coerce")
            temp["Lon"] = pd.to_numeric(temp["Lon"], errors="coerce")
            temp = temp.dropna(subset=["Lat", "Lon"])
            temp["Speed"] = pd.to_numeric(temp["Speed"], errors="coerce").fillna(0.0)

            if "Filename" not in temp.columns:
                temp["Filename"] = os.path.basename(f).replace(".csv", ".NMEA")

            df_list.append(temp)
        except Exception as e:
            print(f"[TelemetryEngine] Skipping {f}: {e}")

    if not df_list:
        return pd.DataFrame(columns=["Filename", "Sentence", "Time", "Status", "Lat", "Lon", "Speed", "Date"])
    return pd.concat(df_list, ignore_index=True)


def find_video_for_trip(trip_id):
    if not os.path.exists(config.VIDEO_DIR):
        return None
    mp4_files = [f for f in os.listdir(config.VIDEO_DIR) if f.lower().endswith(".mp4")]

    for fname in mp4_files:
        if trip_id in fname:
            return fname

    try:
        nmea_time = datetime.strptime(trip_id, "%Y%m%d-%H%M%S")
        expected_video_time = nmea_time - timedelta(seconds=60)
        for target_time in [expected_video_time, nmea_time]:
            for fname in mp4_files:
                vid_stamp = fname.replace("CH1-", "").replace(".mp4", "").replace(".MP4", "")
                try:
                    vid_time = datetime.strptime(vid_stamp, "%Y%m%d-%H%M%S")
                    if abs((target_time - vid_time).total_seconds()) <= 15:
                        return fname
                except ValueError:
                    continue
    except ValueError:
        pass
    return None


def analyze_trip_telemetry(trip_rows):
    if trip_rows.empty:
        return {}
    speeds = trip_rows["Speed"].values
    lats = trip_rows["Lat"].values
    lons = trip_rows["Lon"].values

    if len(lats) > 1:
        dists = haversine_km(lats[:-1], lons[:-1], lats[1:], lons[1:])
        total_dist = round(float(np.sum(dists)), 2)
    else:
        total_dist = 0.0

    avg_speed = round(float(np.mean(speeds)), 1)
    max_speed = round(float(np.max(speeds)), 1)
    min_speed = round(float(np.min(speeds)), 1)
    speed_std = round(float(np.std(speeds)), 2)
    smoothness = max(0, min(100, round(100 - (speed_std * 4))))

    idle_sec = int(np.sum(speeds < 5))
    city_sec = int(np.sum((speeds >= 5) & (speeds <= 30)))
    cruise_sec = int(np.sum((speeds > 30) & (speeds <= 55)))
    fast_sec = int(np.sum(speeds > 55))

    accel = np.round(np.diff(speeds, prepend=speeds[0]), 2)

    events = [{
        "sec": int(np.argmax(speeds)),
        "type": "Peak Velocity Reached",
        "severity": "info",
        "detail": f"Reached trip maximum of {max_speed} km/h"
    }]

    for sec in range(1, len(speeds)):
        if accel[sec] <= -6.0:
            events.append({
                "sec": int(sec),
                "type": "Harsh Braking",
                "severity": "high",
                "detail": f"Sudden drop of {abs(accel[sec])} km/h/s (down to {round(speeds[sec], 1)} km/h)"
            })
        elif accel[sec] <= -3.0:
            events.append({
                "sec": int(sec),
                "type": "Moderate Deceleration",
                "severity": "medium",
                "detail": f"Slowed by {abs(accel[sec])} km/h/s (at {round(speeds[sec], 1)} km/h)"
            })
        elif accel[sec] >= 5.0:
            events.append({
                "sec": int(sec),
                "type": "Rapid Acceleration",
                "severity": "medium",
                "detail": f"Surged +{accel[sec]} km/h/s (up to {round(speeds[sec], 1)} km/h)"
            })
        elif speeds[sec] > 60.0 and speeds[sec - 1] <= 60.0:
            events.append({
                "sec": int(sec),
                "type": "High Speed Threshold",
                "severity": "high",
                "detail": f"Crossed 60 km/h ({round(speeds[sec], 1)} km/h)"
            })

    events.sort(key=lambda x: x["sec"])
    penalty = sum(8 if e["severity"] == "high" else (3 if e["severity"] == "medium" else 0) for e in events)
    safety_score = max(10, 100 - penalty)

    return {
        "distance_km": total_dist,
        "avg_speed": avg_speed,
        "max_speed": max_speed,
        "min_speed": min_speed,
        "smoothness": smoothness,
        "safety_score": safety_score,
        "zones": [idle_sec, city_sec, cruise_sec, fast_sec],
        "accel": accel.tolist(),
        "events": events
    }


def generate_csv_report(trip_id, trip_rows, analytics, video_name, ai_data):
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["TRIPVIEW — TELEMETRY & FULL-SCENE COMPUTER VISION REPORT"])
    writer.writerow(["Trip ID", trip_id])
    writer.writerow(["Synced Video File", video_name or "Not Available"])
    writer.writerow(["Total Duration (sec)", len(trip_rows)])
    if not trip_rows.empty:
        writer.writerow(["Start Coordinates", f"{round(float(trip_rows['Lat'].iloc[0]), 6)}, {round(float(trip_rows['Lon'].iloc[0]), 6)}"])
        writer.writerow(["End Coordinates", f"{round(float(trip_rows['Lat'].iloc[-1]), 6)}, {round(float(trip_rows['Lon'].iloc[-1]), 6)}"])
    writer.writerow([])

    writer.writerow(["1. PERFORMANCE & SAFETY KPIs"])
    writer.writerow(["Metric", "Value", "Unit / Notes"])
    writer.writerow(["Driver Safety Score", analytics.get("safety_score", 0), "/ 100"])
    writer.writerow(["Velocity Smoothness", analytics.get("smoothness", 0), "%"])
    writer.writerow(["Total Trip Distance", analytics.get("distance_km", 0), "km"])
    writer.writerow(["Min / Avg / Max Speed", f"{analytics.get('min_speed', 0)} / {analytics.get('avg_speed', 0)} / {analytics.get('max_speed', 0)}", "km/h"])
    writer.writerow([])

    writer.writerow(["2. FULL-SCENE AI OBJECT DETECTION SUMMARY (ALL CLASSES)"])
    if ai_data and ai_data.get("totals", {}).get("all_classes"):
        writer.writerow(["Detected Class", "Unique Tracked Objects"])
        for cls_name, count in ai_data["totals"]["all_classes"].items():
            writer.writerow([cls_name, count])
    else:
        writer.writerow(["Status", "AI Video Scan not executed yet"])
    writer.writerow([])

    combined_events = list(analytics.get("events", []))
    if ai_data:
        combined_events.extend(ai_data.get("ai_events", []))
    combined_events.sort(key=lambda x: x["sec"])

    writer.writerow(["3. DETECTED EVENTS & AI ALERTS"])
    writer.writerow(["Timestamp (sec)", "Event Type", "Severity", "Detail"])
    for ev in combined_events:
        writer.writerow([f"{ev['sec']}s", ev["type"], ev["severity"].upper(), ev["detail"]])
    writer.writerow([])

    accel_list = analytics.get("accel", [])
    ai_timeline = ai_data.get("timeline_counts", []) if ai_data else []
    writer.writerow(["4. SECOND-BY-SECOND TELEMETRY & OBJECT LOG"])
    writer.writerow(["Second", "UTC Time", "Latitude", "Longitude", "Speed (km/h)", "Accel Delta", "AI Object Count"])
    for sec, row in trip_rows.iterrows():
        spd = round(float(row["Speed"]), 2)
        acc = accel_list[sec] if sec < len(accel_list) else 0.0
        obj_count = ai_timeline[sec] if sec < len(ai_timeline) else "N/A"
        writer.writerow([sec, str(row.get("Time", "")).replace("+00:00", ""), round(float(row["Lat"]), 6), round(float(row["Lon"]), 6), spd, acc, obj_count])

    return output.getvalue()