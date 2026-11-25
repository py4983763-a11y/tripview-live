import os

# 1. Update app.py for full-length / long videos
with open("app.py", "r", encoding="utf-8") as f:
    app_code = f.read()

# Expand timestamp matching tolerance for variable-length clips
app_code = app_code.replace(
    "if abs((target_time - vid_time).total_seconds()) <= 15:",
    "if abs((target_time - vid_time).total_seconds()) <= 120:"
)

# Replace 120s cap with full video duration + adaptive step for long videos
old_scan_loop = """    for sec in range(min(duration_sec, 120)):
        frame_idx = int(sec * fps)"""

new_scan_loop = """    # Adaptive sampling: 1s step for <=2 min, 2s for <=10 min, 5s for longer videos
    step_sec = 1 if duration_sec <= 120 else (2 if duration_sec <= 600 else 5)
    for sec in range(0, duration_sec, step_sec):
        frame_idx = int(sec * fps)"""

app_code = app_code.replace(old_scan_loop, new_scan_loop)

# Keep timeline_counts aligned second-by-second even when step_sec > 1
old_timeline_append = """        total_objects = c_person + c_car + c_bike + c_heavy
        timeline_counts.append(total_objects)"""

new_timeline_append = """        total_objects = c_person + c_car + c_bike + c_heavy
        for _ in range(step_sec):
            if len(timeline_counts) < duration_sec:
                timeline_counts.append(total_objects)"""

app_code = app_code.replace(old_timeline_append, new_timeline_append)

with open("app.py", "w", encoding="utf-8") as f:
    f.write(app_code)
print("Updated: app.py (Supports full-length & long dashcam videos)")

# 2. Update templates/contact.html (Project Lead: Priyanshu & Rahul)
with open("templates/contact.html", "r", encoding="utf-8") as f:
    contact_html = f.read()

contact_html = contact_html.replace(
    "Priyanshu — Data Analytics &amp; Computer Vision",
    "Priyanshu &amp; Rahul — Data Analytics &amp; Computer Vision"
)
with open("templates/contact.html", "w", encoding="utf-8") as f:
    f.write(contact_html)
print("Updated: templates/contact.html (Project Lead: Priyanshu & Rahul)")

# 3. Update UI labels across home.html, events.html, and analytics.html
replacements = {
    "templates/home.html": [
        ("60s Offset", "Auto-Sync"),
        ("Auto-Timestamp Alignment", "Variable-Length Clip Alignment"),
        ("resolving the 60-second dashcam save delay", "matching variable-length MP4 clips with GPS timestamps"),
        ("Scans frames at 1 FPS", "Scans full-length video frames")
    ],
    "templates/events.html": [
        ("Sort: Video Timestamp (0s &rarr; 60s)", "Sort: Video Timestamp (Start &rarr; End)")
    ],
    "templates/analytics.html": [
        ("60s Offset Auto-Matched", "Full-Duration Auto-Matched"),
        ("Run 1 FPS inference on synced dashcam footage", "Run full-duration YOLOv8 inference on short or long dashcam videos"),
        ("YOLOv8n inference complete (1 FPS frame alignment)", "YOLOv8n full-video inference complete (exact timestamp aligned)")
    ]
}

for path, pairs in replacements.items():
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        for old_txt, new_txt in pairs:
            content = content.replace(old_txt, new_txt)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Updated: {path}")

print("\nAll updates applied successfully!")