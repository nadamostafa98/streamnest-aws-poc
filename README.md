# StreamNest – AWS video streaming PoC

StreamNest converts an MP4 into an HLS stream with AWS Lambda and FFmpeg, stores it in a private S3 bucket, and serves it through CloudFront using Origin Access Control (OAC). An HTML page plays it back with HLS.js.

## Live demo

**https://nadamostafa98.github.io/streamnest-aws-poc/**

Open it in Chrome, Edge, Firefox or Safari. Nothing to install and no AWS account needed. The page streams the processed video from the StreamNest CloudFront distribution. In DevTools → Network you can see the `index.m3u8` playlist and `.ts` segments coming from `*.cloudfront.net`.

## Architecture

```text
Browser (player on GitHub Pages, HLS.js)
        │  HTTPS
        ▼
CloudFront ──(OAC, on cache miss)──► S3 bucket (private, eu-north-1)
                                       input/   ← source MP4
                                       output/  ← HLS playlist + segments
                                          ▲
                                          │
                              Lambda + FFmpeg layer (invoked manually)
```

- The Lambda is run by hand. Uploading to S3 does not trigger it.
- It produces a single HLS rendition (no adaptive bitrate ladder).
- The player is a static page hosted on GitHub Pages, not on AWS. It needs no AWS credentials, it only requests public CloudFront URLs.

## Repository layout

| Path | Purpose |
| --- | --- |
| `lambda/lambda_function.py` | Downloads the MP4, runs FFmpeg, uploads the playlist and `.ts` segments |
| `index.html` | Redirects the GitHub Pages root to the player |
| `player/index.html` | Minimal HLS.js player |
| `policies/lambda-s3-policy.example.json` | Lambda role permissions: read `input/*`, write `output/*` |
| `policies/cloudfront-oac-bucket-policy.example.json` | Bucket policy letting one CloudFront distribution read `output/*` |
| `scripts/check-output.sh` | Lists the generated HLS files with the AWS CLI |
| `media/sample.mp4` | Sample video used in the demo |

## Rebuild it in your own AWS account (optional)

You only need this section to recreate the whole pipeline yourself. To see it working, use the [live demo](#live-demo).

### Prerequisites

- An AWS account that can manage S3, IAM, Lambda, CloudFront and CloudWatch.
- A static Linux x86_64 FFmpeg binary with `libx264` and `aac`, packaged as a Lambda layer (not included here, see step 3).
- The AWS CLI, only if you want to use `scripts/check-output.sh`.
- Python 3, to serve the player locally.

This will cost a little money if you're outside the Free Tier. Delete everything when you're done (see [Clean up](#clean-up)).

#### 1. S3 bucket

1. Create a bucket in `eu-north-1` (e.g. `your-streamnest-bucket`). Keep **Block all public access** on and use SSE-S3 encryption.
2. Upload `media/sample.mp4` (or your own MP4) to `input/sample.mp4`. The `output/` prefix is created by the Lambda.

#### 2. Lambda execution role

1. Create an IAM role for Lambda and attach `AWSLambdaBasicExecutionRole` so it can write logs.
2. Add an inline policy from `policies/lambda-s3-policy.example.json`, replacing `REPLACE_WITH_BUCKET_NAME`.

#### 3. FFmpeg layer

Put the FFmpeg executable at `bin/ffmpeg` inside a ZIP, make it executable (`chmod +x`) before zipping, and publish it as a layer in `eu-north-1`. Lambda mounts it at `/opt/bin/ffmpeg`.

There's no tested build recipe in this repo. Make sure the binary you use actually runs on Lambda's Python 3.12 runtime and that its license fits your use.

#### 4. Lambda function

1. Create `streamnest-video-processor`: Python 3.12, x86_64, the role from step 2, 1024 MB memory, 120 s timeout, 512 MB ephemeral storage.
2. Paste in `lambda/lambda_function.py`, attach the FFmpeg layer and deploy.
3. Set these environment variables:

   | Name | Required | Default |
   | --- | --- | --- |
   | `STREAMNEST_BUCKET` | yes | – |
   | `STREAMNEST_INPUT_KEY` | no | `input/sample.mp4` |
   | `STREAMNEST_OUTPUT_PREFIX` | no | `output/forest-video/` |
   | `FFMPEG_PATH` | no | `/opt/bin/ffmpeg` |

4. Run a test with the event `{}`. To process a different file, use `{"input_key": "input/other.mp4"}`. The key must be an `.mp4` under `input/`.
5. On success the function returns the uploaded keys, for example:

   ```json
   {"input": "input/sample.mp4", "outputs": ["output/forest-video/index.m3u8", "output/forest-video/segment_000.ts"]}
   ```

   If it fails, the FFmpeg error message appears in the exception and in CloudWatch Logs.

#### 5. CloudFront

1. Create a distribution with the S3 bucket as the origin. Use the bucket itself, not the static website endpoint.
2. Select **Origin access control** and let it sign requests.
3. Apply `policies/cloudfront-oac-bucket-policy.example.json` as the bucket policy, filling in the bucket name, account ID and distribution ID. The policy the CloudFront console suggests works too, but it grants access to the whole bucket rather than only `output/`.
4. Set the viewer protocol policy to **Redirect HTTP to HTTPS**.
5. Attach a response headers policy with CORS enabled. Allow `GET` and `HEAD`, and list each origin the player will run on, for example `https://YOUR_USERNAME.github.io` and `http://localhost:8000`. Without this, the browser blocks the playlist and segments.
6. Once deployed, check that `https://YOUR_DISTRIBUTION_DOMAIN/output/forest-video/index.m3u8` loads.

OAC only stops people from bypassing CloudFront to reach S3. Anyone with the CloudFront URL can still watch the video. Viewer authentication (signed URLs or cookies) is out of scope.

#### 6. Player

1. In `player/index.html`, change the domain in `playlistUrl` to your own distribution domain (e.g. `d123example.cloudfront.net`).
2. Serve the repository root:

   ```bash
   python -m http.server 8000
   ```

3. Open <http://localhost:8000/player/>. In DevTools → Network you should see `index.m3u8` and `.ts` requests going to `*.cloudfront.net`.

To host it like the live demo: push the repo to GitHub (it must be public on a free account), go to **Settings → Pages**, choose **Deploy from a branch**, then `main` and `/ (root)`. After a minute or two the player is at `https://YOUR_USERNAME.github.io/REPO_NAME/`.

Opening the file directly (`file://`) usually fails because the browser sends `Origin: null`, which the CORS policy won't allow.

#### 7. Check the output (optional)

```bash
export STREAMNEST_BUCKET=your-streamnest-bucket
sh scripts/check-output.sh
```

Set `STREAMNEST_OUTPUT_PREFIX` as well if you changed it on the Lambda.

### What "working" looks like

- The Lambda test succeeds and `output/forest-video/` contains `index.m3u8` and at least one segment.
- The bucket is still private: direct S3 URLs return 403, CloudFront URLs return 200.
- The video plays and seeking works in the player, both locally and on GitHub Pages.

## Not included

S3 event triggers, adaptive bitrate, DRM, viewer authentication, live streaming, cache invalidation, WAF, tracing, alarms and load testing. All of these would be needed before using this in production.

## Clean up

1. Disable and then delete the CloudFront distribution.
2. Empty and delete the S3 bucket.
3. Delete the Lambda function, the FFmpeg layer, and the IAM role.
4. Check the Billing console. Deleting resources doesn't refund charges you've already incurred.

## Credits

Sample forest footage by Ari ichorul / Vecteezy.
