import json
import sys

from hathor import settings
from hathor.audio import metadata
from hathor.exc import CLIException
from hathor.cli.common import HandsomeTable, HathorArgparse, HathorCLI

class AudioCLI(HathorCLI):
    def __init__(self, **kwargs):
        HathorCLI.__init__(self, **kwargs)

        self.kwargs = kwargs
        # make sure all common args arent used
        for key in ['column_limit', 'keys', 'sort_key',
                    'command', 'module', 'reverse_sort']:
            self.kwargs.pop(key, None)

    def run_command(self):
        method = getattr(metadata, self.function_name)
        return_value = method(**self.kwargs)
        self.print_value(return_value)

    def print_value(self, value): #pylint:disable=no-self-use
        # Check type of value to see what to print
        # - Check if bool
        if isinstance(value, bool):
            if value is True:
                print('Success')
            else:
                print('Fail')
            return
        # - Check to see if dict
        if isinstance(value, dict):
            table = HandsomeTable(["key", "value"], self.column_limit)
            for key, val in value.items():
                table.add_row([key, val])
            print(table.get_string(sortby='key', reversesort=self.reverse_sort).encode('utf-8'))
            return

        # - Check if list of strings
        if isinstance(value, list):

            try:
                first_value = value[0]
            except IndexError:
                return

            if isinstance(first_value, str):
                print(', '.join('%s' % i for i in value))
                return


def parse_args(args):
    p = HathorArgparse(description='Random tools for audio files')
    p.add_argument('-c', '--column-limit', default=settings.COLUMN_LIMIT_DEFAULT,
                   type=int, help="Limit on length of columns in output")
    p.add_argument('-k', '--keys', help="Common seperated list of keys to show")
    p.add_argument('-sk', '--sort-key', help="Sort output based on key")
    p.add_argument('-r', '--reverse-sort', action='store_true', help="Show table output in reverse order")

    sub = p.add_subparsers(dest='module', description='Module')

    tagy = sub.add_parser('tags', help='Metadata tags for media files')
    tagy_sub = tagy.add_subparsers(dest='command', help='Command')

    resety = tagy_sub.add_parser('update', help='Update audio tags')
    resety.add_argument('input_file', help='Audio input file')
    resety.add_argument('key_values', type=json.loads,
                        help='JSON input, key value pairs to update tags')

    gety = tagy_sub.add_parser('show', help='Get audio tags for file')
    gety.add_argument('input_file', help='Audio file input')

    deletey = tagy_sub.add_parser('delete', help='Delete tags from audio file')
    deletey.add_argument('input_file', help='Audio file input')
    deletey.add_argument('tag_list', nargs='+', help='Args to delete')

    picy = sub.add_parser('picture', help='Pictures for audio file metadata')
    picy_sub = picy.add_subparsers(dest='command', help='Command')

    extract = picy_sub.add_parser('extract', help='Extract metadata picture from audio file')
    extract.add_argument('input_file', help='Path to audio file')
    extract.add_argument('output_file', help='Path to extracted picture')

    updatey = picy_sub.add_parser('update', help='Update metadata picture for audio file')
    updatey.add_argument('audio_file', help='Path to audio file')
    updatey.add_argument('picture_file', help='Path to picture to use')
    updatey.add_argument('--encoding', type=int, default=3, help='Encoding for file, 3 (utf-8) is default')
    updatey.add_argument('--picture-type', type=int, default=3, help='Type of picture, 3 (cover) is default')
    updatey.add_argument('--description', default='cover', help='Description of image, "cover" is default')

    return vars(p.parse_args(args))

def main():
    try:
        args = parse_args(sys.argv[1:])
    except CLIException as error:
        print("CLI Exception:", str(error))
        return
    x = AudioCLI(**args)
    x.run_command()
