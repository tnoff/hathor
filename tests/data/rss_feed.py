from time import time
SIMPLE_RSS_FEED = {
    'feed': {
        'link': 'https://example.foo'
    },
    'entries': [
        {
            'link': 'https://example.foo/download1',
            'title': 'Episode 0',
            'published_parsed': time(),
        },
        {
            'link': 'https://example.foo/download2',
            'title': 'Episode 1',
            'published_parsed': time(),
        },
    ]
}