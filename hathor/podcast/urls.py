from hathor import settings

def soundcloud_account(channel_name, soundcloud_client_id):
    base = 'http://api.soundcloud.com/resolve.json?url=http://soundcloud.com/%s&client_id=%s'
    return base % (channel_name, soundcloud_client_id)

def soundcloud_track_list(channel_id, soundcloud_client_id,
                          limit=settings.BROADCAST_UPDATE_URL_LIMIT):
    base = 'http://api.soundcloud.com/users/%s/tracks/?client_id=%s' % (channel_id, soundcloud_client_id)
    url = '%s&limit=%s&linked_partitioning=1' % (base, limit)
    return url

def youtube_channel_get(channel_id, google_api_key, page_token=None,
                        limit=settings.BROADCAST_UPDATE_URL_LIMIT):
    base = 'https://www.googleapis.com/youtube/v3/search?part=id%2Csnippet&order=date'
    limit_filter = '&maxResults=%d' % limit
    channel_filter = '&channelId=%s' % channel_id
    key = '&key=%s' % google_api_key
    url = '%s%s%s%s' % (base, limit_filter, channel_filter, key)
    if page_token:
        url = '%s&pageToken=%s' % (url, page_token)
    return url
