import argparse
import json

from hathor.audio import editor, metadata

def parse_args():
    p = argparse.ArgumentParser(description='Random tools for audio files')

    sub = p.add_subparsers(dest='module', description='Module')

    volumey = sub.add_parser('volume', help='Get graph/data about audio volume information')
    volumey_sub = volumey.add_subparsers(dest='command', help='Command')
    csvy = volumey_sub.add_parser('csv', help='Output volume data in CSV format')
    csvy.add_argument('input_file', help='Audio input file')
    csvy.add_argument('output_file', help='Audio output flie')
    pngy = volumey_sub.add_parser('png', help='Output volume data in PNG format')
    pngy.add_argument('input_file', help='Audio input file')
    pngy.add_argument('output_file', help='Audio output flie')

    tagy = sub.add_parser('tags', help='Metadata tags for media files')
    tagy_sub = tagy.add_subparsers(dest='command', help='Command')
    resety = tagy_sub.add_parser('update', help='Update audio tags')
    resety.add_argument('input_file', help='Audio input file')
    resety.add_argument('--date', help='Date track recorded')
    resety.add_argument('--artist', help='Performer, or track artist')
    resety.add_argument('--composer', help='Composer')
    resety.add_argument('--track-number', help='Track number, often in "X/Y" format')
    resety.add_argument('--album', help='Album name')
    resety.add_argument('--copyright', help='Copyright info')
    resety.add_argument('--conductor', help='Conductor')
    resety.add_argument('--genre', help='Genre')
    resety.add_argument('--disc-number', help='Disc number, often in "X/Y" format')
    resety.add_argument('--album-artist', help='Artist, or album artist')
    resety.add_argument('--title', help='Title of track')
    resety.add_argument('--website', help='Website url or information')

    gety = tagy_sub.add_parser('show', help='Get audio tags for file')
    gety.add_argument('input_file', help='Audio file input')

    deletey = tagy_sub.add_parser('delete', help='Delete tags from audio file')
    deletey.add_argument('input_file', help='Audio file input')
    deletey.add_argument('args', nargs='+', help='Args to delete')

    picy = sub.add_parser('picture', help='Pictures for audio file metadata')
    picy_sub = picy.add_subparsers(dest='command', help='Command')

    extract = picy_sub.add_parser('extract', help='Extract metadata picture from audio file')
    extract.add_argument('audio_file', help='Path to audio file')
    extract.add_argument('picture_output_path', help='Path to extracted picture')

    updatey = picy_sub.add_parser('update', help='Update metadata picture for audio file')
    updatey.add_argument('audio_file', help='Path to audio file')
    updatey.add_argument('picture_input_file', help='Path to picture to use')
    updatey.add_argument('--encoding', type=int, default=3, help='Encoding for file, 3 (utf-8) is default')
    updatey.add_argument('--picture-type', type=int, default=3, help='Type of picture, 3 (cover) is default')
    updatey.add_argument('--description', default='cover', help='Description of image, "cover" is default')

    return p.parse_args()

def volume_csv(args):
    print 'Writing data to %s' % args.output_file
    editor.volume_data_csv(args.input_file, args.output_file)

def volume_png(args):
    print 'Writing data to %s' % args.output_file
    editor.volume_data_png(args.input_file, args.output_file)

def tags_update(args):
    update_args = vars(args)
    update_args.pop('command')
    update_args.pop('module')
    inputy = update_args.pop('input_file')
    metadata.tags_update(inputy, **update_args)
    print 'Tags reset on file:%s' % inputy

def tags_show(args):
    data = metadata.tags_show(args.input_file)
    print json.dumps(data, indent=4)

def tags_delete(args):
    metadata.tags_delete(args.input_file, *args.args)
    print 'Args deleted on file:%s' % args.input_file

def picture_extract(args):
    metadata.picture_extract(args.audio_file, args.picture_output_path)
    print 'Picture extracted to path: %s' % args.picture_output_path

def picture_update(args):
    metadata.picture_update(args.audio_file, args.picture_input_file,
                            encoding=args.encoding, picture_type=args.picture_type,
                            description=args.description)
    print 'Updated picture for audio file:%s' % args.audio_file

FUNCTION_MAPPING = {
    'volume' : {
        'csv' : volume_csv,
        'png' : volume_png,
    },
    'tags' : {
        'update' : tags_update,
        'show' : tags_show,
        'delete' : tags_delete,
    },
    'picture' : {
        'extract' : picture_extract,
        'update' : picture_update,
    },
}

def main():
    args = parse_args()
    method = FUNCTION_MAPPING[args.module][args.command]
    method(args)
