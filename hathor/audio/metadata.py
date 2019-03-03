import os

import mutagen
import mutagen.id3 as mutagen_id3
from mutagen.flac import FLAC, Picture

from hathor.exc import AudioFileException

def _generate_metadata(file_path):
    try:
        audio_file = mutagen.File(file_path, easy=True)
    except mutagen.mp3.HeaderNotFoundError as e:
        raise AudioFileException("Unable to generate audio headers:%s" % str(e))
    if audio_file is None:
        raise AudioFileException("Unsupported type for tags on file %s" % file_path)
    return audio_file

def _generate_id3(file_path):
    try:
        audio_file = mutagen_id3.ID3(file_path)
    except mutagen_id3._util.ID3NoHeaderError as error: #pylint:disable=protected-access
        raise AudioFileException("Invalid file %s type -- %s" % (file_path, str(error)))
    return audio_file

def _generate_flac(file_path):
    return FLAC(file_path)

def tags_update(input_file, key_values):
    '''
    Reset the audio tags on the file assocatied with an epsiode
    input_file       :   Path to file
    key_values       :   Dictionary of tags to update
    '''
    audio_file = _generate_metadata(input_file)

    for key, value in key_values.items():
        if value is None:
            continue
        try:
            del audio_file[key]
        except KeyError:
            pass
        audio_file[key] = value
    audio_file.save()
    return audio_file

def tags_show(input_file):
    '''
    Get dictionary of audio tags for file
    input_file  :   audio file to get tags from
    '''
    audio_file = _generate_metadata(input_file)

    new_dict = dict()
    for key, value in audio_file.items():
        new_dict[key] = value[0]
    return new_dict

def tags_delete(input_file, tag_list):
    '''
    Attempt to delete all tags in args from audio file
    input_file  :   audio_file to delete tags
    tag_list    :   tags to delete from input file
    '''
    audio_file = _generate_metadata(input_file)

    deleted_tags = []
    for tag in tag_list:
        try:
            del audio_file[tag]
            deleted_tags.append(tag)
        except KeyError:
            pass
    audio_file.save()
    return deleted_tags

def picture_extract(input_file, output_file):
    '''
    Extract picture from audio file to and output file
    input_file      :   Input path of file you wish to extract picture from
    output_file     :   Output path of new picture file (will override file ending if necessary)
    '''
    audio_file = _generate_id3(input_file)

    picture = None
    # sometimes keys can be weird and have suffixes, like "APIC:" or "APIC:png"
    for key in audio_file.keys():
        if key.startswith('APIC'):
            picture = audio_file[key]
            break
    if picture is None:
        raise AudioFileException("Unable to find picture for file:%s" % input_file)

    _, ending = os.path.splitext(output_file)

    if picture.mime == 'image/jpeg' and ending != '.jpg':
        output_file = '%s.jpg' % output_file
    elif picture.mime == 'image/png' and ending != '.png':
        output_file = '%s.png' % output_file

    with open(output_file, 'wb') as writer:
        writer.write(picture.data)

    return {
        'encoding' : picture.encoding,
        'mime' : picture.mime,
        'type' : picture.type,
        'desc' : picture.desc,
        'output_path' : output_file,
    }

def picture_update(audio_file, picture_file, encoding=3, picture_type=3, description='cover'):
    '''
    Update a picture for an audio file from a seperate image
    audio_file           :   Path of audio file you wish to update
    picture_file         :   Path of image you wish to use
    encoding             :   Encoding of image, passed to mutagen. 3 is utf-8
    picture_type         :   Type of picture, passed to mutagen. 3 is cover image
    description          :   Description of image
    '''
    if picture_file.endswith('.png'):
        mime = 'image/png'
    elif picture_file.endswith('.jpg') or picture_file.endswith('.jpeg'):
        mime = 'image/jpeg'
    else:
        raise AudioFileException("Unsupported image type:%s" % picture_file)

    with open(picture_file, 'rb') as reader:
        data = reader.read()

    # Check if file is flac or mp3
    if audio_file.endswith('.flac'):
        generated_audio_file = _generate_flac(audio_file)
        image = Picture()
        image.type = encoding
        image.desc = description
        image.data = data
        generated_audio_file.add_picture(image)
        generated_audio_file.save(audio_file)
    else:
        generated_audio_file = _generate_id3(audio_file)
        keys_to_delete = []
        for key in generated_audio_file.keys():
            if key.startswith('APIC'):
                keys_to_delete.append(key)
        for key in keys_to_delete:
            del generated_audio_file[key]
        generated_audio_file['APIC'] = mutagen_id3.APIC(encoding=encoding, mime=mime, #pylint:disable=no-member
                                                        data=data, type=picture_type, desc=description)
        generated_audio_file.save()
    return True
