"""Convert one MP4 in S3 to a single-rendition HLS stream.

Invoked manually (no S3 trigger). By default it processes STREAMNEST_INPUT_KEY;
pass {"input_key": "input/other.mp4"} in the test event to process another file.
"""
import json
import os
import subprocess
import tempfile
from pathlib import Path

import boto3

s3 = boto3.client("s3")
BUCKET = os.environ["STREAMNEST_BUCKET"]
INPUT_KEY = os.environ.get("STREAMNEST_INPUT_KEY", "input/sample.mp4")
OUTPUT_PREFIX = os.environ.get("STREAMNEST_OUTPUT_PREFIX", "output/forest-video/").rstrip("/") + "/"
FFMPEG = os.environ.get("FFMPEG_PATH", "/opt/bin/ffmpeg")

CONTENT_TYPES = {
    ".m3u8": "application/vnd.apple.mpegurl",
    ".ts": "video/mp2t",
}


def lambda_handler(event, context):
    key = event.get("input_key", INPUT_KEY) if isinstance(event, dict) else INPUT_KEY
    if not key.startswith("input/") or not key.lower().endswith(".mp4"):
        raise ValueError("input_key must be an MP4 object under input/")

    with tempfile.TemporaryDirectory() as work:
        source = Path(work) / "source.mp4"
        hls_dir = Path(work) / "hls"
        hls_dir.mkdir()
        s3.download_file(BUCKET, key, str(source))

        # H.264 + AAC in 6-second MPEG-TS segments, written as a complete VOD playlist.
        cmd = [
            FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-f", "hls", "-hls_time", "6", "-hls_playlist_type", "vod",
            "-hls_segment_filename", str(hls_dir / "segment_%03d.ts"),
            str(hls_dir / "index.m3u8"),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg failed: {result.stderr.strip()}")
        if not (hls_dir / "index.m3u8").exists():
            raise RuntimeError("FFmpeg finished but no playlist was written")

        uploaded = []
        for file in sorted(hls_dir.iterdir()):
            content_type = CONTENT_TYPES.get(file.suffix)
            if content_type is None:
                continue
            object_key = OUTPUT_PREFIX + file.name
            s3.upload_file(str(file), BUCKET, object_key, ExtraArgs={"ContentType": content_type})
            uploaded.append(object_key)

    summary = {"input": key, "outputs": uploaded}
    print(json.dumps(summary))
    return summary
