class HathorException(Exception):
    '''
    Generic Hathor Exception
    '''

class AudioFileException(Exception):
    '''
    Generic AudioFileException
    '''

class EpisodeNotReady(HathorException):
    '''
    Episode exists upstream but cannot be downloaded yet, for example a
    youtube or twitch broadcast that is live, upcoming, or still processing
    '''

class FunctionUndefined(Exception):
    '''
    Throw error if function not inherited
    '''

class CliException(Exception):
    '''
    Generic Cli Exception
    '''
