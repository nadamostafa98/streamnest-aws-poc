#!/bin/sh
# List the HLS files the Lambda wrote to S3.
# Usage: STREAMNEST_BUCKET=my-bucket [STREAMNEST_OUTPUT_PREFIX=output/forest-video/] sh scripts/check-output.sh
set -eu
: "${STREAMNEST_BUCKET:?Set STREAMNEST_BUCKET to your S3 bucket name}"
PREFIX="${STREAMNEST_OUTPUT_PREFIX:-output/forest-video/}"
aws s3 ls "s3://${STREAMNEST_BUCKET}/${PREFIX}" --recursive
