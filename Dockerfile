FROM python:3.14-slim

# ffmpeg (and ffprobe, same package) for yt-dlp. Most youtube formats are
# delivered as separate video and audio streams -- the archive manager asks for
# bestvideo+bestaudio -- and yt-dlp aborts the download outright rather than
# degrading when it has nothing to merge them with:
#   ERROR: You have requested merging of multiple formats but ffmpeg is not installed
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Javascript runtime for yt-dlp's EJS support, which solves youtube's JS
# challenges. Without one yt-dlp warns "some formats may be missing" and silently
# drops the formats behind a challenge. Deno is yt-dlp's default runtime and this
# image publishes just the binary, multi-arch, so it copies straight in.
# https://github.com/yt-dlp/yt-dlp/wiki/EJS
COPY --from=denoland/deno:bin-2.5.4 /deno /usr/local/bin/deno

WORKDIR /app

COPY . .
RUN pip install --no-cache-dir .

VOLUME ["/data", "/podcasts", "/config"]

ENTRYPOINT ["hathor"]
CMD ["--help"]
