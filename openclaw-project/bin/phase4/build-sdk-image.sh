set -eu
cd /opt/openclaw-production
mkdir -p phase4-sdk-image
printf %s IyBSZXBhaXIgdGhlIG1pc3NpbmcgaG9zdC1wYWNrYWdlIHBlZXIgbGluayBmb3IgYnVuZGxlZCBuYXRpdmUgQ29kZXggc2V0dXAuCiMgQmFzZSByZW1haW5zIHRoZSBwcmV2aW91c2x5IGRlcGxveWVkIE9wZW5DbGF3IDIwMjYuOS42IGRpZ2VzdC4KRlJPTSBnaGNyLmlvL29wZW5jbGF3L29wZW5jbGF3QHNoYTI1Njo2MjgzMjY2OGUzZTVlMTM5Zjc0NWY3ZDNkZjg5MmM5MjUxZWI1MzMxOGI3ZDE0YTc2YzQxMGRkZTFmMjVkNzMwClVTRVIgcm9vdApSVU4gdGVzdCAhIC1lIC9hcHAvbm9kZV9tb2R1bGVzL29wZW5jbGF3ICYmIGxuIC1zIC9hcHAgL2FwcC9ub2RlX21vZHVsZXMvb3BlbmNsYXcKVVNFUiBub2RlCg== | base64 -d > phase4-sdk-image/Dockerfile
docker build --tag openclaw-gateway:2026.9.6-sdk-peer phase4-sdk-image
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --user 1000:1000 --entrypoint node openclaw-gateway:2026.9.6-sdk-peer --input-type=module -e 'await import("/app/dist/extensions/codex/.setup/native-auth-D64RzExG.mjs"); console.log("SDK_MODULE_LOAD_OK");'
docker image inspect openclaw-gateway:2026.9.6-sdk-peer --format '{{.Id}}'
