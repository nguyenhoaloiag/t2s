import os, uuid, re, shutil, subprocess, requests, threading
from urllib.parse import urlparse
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__)
TEMP_DIR = "temp"
os.makedirs(TEMP_DIR, exist_ok=True)
JOB_STATUS = {}

def run_ffmpeg(cmd):
    subprocess.run(cmd, check=True)

def download_file(url, dest):
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, stream=True, timeout=30)
        r.raise_for_status()
        with open(dest, 'wb') as f:
            for chunk in r.iter_content(8192): f.write(chunk)
        return True
    except Exception as e:
        print(f"\u274c Download failed: {url} | {e}")
        return False

def get_audio_duration(path):
    try:
        out = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", path
        ], capture_output=True, text=True)
        return float(out.stdout.strip())
    except:
        return 0.0

def format_time(sec):
    h, m, s = int(sec // 3600), int((sec % 3600) // 60), int(sec % 60)
    ms = int((sec - int(sec)) * 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

def generate_subs(text, duration, path):
    sentences = re.findall(r'[^.!?]+[.!?]?', text.strip())
    total_chars = sum(len(s) for s in sentences)
    if not total_chars: return
    current = 0.0
    with open(path, "w", encoding="utf-8") as f:
        for i, s in enumerate(sentences):
            dur = duration * len(s) / total_chars
            f.write(f"{i+1}\n{format_time(current)} --> {format_time(current+dur)}\n{s.strip()}\n\n")
            current += dur

@app.route("/c2vi", methods=["POST"])
def submit_job():
    job_id = uuid.uuid4().hex
    JOB_STATUS[job_id] = {"status": "processing", "video": None, "error": None}
    threading.Thread(target=process_job, args=(job_id, request.get_json())).start()
    return jsonify({"job_id": job_id})

@app.route("/status/<job_id>")
def get_status(job_id):
    return jsonify(JOB_STATUS.get(job_id, {"error": "job_id not found"}))

@app.route("/result/<job_id>")
def get_result(job_id):
    job = JOB_STATUS.get(job_id)
    if not job or job["status"] != "done":
        return jsonify({"error": "Video chưa sẵn sàng"}), 400
    return send_from_directory(TEMP_DIR, job["video"], as_attachment=True)

def process_job(job_id, data):
    try:
        img_urls = data.get("image_urls", [])
        audio_url = data.get("audio_url")
        bgm_url = data.get("bgm_url")
        subs_text = data.get("subtitle_text", "")
        aspect = data.get("aspect_ratio", "horizontal")
        logo_url = data.get("logo_url")
        logo_position = data.get("logo_position", "top-right")
        intro_url = data.get("intro_url")

        if not img_urls or not audio_url:
            raise Exception("Thiếu ảnh hoặc audio.")

        job_dir = os.path.join(TEMP_DIR, job_id)
        os.makedirs(job_dir, exist_ok=True)

        res = "720:1280" if aspect == "vertical" else "1280:720"
        img_paths = []
        for i, url in enumerate(img_urls):
            ext = os.path.splitext(urlparse(url).path)[1].lower()
            ext = ext if ext in [".jpg", ".jpeg", ".png", ".webp"] else ".jpg"
            raw = os.path.join(job_dir, f"raw_{i}{ext}")
            jpg = os.path.join(job_dir, f"img_{i}.jpg")

            if not download_file(url, raw):
                raise Exception(f"Không tải được ảnh {url}")
            subprocess.run(["ffmpeg", "-y", "-i", raw, "-q:v", "2", jpg], check=True)
            img_paths.append(jpg)

        voice_mp3 = os.path.join(job_dir, "voice.mp3")
        voice_wav = os.path.join(job_dir, "voice.wav")
        if not download_file(audio_url, voice_mp3):
            raise Exception("Không tải được giọng đọc")
        run_ffmpeg(["ffmpeg", "-y", "-i", voice_mp3, "-ar", "44100", "-ac", "2", "-sample_fmt", "s16", voice_wav])

        duration = get_audio_duration(voice_wav)
        if duration <= 0:
            raise Exception("Audio không hợp lệ")

        fade = min(2.0, duration / 4)
        final_audio = voice_wav

        if bgm_url:
            bgm_mp3 = os.path.join(job_dir, "bgm.mp3")
            if not download_file(bgm_url, bgm_mp3):
                raise Exception("Không tải được nhạc nền")
            run_ffmpeg([
                "ffmpeg", "-y", "-i", voice_wav, "-i", bgm_mp3,
                "-filter_complex",
                f"[0:a]afade=t=in:st=0:d={fade},afade=t=out:st={duration-fade}:d={fade}[v];"
                f"[1:a]volume=0.15,afade=t=in:st=0:d={fade},afade=t=out:st={duration-fade}:d={fade}[b];"
                f"[v][b]amix=inputs=2:duration=first[a]",
                "-map", "[a]", "-c:a", "aac", "-b:a", "192k",
                os.path.join(job_dir, "mixed.m4a")
            ])
            final_audio = os.path.join(job_dir, "mixed.m4a")

        input_txt = os.path.join(job_dir, "input.txt")
        image_duration = max(duration / len(img_paths), 0.5)
        with open(input_txt, "w") as f:
            for img in img_paths:
                f.write(f"file '{os.path.abspath(img)}'\n")
                f.write(f"duration {image_duration:.2f}\n")
            f.write(f"file '{os.path.abspath(img_paths[-1])}'\n")

        img_video = os.path.join(job_dir, "video.mp4")
        run_ffmpeg([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-fflags", "+genpts",
            "-i", input_txt, "-vf", f"scale={res},format=yuv420p",
            "-r", "30", "-an", img_video
        ])

        if intro_url:
            intro_path = os.path.join(job_dir, "intro.mp4")
            if not download_file(intro_url, intro_path):
                raise Exception("Không tải được intro")
            concat_txt = os.path.join(job_dir, "concat_intro.txt")
            with open(concat_txt, "w") as f:
                f.write(f"file '{os.path.abspath(intro_path)}'\n")
                f.write(f"file '{os.path.abspath(img_video)}'\n")
            img_video = os.path.join(job_dir, "with_intro.mp4")
            run_ffmpeg([
                "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_txt,
                "-c", "copy", img_video
            ])

        video_with_audio = os.path.join(job_dir, "merged.mp4")
        run_ffmpeg([
            "ffmpeg", "-y", "-i", img_video, "-i", final_audio,
            "-c:v", "copy", "-c:a", "aac", "-shortest", "-movflags", "+faststart",
            video_with_audio
        ])

        if logo_url:
            logo_path = os.path.join(job_dir, "logo.png")
            if not download_file(logo_url, logo_path):
                raise Exception("Không tải được logo")
            pos_map = {
                "top-left": "10:10",
                "top-right": "main_w-overlay_w-10:10",
                "bottom-left": "10:main_h-overlay_h-10",
                "bottom-right": "main_w-overlay_w-10:main_h-overlay_h-10"
            }
            position = pos_map.get(logo_position, "main_w-overlay_w-10:10")
            final_video = os.path.join(job_dir, "video_logo.mp4")
            run_ffmpeg([
                "ffmpeg", "-y",
                "-i", video_with_audio,
                "-i", logo_path,
                "-filter_complex", f"[1]scale=100:-1[logo];[0][logo]overlay={position}",
                "-c:a", "copy", final_video
            ])
        else:
            final_video = video_with_audio

        if subs_text:
            sub_path = os.path.join(job_dir, "subs.srt")
            generate_subs(subs_text, duration, sub_path)
            with_subs = os.path.join(job_dir, "with_subs.mp4")
            run_ffmpeg([
                "ffmpeg", "-y", "-i", final_video,
                "-vf", f"subtitles={sub_path}:force_style='FontName=Arial,FontSize=16,PrimaryColour=&H00FFFF00,BorderStyle=1,Outline=1'",
                "-c:a", "copy", with_subs
            ])
            final_video = with_subs

        result_name = f"{job_id}.mp4"
        shutil.move(final_video, os.path.join(TEMP_DIR, result_name))
        JOB_STATUS[job_id] = {"status": "done", "video": result_name}
        shutil.rmtree(job_dir)

    except Exception as e:
        JOB_STATUS[job_id] = {"status": "error", "error": str(e)}

if __name__ == "__main__":
    app.run(debug=True, port=5000)
