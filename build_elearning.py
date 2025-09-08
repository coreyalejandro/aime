#!/usr/bin/env python3

import os
import re
import json
import subprocess
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont


SCRIPT_PATH = Path("/workspace/AIMe Course - The Complete 8-Video Recording Script.md")
IMAGES_DIR = Path("/workspace/images")
BUILD_DIR = Path("/workspace/build")
FRAMES_DIR = BUILD_DIR / "frames"
SCENES_DIR = BUILD_DIR / "scenes"
OUTPUT_VIDEO = Path("/workspace/output/AIme_elearning_course.mp4")
MAPPING_JSON = BUILD_DIR / "image_mapping.json"


def ensure_dirs() -> None:
    (Path("/workspace/output")).mkdir(parents=True, exist_ok=True)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    SCENES_DIR.mkdir(parents=True, exist_ok=True)


def read_text(path: Path) -> str:
    with path.open("r", encoding="utf-8") as f:
        return f.read()


def find_font() -> ImageFont.FreeTypeFont:
    candidate_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for p in candidate_paths:
        if os.path.exists(p):
            return ImageFont.truetype(p, size=44)
    # Fallback to default PIL font
    return ImageFont.load_default()


def parse_script(markdown_text: str) -> List[Dict]:
    videos: List[Dict] = []

    lines = markdown_text.splitlines()
    current_video: Optional[Dict] = None
    in_table = False
    header_captured = False

    for line in lines:
        # Detect new video section
        m = re.match(r"^## \*\*Video\s+(\d+):\s*(.*?)\*\*", line.strip())
        if m:
            if current_video:
                videos.append(current_video)
            current_video = {
                "video_number": int(m.group(1)),
                "title": m.group(2),
                "scenes": [],
            }
            in_table = False
            header_captured = False
            continue

        # Table rows start after header lines of the 3-col table
        if current_video:
            if line.strip().startswith("| Scene |"):
                in_table = True
                header_captured = True
                continue
            if header_captured and line.strip().startswith("| :----"):
                # separator line
                continue
            if in_table:
                if not line.strip().startswith("|"):
                    # End of table
                    in_table = False
                    continue
                # Parse table row: | **1** | Visual | Narration |
                cols = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cols) >= 3:
                    scene_label = re.sub(r"\*", "", cols[0]).strip()
                    scene_number_match = re.search(r"(\d+)", scene_label)
                    scene_number = int(scene_number_match.group(1)) if scene_number_match else len(current_video["scenes"]) + 1
                    visual = cols[1].strip()
                    narration = cols[2].strip().strip('"')
                    current_video["scenes"].append({
                        "scene_number": scene_number,
                        "visual": visual,
                        "narration": narration,
                    })

    if current_video:
        videos.append(current_video)

    return videos


def list_images(images_dir: Path) -> List[Path]:
    exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".gif"}
    all_images = [p for p in images_dir.glob("**/*") if p.suffix.lower() in exts]
    # Sort by name for deterministic order
    return sorted(all_images, key=lambda p: p.name.lower())


def build_default_image_mapping(videos: List[Dict], images: List[Path]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}

    remaining = images.copy()

    # Heuristic: Title card for Video 1 Scene 1 -> image with AIMe/AlMe name
    title_candidates = [p for p in remaining if re.search(r"ai\s*\+\s*me|aime|alme", p.name, re.IGNORECASE)]
    if title_candidates:
        title_img = title_candidates[0]
        key = scene_key(1, 1)
        mapping[key] = str(title_img)
        remaining.remove(title_img)

    # Assign remaining images in reading order to remaining scenes
    scene_order: List[Tuple[int, int]] = []
    for v in videos:
        for s in v["scenes"]:
            scene_order.append((v["video_number"], s["scene_number"]))

    # Skip already assigned
    unassigned_keys = [scene_key(vn, sn) for vn, sn in scene_order if scene_key(vn, sn) not in mapping]

    for key, img in zip(unassigned_keys, remaining):
        mapping[key] = str(img)

    return mapping


def scene_key(video_number: int, scene_number: int) -> str:
    return f"V{video_number:02d}_S{scene_number:02d}"


def estimate_duration_seconds(narration: str) -> float:
    words = len(re.findall(r"\w+", narration))
    seconds_per_word = 0.36  # ~166 wpm
    duration = max(4.0, min(22.0, words * seconds_per_word))
    return round(duration, 2)


def wrap_text(text: str, font: ImageFont.ImageFont, max_width_px: int, draw: ImageDraw.ImageDraw) -> List[str]:
    words = text.split()
    lines: List[str] = []
    current: List[str] = []
    for word in words:
        test = (" ".join(current + [word])).strip()
        w, _ = draw.textbbox((0, 0), test, font=font)[2:]
        if w <= max_width_px or not current:
            current.append(word)
        else:
            lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines


def compose_frame(base_image_path: Path, narration: str, out_path: Path, canvas_size: Tuple[int, int] = (1920, 1080)) -> None:
    width, height = canvas_size
    # Load base image
    with Image.open(base_image_path) as img:
        img = img.convert("RGB")
        # Fit image to canvas (contain) and pad to 16:9
        img_ratio = img.width / img.height
        canvas_ratio = width / height
        if img_ratio > canvas_ratio:
            # image is wider -> fit width
            new_width = width
            new_height = int(width / img_ratio)
        else:
            new_height = height
            new_width = int(height * img_ratio)
        img_resized = img.resize((new_width, new_height), Image.LANCZOS)

        background = Image.new("RGB", (width, height), (10, 10, 12))
        offset = ((width - new_width) // 2, (height - new_height) // 2)
        background.paste(img_resized, offset)

    draw = ImageDraw.Draw(background)
    font = find_font()

    # Text box area (bottom 34%)
    box_margin = 40
    box_top = int(height * 0.66)
    box_left = box_margin
    box_right = width - box_margin
    box_bottom = height - box_margin

    # Semi-transparent overlay for readability
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rounded_rectangle(
        [(box_left - 10, box_top - 10), (box_right + 10, box_bottom + 10)],
        radius=16,
        fill=(0, 0, 0, 150),
        outline=(255, 255, 255, 40),
        width=2,
    )
    background = Image.alpha_composite(background.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(background)

    # Wrap text to fit
    max_text_width = box_right - box_left
    lines = wrap_text(narration, font, max_text_width, draw)

    line_height = font.size + 10
    total_text_height = len(lines) * line_height
    start_y = box_top + max(0, ((box_bottom - box_top) - total_text_height) // 2)

    for idx, line in enumerate(lines):
        # shadow
        draw.text((box_left + 2, start_y + idx * line_height + 2), line, font=font, fill=(0, 0, 0))
        draw.text((box_left, start_y + idx * line_height), line, font=font, fill=(240, 240, 240))

    background.save(out_path)


def run_ffmpeg(cmd: List[str]) -> None:
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)


def render_scene_video(frame_path: Path, duration_s: float, out_video_path: Path) -> None:
    # Create a simple Ken Burns slow zoom using zoompan over a still image
    # We will first create a short mp4 from the still with a slow zoom.
    fps = 30

    # Use scale and zoompan on image input
    # Note: zoompan requires frame count; use fps and d for duration per frame
    vf = (
        f"scale=1920:1080,zoompan=z='min(zoom+0.0008,1.06)':d=1:fps={fps}:s=1920x1080,"
        "format=yuv420p"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-loop", "1",
        "-t", f"{duration_s}",
        "-i", str(frame_path),
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        str(out_video_path),
    ]
    run_ffmpeg(cmd)


def concat_videos(video_paths: List[Path], out_path: Path) -> None:
    # Use concat demuxer
    concat_list_path = BUILD_DIR / "concat_list.txt"
    with concat_list_path.open("w", encoding="utf-8") as f:
        for p in video_paths:
            f.write(f"file '{p.as_posix()}'\n")

    cmd = [
        "ffmpeg",
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_list_path),
        "-c", "copy",
        str(out_path),
    ]
    run_ffmpeg(cmd)


def main() -> None:
    ensure_dirs()

    if not SCRIPT_PATH.exists():
        raise FileNotFoundError(f"Script file not found: {SCRIPT_PATH}")
    if not IMAGES_DIR.exists():
        raise FileNotFoundError(f"Images directory not found: {IMAGES_DIR}")

    md = read_text(SCRIPT_PATH)
    videos = parse_script(md)

    images = list_images(IMAGES_DIR)
    if not images:
        raise RuntimeError(f"No images found in {IMAGES_DIR}")

    # Build or read mapping
    if MAPPING_JSON.exists():
        mapping = json.loads(read_text(MAPPING_JSON))
    else:
        mapping = build_default_image_mapping(videos, images)
        with MAPPING_JSON.open("w", encoding="utf-8") as f:
            json.dump(mapping, f, indent=2)

    # Compose frames and render scenes
    rendered_scene_paths: List[Path] = []
    for v in videos:
        vn = v["video_number"]
        for s in v["scenes"]:
            sn = s["scene_number"]
            key = scene_key(vn, sn)
            img_path_str = mapping.get(key)
            if not img_path_str:
                # Fallback: use first image
                img_path_str = str(images[0])
            base_img_path = Path(img_path_str)
            if not base_img_path.exists():
                # Fallback to any available
                base_img_path = images[0]

            narration = s["narration"]
            duration = estimate_duration_seconds(narration)

            frame_path = FRAMES_DIR / f"{key}.png"
            compose_frame(base_img_path, narration, frame_path)

            scene_out = SCENES_DIR / f"{key}.mp4"
            render_scene_video(frame_path, duration, scene_out)
            rendered_scene_paths.append(scene_out)

    # Concat
    concat_videos(rendered_scene_paths, OUTPUT_VIDEO)
    print(f"\nDone. Output video: {OUTPUT_VIDEO}")


if __name__ == "__main__":
    main()

