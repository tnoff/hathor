class SmokeFailure(Exception):
    '''
    A check did not pass. The message says what was wrong and never holds the url token
    '''
