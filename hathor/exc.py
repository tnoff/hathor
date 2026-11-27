class HathorException(Exception):
    '''
    Generic Hathor Exception
    '''

class SyncFailure(HathorException):
    '''
    Raised at the END of a sync or download, after everything that could be done
    was done, when some podcasts or episodes failed. One bad feed does not stop the
    others: each failure is logged and recorded here instead

    failures : list of dicts with stage, podcast_id, podcast_name, episode_id (None
               for a podcast level failure) and error (scrubbed of url query strings)
    results  : what did succeed, such as the new episodes of an episode sync
    '''
    def __init__(self, failures: list[dict], results: list | None = None):
        self.failures = failures
        self.results = results if results is not None else []
        lines = [f'{len(failures)} failure(s) during sync:']
        for failure in failures[:10]:
            where = f'podcast {failure["podcast_id"]} ({failure["podcast_name"]})'
            if failure['episode_id'] is not None:
                where += f' episode {failure["episode_id"]}'
            lines.append(f'  {failure["stage"]} of {where}: {failure["error"]}')
        if len(failures) > 10:
            lines.append(f'  ... and {len(failures) - 10} more')
        super().__init__('\n'.join(lines))

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
