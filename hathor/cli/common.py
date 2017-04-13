import argparse

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
            if isinstance(data, basestring) and self.column_limit is not None:
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

        module = kwargs.pop('module')
        command = kwargs.pop('command')

        function_name = '%s_%s' % (module, command)
        self.function_name = function_name.replace('-', '_')

class HathorArgparse(argparse.ArgumentParser):
    def error(self, message):
        raise CLIException(message)
