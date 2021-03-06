from io import StringIO

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
            print(table) # will not actually print

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
            print(table) # will not actually print

        table_printed = mock_print.getvalue()
        table_row = table_printed.split('\n')[3]
        # make sure all variables are 100 chars
        for item in table_row.split('|')[1:-1]:
            self.assert_length(item.strip(), 50)

    def test_table_keys_capitalize(self):
        with mock.patch('sys.stdout', new_callable=StringIO) as mock_print:
            fields = ['foo', 'derp_herp']
            table = HandsomeTable(fields, 50)
            row = ['foo', 'derp']
            table.add_row(row)
            print(table) # will not actually print

        self.assertEqual(mock_print.getvalue(), "+-----+-----------+\n| Foo "
                                                "| Derp Herp |\n+-----+-----------+\n| "
                                                "foo |    derp   |\n+-----+-----------+\n")

    def test_table_sort_key_capitalize(self):
        with mock.patch('sys.stdout', new_callable=StringIO) as mock_print:
            fields = ['foo', 'derp_herp']
            table = HandsomeTable(fields, 50)
            table.add_row(['apple', 'cherry'])
            table.add_row(['jerry', 'derry'])
            table.add_row(['berry', 'perry'])
            print(table.get_string(sortby="foo"))# will not actually print


        self.assertEqual(mock_print.getvalue(), "+-------+-----------+\n|  Foo  | "
                                                "Derp Herp |\n+-------+-----------+\n| apple "
                                                "|   cherry  |\n| berry |   perry   |\n| "
                                                "jerry |   derry   |\n+-------+-----------+\n")
