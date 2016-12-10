from hathor import settings

def soundcloud_track_list(channel_name, soundcloud_client_id):
    limit = settings.BROADCAST_UPDATE_URL_LIMIT
    base = 'http://api.soundcloud.com/users/%s/tracks/?client_id=%s' % (channel_name, soundcloud_client_id)
    url = '%s&limit=%s&linked_partitioning=1' % (base, limit)
    return url

def youtube_channel_get(channel_id, google_api_key, page_token=None):
    max_results = settings.BROADCAST_UPDATE_URL_LIMIT
    base = 'https://www.googleapis.com/youtube/v3/search?part=id%2Csnippet&order=date'
    limit_filter = '&maxResults=%d' % max_results
    channel_filter = '&channelId=%s' % channel_id
    key = '&key=%s' % google_api_key
    url = '%s%s%s%s' % (base, limit_filter, channel_filter, key)
    if page_token:
        url = '%s&pageToken=%s' % (url, page_token)
    return url
