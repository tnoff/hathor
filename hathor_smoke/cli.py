'''
The hathor-smoke command line
'''
import click

from hathor_smoke.checks import DEFAULT_MAX_INDEX_AGE, DEFAULT_RETRIES, DEFAULT_TIMEOUT, Smoke, run_checks

@click.command()
@click.option('--base-url', envvar='HATHOR_SMOKE_BASE_URL', required=True, show_envvar=True,
              help='Public address of the server before the token, such as https://example.com/hathor')
@click.option('--token', envvar='HATHOR_TOKEN', required=True, show_envvar=True,
              help='The url token. Prefer the environment: a flag is visible in the process list')
@click.option('--max-index-age', type=click.IntRange(min=1), default=DEFAULT_MAX_INDEX_AGE, show_default=True,
              help='Oldest allowed index.json, in seconds')
@click.option('--timeout', type=click.IntRange(min=1), default=DEFAULT_TIMEOUT, show_default=True,
              help='Seconds to wait on one request')
@click.option('--retries', type=click.IntRange(min=0), default=DEFAULT_RETRIES, show_default=True,
              help='Retries on a connection error or a 502, 503 or 504')
@click.option('--allow-empty', is_flag=True, default=False,
              help='Do not fail when the index has no episodes in it')
@click.pass_context
def cli(ctx, base_url, token, max_index_age, timeout, retries, allow_empty):
    '''
    Check a deployed hathor server from the outside. Prints one line per check and exits 1 if
    any failed. Read only: nothing is synced, written or deleted
    '''
    smoke = Smoke(base_url, token, max_index_age=max_index_age, timeout=timeout, retries=retries,
                  allow_empty=allow_empty)
    try:
        results = run_checks(smoke)
    finally:
        smoke.close()
    for result in results:
        click.echo(f'{"PASS" if result.passed else "FAIL"} {result.name}: {result.detail}')
    failed = [result for result in results if not result.passed]
    click.echo(f'{len(results) - len(failed)}/{len(results)} checks passed')
    if failed:
        ctx.exit(1)
