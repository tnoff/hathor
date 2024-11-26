def youtube_channel_get(channel_id, google_api_key, page_token=None,
                        limit=8):
    base = 'https://www.googleapis.com/youtube/v3/search?part=id%2Csnippet&order=date'
    limit_filter = '&maxResults=%d' % limit
    channel_filter = '&channelId=%s' % channel_id
    key = '&key=%s' % google_api_key
    url = '%s%s%s%s' % (base, limit_filter, channel_filter, key)
    if page_token:
        url = '%s&pageToken=%s' % (url, page_token)
    return url
