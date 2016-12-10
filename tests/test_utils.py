from hathor import utils
from tests import utils as test_utils

class TestUtils(test_utils.TestHelper):
    def test_clean_stringy(self):
        self.assert_none(utils.clean_string(None))
        self.assert_not_none(utils.clean_string(''))
        self.assert_not_none(utils.clean_string('foo'))

    def test_normalize_name(self):
        self.assertEqual('a_b', utils.normalize_name('a______b'))
        self.assertEqual('a_b', utils.normalize_name('a&-b'))
