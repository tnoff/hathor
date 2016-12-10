from prettytable import PrettyTable

class HandsomeTable(PrettyTable):
    def __init__(self, field_names, column_limit, **kwargs):
        if column_limit == -1:
            self.column_limit = None
        self.column_limit = column_limit
        super(HandsomeTable, self).__init__(field_names, **kwargs)

    def add_row(self, row_data):
        new_data = []
        for column in row_data:
            data = column
            if isinstance(column, basestring) and self.column_limit is not None:
                if len(column) > self.column_limit:
                    data = column[0:self.column_limit]
            new_data.append(data)
        super(HandsomeTable, self).add_row(new_data)
