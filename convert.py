import os
import glob
import subprocess
import imageio_ffmpeg

# Priyanshu apne laptop ke hisaab se ya toh yahan path badal sakte hain
# ya environment variables (INPUT_VIDEO_DIR, OUTPUT_PREVIEW_DIR) set kar sakte hain.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_FOLDER = os.environ.get("INPUT_VIDEO_DIR", os.path.join(BASE_DIR, "videos"))
OUTPUT_FOLDER = os.environ.get("OUTPUT_PREVIEW_DIR", os.path.join(BASE_DIR, "preview_videos"))


def batch_transcode_videos():
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

    ts_files = sorted(
        list(set(
            glob.glob(os.path.join(INPUT_FOLDER, "*.TS")) +
            glob.glob(os.path.join(INPUT_FOLDER, "*.ts"))
        ))
    )

    if not ts_files:
        print(f"Error: No .TS files found in {INPUT_FOLDER}")
        return

    total = len(ts_files)
    print(f"Found {total} total videos. Converting remaining files...\n")

    for idx, file_path in enumerate(ts_files, start=1):
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        output_mp4 = os.path.join(OUTPUT_FOLDER, f"{base_name}.mp4")

        if os.path.exists(output_mp4):
            print(f"[{idx}/{total}] Skipped (already exists): {base_name}.mp4")
            continue

        print(f"[{idx}/{total}] Converting: {base_name}.TS -> {base_name}.mp4 ...")
        cmd = [
            ffmpeg_exe, "-y", "-i", file_path,
            "-vf", "scale=-2:480",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-crf", "26", "-preset", "veryfast",
            "-movflags", "+faststart",
            "-an", output_mp4
        ]
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        if result.returncode == 0:
            print(f"[{idx}/{total}] Completed: {base_name}.mp4")
        else:
            print(f"[{idx}/{total}] Failed: {base_name}.TS")

    print(f"\nAll {total} videos are now ready in {OUTPUT_FOLDER}.")


if __name__ == "__main__":
    batch_transcode_videos()