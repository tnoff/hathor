from time import struct_time

SIMPLE_RSS_FEED = {
    'feed': {
        'link': 'https://example.foo'
    },
    'entries': [
        {
            'links': [
                {
                    'href': 'https://example.foo/download1.mp3',
                    'type': 'audio/mpeg',
                }
            ],
            'title': 'Episode 0',
            'published_parsed': struct_time((2024, 12, 11, 22, 40, 1, 2, 346, -1)),
            'id': '123456'
        },
        {
            'links': [
                {
                    'href': 'https://example.foo/download2.mp3',
                    'type': 'audio/mpeg',
                }
            ],
            'title': 'Episode 1',
            'published_parsed': struct_time((2024, 12, 11, 23, 40, 1, 2, 346, -1)),
            'id': '123405690'
        },
    ]
}