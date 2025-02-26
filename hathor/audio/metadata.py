from mimetypes import guess_extension, guess_type
from pathlib import Path
from typing import List

from mutagen import File as mutagen_file
from mutagen.id3 import APIC, ID3
from mutagen.id3._util import ID3NoHeaderError
from mutagen.mp3 import HeaderNotFoundError

from hathor.exc import AudioFileException

def _generate_metadata(file_path: Path) -> mutagen_file:
    try:
        audio_file = mutagen_file(file_path, easy=True)
    except HeaderNotFoundError as e:
        raise AudioFileException(str(e)) from e
    if audio_file is None:
        raise AudioFileException(f'Unsupported type for tags on file {file_path}')
    return audio_file

def _generate_id3(file_path: Path) -> ID3:
    try:
        audio_file = ID3(file_path)
    except ID3NoHeaderError as error: #pylint:disable=protected-access
        raise AudioFileException(f'Invalid file {file_path} type -- {str(error)}') from error
    return audio_file

def tags_update(input_file: Path, key_values: dict) -> mutagen_file:
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
        try:
            audio_file[key] = value
        except TypeError as e:
            raise AudioFileException(f'Unable to add key value {key}={value} for file {input_file}') from e
    audio_file.save()
    return True

def tags_show(input_file: Path) -> mutagen_file:
    '''
    Get dictionary of audio tags for file
    input_file  :   audio file to get tags from
    '''
    audio_file = _generate_metadata(input_file)

    new_dict = {}
    for key, value in audio_file.items():
        new_dict[key] = value[0]
    return new_dict

def tags_delete(input_file: Path, tag_list: List[str]) -> mutagen_file:
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

def picture_extract(audio_file: Path, output_file: Path) -> dict:
    '''
    Extract picture from audio file to and output file
    audio_file      :   Input path of file you wish to extract picture from
    output_file     :   Output path of new picture file (will override file ending if necessary)
    '''
    audio_file = _generate_id3(audio_file)

    picture = None
    # sometimes keys can be weird and have suffixes, like "APIC:" or "APIC:png"
    for key in audio_file:
        if key.startswith('APIC'):
            picture = audio_file[key]
            break
    if picture is None:
        raise AudioFileException(f'Unable to find picture for file: {audio_file}')

    if not isinstance(output_file, Path):
        output_file = Path(output_file)

    if guess_extension(picture.mime) != output_file.suffix:
        raise AudioFileException(f'Invalid suffix {output_file.suffix} for mimetype {picture.mime}')

    with open(output_file, 'wb') as writer:
        writer.write(picture.data)

    return {
        'encoding' : picture.encoding,
        'mime' : picture.mime,
        'type' : picture.type,
        'desc' : picture.desc,
        'output_path' : str(output_file.resolve()),
    }

def picture_update(audio_file: Path, picture_file: Path,
                   encoding: int = 3, picture_type: int = 3,
                   description: str = 'cover'):
    '''
    Update a picture for an audio file from a seperate image
    audio_file           :   Path of audio file you wish to update
    picture_file         :   Path of image you wish to use
    encoding             :   Encoding of image, passed to mutagen. 3 is utf-8
    picture_type         :   Type of picture, passed to mutagen. 3 is cover image
    description          :   Description of image
    '''
    if not isinstance(picture_file, Path):
        picture_file = Path(picture_file)
    if not isinstance(audio_file, Path):
        audio_file = Path(audio_file)

    mime = guess_type(picture_file)[0]
    if not mime:
        raise AudioFileException(f'Unsupported image type: {picture_file}')

    with open(picture_file, 'rb') as reader:
        data = reader.read()

    generated_audio_file = _generate_id3(audio_file)
    keys_to_delete = []
    for key in generated_audio_file.keys():
        if key.startswith('APIC'):
            keys_to_delete.append(key)
    for key in keys_to_delete:
        del generated_audio_file[key]
    generated_audio_file['APIC'] = APIC(encoding=encoding, mime=mime,
                                        data=data, type=picture_type, desc=description)
    generated_audio_file.save()
    return True
