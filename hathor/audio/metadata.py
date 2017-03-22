import os

import mutagen
import mutagen.id3 as mutagen_id3

from hathor.exc import AudioFileException

def _generate_metadata(file_path):
    audio_file = mutagen.File(file_path, easy=True)
    if audio_file is None:
        raise AudioFileException("Unsupported type for tags on file %s" % file_path)
    return audio_file

def _generate_id3(file_path):
    try:
        audio_file = mutagen_id3.ID3(file_path)
    except mutagen_id3._util.ID3NoHeaderError as error: #pylint:disable=protected-access
        raise AudioFileException("Invalid file %s type -- %s" % (file_path, str(error)))
    return audio_file

def tags_update(file_path, **kwargs):
    '''Reset the audio tags on the file assocatied with an epsiode
       file_path        :   Path to file
       date             :   Date track recorded
       performer        :   Performer, or track artist
       composer         :   Composer
       track_number     :   Track number, often in "X/Y" format
       album            :   Album name
       copyright        :   Copyright info
       conductor        :   Conductor
       genre            :   Genre
       disc_number      :   Disc number, often in "X/Y" format
       album_artist     :   Album artist
       title            :   Title of track
       website          :   Website url or information
    '''
    audio_file = _generate_metadata(file_path)

    track = kwargs.pop('track_number', None)
    if track:
        kwargs['tracknumber'] = track

    disc = kwargs.pop('disc_number', None)
    if disc:
        kwargs['discnumber'] = disc

    album_artist = kwargs.pop('album_artist', None)
    if album_artist:
        kwargs['albumartist'] = album_artist

    for key, value in kwargs.items():
        if value is None:
            continue
        try:
            del audio_file[key]
        except KeyError:
            pass
        audio_file[key] = value
    audio_file.save()
    return audio_file

def tags_show(file_path):
    '''Get dictionary of audio tags for file
       file_path    :   audio file to get tags from
    '''
    audio_file = _generate_metadata(file_path)

    new_dict = dict()
    for key, value in audio_file.items():
        new_dict[key] = value[0]
    # check for track number and disk number
    track = new_dict.pop('tracknumber', None)
    if track is not None:
        new_dict['track_number'] = track
    disc = new_dict.pop('discnumber', None)
    if disc is not None:
        new_dict['disc_number'] = disc
    artist = new_dict.pop('albumartist', None)
    if artist is not None:
        new_dict['album_artist'] = artist
    return new_dict

def tags_delete(file_path, *args):
    '''Attempt to delete all tags in args from audio file
       file_path    :   audio_file to delete tags
    '''
    audio_file = _generate_metadata(file_path)

    deleted_tags = []
    for tag in args:
        if tag == 'disc_number':
            tag = 'discnumber'
        elif tag == 'track_number':
            tag = 'tracknumber'
        elif tag == 'album_artist':
            tag = 'albumartist'
        try:
            del audio_file[tag]
            deleted_tags.append(tag)
        except KeyError:
            pass
    audio_file.save()

def picture_extract(input_path, output_path):
    '''Extract picture from audio file to and output file
       input_path       :   Input path of file you wish to extract picture from
       output_path      :   Output path of new picture file (will override file ending if necessary)
    '''
    audio_file = _generate_id3(input_path)

    picture = None
    # sometimes keys can be weird and have suffixes, like "APIC:" or "APIC:png"
    for key in audio_file.keys():
        if key.startswith('APIC'):
            picture = audio_file[key]
            break
    if picture is None:
        raise AudioFileException("Unable to find picture for file:%s" % input_path)

    _, ending = os.path.splitext(output_path)

    if picture.mime == 'image/jpeg' and ending != '.jpg':
        output_path = output_path + '.jpg'
    elif picture.mime == 'image/png' and ending != '.png':
        output_path = output_path + '.png'

    with open(output_path, 'wb') as writer:
        writer.write(picture.data)

    return {
        'encoding' : picture.encoding,
        'mime' : picture.mime,
        'type' : picture.type,
        'desc' : picture.desc,
        'output_path' : output_path,
    }

def picture_update(audio_file_path, image_path, encoding=3, picture_type=3, description='cover'):
    '''Update a picture for an audio file from a seperate image
       audio_file_path      :   Path of audio file you wish to update
       image_path           :   Path of image you wish to use
       encoding             :   Encoding of image, passed to mutagen. 3 is utf-8
       picture_type         :   Type of picture, passed to mutagen. 3 is cover image
       description          :   Description of image
    '''
    audio_file = _generate_id3(audio_file_path)

    if image_path.endswith('.png'):
        mime = 'image/png'
    elif image_path.endswith('.jpg') or image_path.endswith('.jpeg'):
        mime = 'image/jpeg'
    else:
        raise AudioFileException("Unsupported image type:%s" % image_path)

    with open(image_path, 'r') as reader:
        data = reader.read()

    for key in audio_file.keys():
        if key.startswith('APIC'):
            del audio_file[key]

    audio_file['APIC'] = mutagen_id3.APIC(encoding=encoding, mime=mime, #pylint:disable=no-member
                                          data=data, type=picture_type, desc=description)
    audio_file.save()
