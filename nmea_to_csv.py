import os
import csv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NMEA_FOLDER = os.environ.get("INPUT_NMEA_DIR", os.path.join(BASE_DIR, "nmea_files"))
OUTPUT_CSV_PATH = os.environ.get(
    "OUTPUT_MERGED_CSV",
    os.path.join(BASE_DIR, "All_NMEA_Combined.csv")
)


def nmea_to_decimal(coord_str, direction):
    if not coord_str or str(coord_str).strip() == "":
        return None
    coord_str = str(coord_str).strip()
    try:
        if direction in ["N", "S"]:
            deg = float(coord_str[:2])
            minutes = float(coord_str[2:])
        else:
            deg = float(coord_str[:3])
            minutes = float(coord_str[3:])

        decimal = deg + (minutes / 60.0)
        if direction in ["S", "W"]:
            decimal = -decimal
        return round(decimal, 6)
    except Exception:
        return None


def merge_all_nmea_to_single_csv(folder_path, output_csv_path):
    if not os.path.exists(folder_path):
        print(f"Error: Folder nahi mila: {folder_path}")
        return

    all_files = os.listdir(folder_path)
    nmea_filenames = sorted(list(set(f for f in all_files if f.lower().endswith(".nmea"))))
    nmea_files = [os.path.join(folder_path, f) for f in nmea_filenames]

    if not nmea_files:
        print(f"Error: Folder mein koi .NMEA file nahi mili: {folder_path}")
        return

    out_dir = os.path.dirname(os.path.abspath(output_csv_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    headers = [
        "Trip_ID",
        "Source_File",
        "Sec",
        "Date",
        "Time (UTC)",
        "Status",
        "Latitude",
        "Longitude",
        "Speed (km/h)",
        "Heading (deg)"
    ]

    total_rows = 0

    with open(output_csv_path, "w", newline="", encoding="utf-8") as csv_f:
        writer = csv.writer(csv_f)
        writer.writerow(headers)

        for trip_idx, file_path in enumerate(nmea_files, start=1):
            filename = os.path.basename(file_path)
            sec = 0
            file_rows = 0

            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("$GPRMC") or line.startswith("$GNRMC"):
                        parts = line.split(",")
                        if len(parts) >= 10:
                            raw_time = parts[1]
                            status = parts[2]

                            formatted_time = ""
                            if len(raw_time) >= 6:
                                formatted_time = f"{raw_time[0:2]}:{raw_time[2:4]}:{raw_time[4:6]}"

                            lat = nmea_to_decimal(parts[3], parts[4])
                            lon = nmea_to_decimal(parts[5], parts[6])

                            try:
                                spd_knots = float(parts[7]) if parts[7] else 0.0
                                spd_kmph = round(spd_knots * 1.852, 2)
                            except ValueError:
                                spd_kmph = 0.0

                            try:
                                heading = float(parts[8]) if parts[8] else 0.0
                            except ValueError:
                                heading = 0.0

                            raw_date = parts[9]
                            formatted_date = (
                                f"20{raw_date[4:6]}-{raw_date[2:4]}-{raw_date[0:2]}"
                                if len(raw_date) >= 6 else ""
                            )

                            writer.writerow([
                                trip_idx,
                                filename,
                                sec,
                                formatted_date,
                                formatted_time,
                                status,
                                lat,
                                lon,
                                spd_kmph,
                                heading
                            ])
                            sec += 1
                            file_rows += 1
                            total_rows += 1

            print(f"[{trip_idx:02d}/{len(nmea_files)}] Added {filename} ({file_rows} rows)")

    print(f"\nDONE: Saari {len(nmea_files)} NMEA files ka data ({total_rows} rows) '{output_csv_path}' mein save ho gaya hai!")


if __name__ == "__main__":
    merge_all_nmea_to_single_csv(folder_path=NMEA_FOLDER, output_csv_path=OUTPUT_CSV_PATH)