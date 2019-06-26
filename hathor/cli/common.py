import argparse
import re

from prettytable import PrettyTable

from hathor.exc import CLIException

class HandsomeTable(PrettyTable):
    def __init__(self, field_names, column_limit, **kwargs):
        if column_limit == -1:
            self.column_limit = None
        self.column_limit = column_limit
        corrected_names = []
        for name in field_names:
            splitter = name.split('_')
            corrected_names.append(' '.join(i.capitalize() for i in splitter))
        super(HandsomeTable, self).__init__(corrected_names, **kwargs)

    def add_row(self, row_data):
        new_data = []
        for column in row_data:
            data = '%s' % column
            if isinstance(data, str) and self.column_limit is not None:
                if len(data) > self.column_limit:
                    data = data[:self.column_limit]
            new_data.append(data)
        super(HandsomeTable, self).add_row(new_data)

    def get_string(self, *args, **kwargs):
        sort_key = kwargs.pop('sortby', None)
        if sort_key:
            splitter = sort_key.split('_')
            kwargs['sortby'] = ' '.join(i.capitalize() for i in splitter)
        return super(HandsomeTable, self).get_string(*args, **kwargs)

class HathorCLI(object):
    def __init__(self, **kwargs):

        self.column_limit = kwargs.pop('column_limit', None)

        self.keys = kwargs.pop('keys', None)
        if self.keys:
            self.keys = self.keys.split(',')
        self.sort_key = kwargs.pop('sort_key', None)

        self.reverse_sort = kwargs.pop('reverse_sort', False)

        try:
            module = kwargs.pop('module')
            command = kwargs.pop('command')
        except KeyError:
            raise CLIException("Either module or command not supplied")

        function_name = '%s_%s' % (module, command)
        self.function_name = function_name.replace('-', '_')

class HathorArgparse(argparse.ArgumentParser):
    def error(self, message):
        '''
        Some logic here to keep the error printing consistent
        If theres a cli arg that contains "invalid choice: '<whatever>' (choose from 'opt1', 'opt2')"
        Make sure the options are presented in alphabetical order
        '''
        CHOICE_REGEX = ".* invalid choice: '[a-zA-Z]+' \(choose from (.*)\)"
        result = re.match(CHOICE_REGEX, message)
        if result:
            options = result.group(1)
            OPTIONS_REGEX = "'([a-zA-Z0-9]+)'"
            options_list = sorted(re.findall(OPTIONS_REGEX, options))
            sorted_output = ", ".join("'%s'" % opt for opt in options_list)
            message = message.replace(options, sorted_output)
        raise CLIException(message)
