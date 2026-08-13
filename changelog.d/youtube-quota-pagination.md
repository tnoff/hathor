### Changed

- Youtube episode syncs now read a channel's uploads playlist through `playlistItems.list` instead of `search.list`. The two return the same fields, but `search.list` costs 100 units of the 10,000 unit daily API quota per call while `playlistItems.list` costs 1. Page size is also set explicitly to 50, the maximum; the API default of 5 was spending a call on every fifth video.
- A sync now stops paging once it sees three videos in a row that are already stored, so a routine sync of a channel with nothing new costs one call instead of walking the whole back catalogue. Known videos are recognised before the title filters run, so a filter that rarely matches can no longer keep a walk going to the oldest upload.
- Paging is capped at 20 pages per sync, so no single podcast can page through an entire channel. The first sync of a very large channel may need to run more than once to reach the oldest uploads.
- Youtube API calls now ask the google client for retries, so transient 429s and rate-limit 403s back off and retry instead of failing the sync. An exhausted daily quota raises a plain "Youtube api daily quota exceeded" error rather than a raw HttpError.
- Archive managers are built once per client instead of once per episode, so a download run reuses one google API client and one twitch access token.
