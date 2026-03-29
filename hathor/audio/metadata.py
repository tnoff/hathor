from mimetypes import guess_extension, guess_type
from pathlib import Path

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
        return ID3(file_path)
    except ID3NoHeaderError as error:
        raise AudioFileException(f'Invalid file {file_path} type -- {str(error)}') from error

def tags_update(input_file: Path, key_values: dict) -> bool:
    '''
    Reset the audio tags on the file associated with an episode
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

def tags_show(input_file: Path) -> dict:
    '''
    Get dictionary of audio tags for file
    input_file  :   audio file to get tags from
    '''
    audio_file = _generate_metadata(input_file)

    return {key: value[0] for key, value in audio_file.items()}

def tags_delete(input_file: Path, tag_list: list[str]) -> list[str]:
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

def picture_extract(input_file: Path, output_file: Path) -> dict:
    '''
    Extract picture from audio file to an output file
    input_file      :   Input path of file you wish to extract picture from
    output_file     :   Output path of new picture file
    '''
    id3 = _generate_id3(input_file)

    picture = None
    # sometimes keys can be weird and have suffixes, like "APIC:" or "APIC:png"
    for key in id3:
        if key.startswith('APIC'):
            picture = id3[key]
            break
    if picture is None:
        raise AudioFileException(f'Unable to find picture for file: {input_file}')

    output_file = Path(output_file)

    expected_ext = guess_extension(picture.mime)
    if expected_ext is None:
        raise AudioFileException(f'Unrecognised picture mimetype {picture.mime}')
    if expected_ext != output_file.suffix:
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
    Update a picture for an audio file from a separate image
    audio_file           :   Path of audio file you wish to update
    picture_file         :   Path of image you wish to use
    encoding             :   Encoding of image, passed to mutagen. 3 is utf-8
    picture_type         :   Type of picture, passed to mutagen. 3 is cover image
    description          :   Description of image
    '''
    picture_file = Path(picture_file)
    audio_file = Path(audio_file)

    mime = guess_type(picture_file)[0]
    if not mime:
        raise AudioFileException(f'Unsupported image type: {picture_file}')

    with open(picture_file, 'rb') as reader:
        data = reader.read()

    id3 = _generate_id3(audio_file)
    for key in [k for k in id3.keys() if k.startswith('APIC')]:
        del id3[key]
    id3['APIC'] = APIC(encoding=encoding, mime=mime,
                       data=data, type=picture_type, desc=description)
    id3.save()
    return True
