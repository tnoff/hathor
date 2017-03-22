from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base

BASE = declarative_base()

def as_dict(row, datetime_output_format):
    data = {}
    for column in row.__table__.columns:
        value = getattr(row, column.name)
        if isinstance(value, datetime):
            value = value.strftime(datetime_output_format)
        data[column.name] = value
    return data

def inject_function(func):
    def decorated_class(cls):
        setattr(cls, func.__name__, func)
        return cls
    return decorated_class


@inject_function(as_dict)
class Podcast(BASE):
    __tablename__ = 'podcast'
    __table_args__ = (UniqueConstraint('archive_type', 'broadcast_id',
                                       name='_broadcast_indentifier'),)
    # unique keys
    id = Column(Integer, primary_key=True)
    name = Column(String(256), unique=True)
    # non unique but required
    archive_type = Column(String, nullable=False)
    broadcast_id = Column(String, nullable=False)
    # optional args
    max_allowed = Column(Integer)
    file_location = Column(String(10*1024))
    artist_name = Column(String(256))
    automatic_episode_download = Column(Boolean)

@inject_function(as_dict)
class PodcastEpisode(BASE):
    __tablename__ = 'podcast_episode'
    # unique keys
    id = Column(Integer, primary_key=True)
    download_url = Column(String(10*1024), unique=True)
    # keys set at creation, and inmutable
    title = Column(String(10*1024))
    description = Column(String(10*1024))
    date = Column(DateTime)
    podcast_id = Column(Integer, ForeignKey('podcast.id'))
    # optional, can be changed via client
    file_path = Column(String(10*1024))
    file_size = Column(Integer)
    prevent_deletion = Column(Boolean)


@inject_function(as_dict)
class PodcastTitleFilter(BASE):
    __tablename__ = 'podcast_title_filter'
    __table_args__ = (UniqueConstraint('podcast_id', 'regex_string',
                                       name='_repeating_filters'),)

    id = Column(Integer, primary_key=True)
    podcast_id = Column(Integer, ForeignKey('podcast.id'))
    regex_string = Column(String(2 * 1024), nullable=False)
