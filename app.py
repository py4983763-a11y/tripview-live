import os
import json
from functools import wraps
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, jsonify, send_file, Response, flash
)
import config
from telemetry_engine import (
    load_all_gps_data, find_video_for_trip,
    analyze_trip_telemetry, generate_csv_report
)
from vision_engine import scan_video_frame_by_frame, start_background_preindexer

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

gps_df = load_all_gps_data()
start_background_preindexer(gps_df, find_video_for_trip)


def load_users():
    if not os.path.exists(config.USERS_FILE):
        default_users = {
            "demo@tripview.io": {
                "name": "Priyanshu (Demo Analyst)",
                "password": generate_password_hash("demo123"),
                "role": "Lead Analyst"
            }
        }
        save_users(default_users)
        return default_users
    with open(config.USERS_FILE, "r") as f:
        return json.load(f)


def save_users(users):
    with open(config.USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login_page", next=request.path))
        return f(*args, **kwargs)
    return decorated


@app.route("/")
def home_page():
    total_trips = int(gps_df["Filename"].nunique()) if not gps_df.empty else 0
    total_videos = len([f for f in os.listdir(config.VIDEO_DIR) if f.lower().endswith(".mp4")])
    return render_template("home.html", total_trips=total_trips, total_videos=total_videos)


@app.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "POST":
        action = request.form.get("action")
        users = load_users()

        if action == "demo":
            session["user"] = {"email": "demo@tripview.io", "name": "Priyanshu (Demo)", "role": "Lead Analyst"}
            return redirect(url_for("explorer_page"))

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if action == "register":
            name = request.form.get("name", "").strip() or "Fleet Analyst"
            if not email or not password:
                flash("Please provide both email and password.", "error")
            elif email in users:
                flash("Account already exists. Please sign in.", "error")
            else:
                users[email] = {
                    "name": name,
                    "password": generate_password_hash(password),
                    "role": "Data Analyst"
                }
                save_users(users)
                session["user"] = {"email": email, "name": name, "role": "Data Analyst"}
                return redirect(url_for("explorer_page"))

        elif action == "login":
            user = users.get(email)
            if user and check_password_hash(user["password"], password):
                session["user"] = {"email": email, "name": user["name"], "role": user.get("role", "Analyst")}
                next_url = request.args.get("next") or url_for("explorer_page")
                return redirect(next_url)
            else:
                flash("Invalid email or password.", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("home_page"))


@app.route("/explorer")
@login_required
def explorer_page():
    return render_template("explorer.html")


@app.route("/events")
@login_required
def events_page():
    return render_template("events.html")


@app.route("/analytics")
@login_required
def analytics_page():
    return render_template("analytics.html")


@app.route("/contact", methods=["GET", "POST"])
def contact_page():
    submitted = False
    if request.method == "POST":
        entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "name": request.form.get("name", ""),
            "email": request.form.get("email", ""),
            "subject": request.form.get("subject", ""),
            "message": request.form.get("message", "")
        }
        msgs = []
        if os.path.exists(config.MESSAGES_FILE):
            with open(config.MESSAGES_FILE, "r") as f:
                msgs = json.load(f)
        msgs.append(entry)
        with open(config.MESSAGES_FILE, "w") as f:
            json.dump(msgs, f, indent=2)
        submitted = True
    return render_template("contact.html", submitted=submitted)


@app.route("/api/routes")
@login_required
def get_routes():
    features = []
    for filename, group in gps_df.groupby("Filename", sort=False):
        trip_id = str(filename).replace("CH1-", "").replace(".NMEA", "").replace(".csv", "")
        coordinates = [[float(row["Lon"]), float(row["Lat"])] for _, row in group.iterrows()]
        features.append({
            "type": "Feature",
            "properties": {
                "trip_id": trip_id,
                "avg_speed": round(float(group["Speed"].mean()), 1)
            },
            "geometry": {"type": "LineString", "coordinates": coordinates}
        })
    return jsonify({"type": "FeatureCollection", "features": features})


@app.route("/api/all_events")
@login_required
def get_all_events():
    all_events = []
    for filename, group in gps_df.groupby("Filename", sort=False):
        group = group.reset_index(drop=True)
        trip_id = str(filename).replace("CH1-", "").replace(".NMEA", "").replace(".csv", "")
        video_name = find_video_for_trip(trip_id)
        analytics = analyze_trip_telemetry(group)

        for ev in analytics.get("events", []):
            all_events.append({
                "trip_id": trip_id,
                "video_file": video_name,
                "sec": ev["sec"],
                "type": ev["type"],
                "severity": ev["severity"],
                "detail": ev["detail"],
                "source": "Telemetry"
            })

        cache_file = os.path.join(config.CACHE_DIR, f"{trip_id}_ai_v2.json")
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r") as f:
                    ai_data = json.load(f)
                    for ev in ai_data.get("ai_events", []):
                        all_events.append({
                            "trip_id": trip_id,
                            "video_file": video_name,
                            "sec": ev["sec"],
                            "type": ev["type"],
                            "severity": ev["severity"],
                            "detail": ev["detail"],
                            "source": "AI Vision"
                        })
            except Exception:
                pass
    return jsonify({"events": all_events})


@app.route("/api/telemetry/<trip_id>")
@login_required
def get_trip_details(trip_id):
    possible_names = [f"CH1-{trip_id}.NMEA", f"{trip_id}.NMEA", f"{trip_id}.csv", trip_id]
    trip_rows = gps_df[gps_df["Filename"].isin(possible_names)].reset_index(drop=True)

    points = [{
        "sec": int(sec),
        "time": str(row.get("Time", "")).replace("+00:00", ""),
        "lat": round(float(row["Lat"]), 6),
        "lng": round(float(row["Lon"]), 6),
        "speed": round(float(row["Speed"]), 1)
    } for sec, row in trip_rows.iterrows()]

    video_name = find_video_for_trip(trip_id)
    analytics = analyze_trip_telemetry(trip_rows)

    cache_file = os.path.join(config.CACHE_DIR, f"{trip_id}_ai_v2.json")
    ai_data = None
    if os.path.exists(cache_file):
        with open(cache_file, "r") as f:
            ai_data = json.load(f)

    return jsonify({
        "trip_id": trip_id,
        "video_file": video_name,
        "points": points,
        "analytics": analytics,
        "ai_data": ai_data
    })


@app.route("/api/ai_scan/<trip_id>", methods=["POST"])
@login_required
def run_ai_video_scan(trip_id):
    video_name = find_video_for_trip(trip_id)
    if not video_name:
        return jsonify({"status": "error", "message": "No video file found for this trip."}), 404

    force = request.args.get("force") == "1"
    try:
        ai_data = scan_video_frame_by_frame(trip_id, video_name, force_rescan=force)
        return jsonify({"status": "success", "ai_data": ai_data})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/export/<trip_id>")
@login_required
def export_report(trip_id):
    possible_names = [f"CH1-{trip_id}.NMEA", f"{trip_id}.NMEA", f"{trip_id}.csv", trip_id]
    trip_rows = gps_df[gps_df["Filename"].isin(possible_names)].reset_index(drop=True)
    analytics = analyze_trip_telemetry(trip_rows)
    video_name = find_video_for_trip(trip_id)

    cache_file = os.path.join(config.CACHE_DIR, f"{trip_id}_ai_v2.json")
    ai_data = None
    if os.path.exists(cache_file):
        with open(cache_file, "r") as f:
            ai_data = json.load(f)

    csv_content = generate_csv_report(trip_id, trip_rows, analytics, video_name, ai_data)
    return Response(
        csv_content,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename=TripView_Analyst_Report_{trip_id}.csv"}
    )


@app.route("/videos/<filename>")
@login_required
def stream_video(filename):
    file_path = os.path.join(config.VIDEO_DIR, filename)
    if not os.path.exists(file_path):
        return "Video not found", 404
    as_download = request.args.get("download") == "1"
    return send_file(file_path, as_attachment=as_download, conditional=True)


if __name__ == "__main__":
    print(f"TripView Platform ready! Loaded {gps_df['Filename'].nunique()} trips.")
    app.run(debug=True, use_reloader=False, host="0.0.0.0", port=5000)