from StringIO import StringIO

import mock

from hathor import utils
from hathor.cli.common import HandsomeTable

from tests import utils as test_utils

class TestHandsomeTable(test_utils.TestHelper):
    def test_table_no_column_limit(self):
        with mock.patch('sys.stdout', new_callable=StringIO) as mock_print:
            fields = [utils.random_string() for _ in range(5)]
            table = HandsomeTable(fields, -1)
            row = [utils.random_string(length=101) for _ in range(5)]
            table.add_row(row)
            print table # will not actually print

        table_printed = mock_print.getvalue()
        table_row = table_printed.split('\n')[3]
        # make sure all variables are 100 chars
        for item in table_row.split('|')[1:-1]:
            self.assert_length(item.strip(), 100)

    def test_table_column_limit(self):
        with mock.patch('sys.stdout', new_callable=StringIO) as mock_print:
            fields = [utils.random_string() for _ in range(5)]
            table = HandsomeTable(fields, 50)
            row = [utils.random_string(length=101) for _ in range(5)]
            table.add_row(row)
            print table # will not actually print

        table_printed = mock_print.getvalue()
        table_row = table_printed.split('\n')[3]
        # make sure all variables are 100 chars
        for item in table_row.split('|')[1:-1]:
            self.assert_length(item.strip(), 50)
