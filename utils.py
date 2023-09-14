import os
import json
import logging
import subprocess
from os import listdir
from os.path import isdir
from os.path import join as path_join
from connection_wrapper import ConnectionWrapper
from config import Config


CONDOR_STATUS = {'0': 'UNEXPLAINED',
                 '1': 'IDLE',
                 '2': 'RUN',
                 '3': 'REMOVED',
                 '4': 'DONE',
                 '5': 'HOLD',
                 '6': 'SUBMISSION ERROR'}


BRANCHES_CACHE = {}
CAMPAIGNS_CACHE = {}
CARDS_CACHE = {}
TUNES_CACHE = []


def clean_split(string, separator=',', maxsplit=-1):
    """
    Split a string by separator and collect only non-empty values
    """
    return [x.strip() for x in string.split(separator, maxsplit) if x.strip()]


def run_command(command):
    """
    Run a bash command and return stdout, stderr and exit code
    """
    if isinstance(command, list):
        command = '\n'.join(command)

    process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE)
    stdout, stderr = process.communicate()
    code = process.returncode
    stdout = stdout.decode('utf-8') if stdout is not None else None
    stderr = stderr.decode('utf-8') if stderr is not None else None
    return stdout, stderr, code


def get_jobs_in_condor(ssh=None):
    """
    Fetch jobs from HTCondor
    Return a dictionary where key is job id and value is status (IDLE, RUN, ...)
    """
    cmd = 'condor_q -af:h ClusterId JobStatus Cmd'
    if ssh:
        stdout, stderr, exit_code = ssh.execute_command(cmd)
    else:
        stdout, stderr, exit_code = run_command(cmd)

    if exit_code != 0:
        logger.error('HTCondor is failing (%s):\n%s\n%s', exit_code, stdout, stderr)
        raise Exception('HTCondor status check returned %s', exit_code)

    logger = logging.getLogger()
    lines = stdout.split('\n')
    if not lines or 'ClusterId JobStatus Cmd' not in lines[0]:
        logger.error('HTCondor is failing (%s):\n%s\n%s', exit_code, stdout, stderr)
        raise Exception('HTCondor is not working')

    jobs_dict = {}
    lines = lines[1:]
    for line in lines:
        if 'GRIDPACK_' not in line:
            continue

        columns = line.split()
        if not columns:
            continue

        job_id = columns[0]
        job_status = columns[1]
        jobs_dict[job_id] = CONDOR_STATUS.get(job_status, 'REMOVED')

    logger.info('Job status in HTCondor: %s', json.dumps(jobs_dict))
    return jobs_dict


def get_latest_log_output_in_condor(gridpack, ssh=None):
    """
    Scan the job output log and stores it into the filesystem
    """
    logger = logging.getLogger()
    condor_id = gridpack.get_condor_id()
    public_stream_folder = Config.get('public_stream_folder')
    generation_log_file = f'{public_stream_folder}/GRIDPACK_GENERATION_{gridpack.get_id()}.log'

    if condor_id == 0:
        raise AssertionError(
            (
                'This Gridpack should be already submitted and running. '
                'Its ID must not be zero'
            )
        )
    
    cmd = f"condor_ssh_to_job {condor_id} 'cat _condor_stdout' >> {generation_log_file}"
    if ssh:
        stdout, stderr, exit_code = ssh.execute_command(cmd)
    else:
        stdout, stderr, exit_code = run_command(cmd)

    if exit_code != 0:
        logger.error('HTCondor is failing (%s):\n%s\n%s', exit_code, stdout, stderr)
        raise Exception('HTCondor status check returned %s', exit_code)


def get_git_branches(repository, cache=True):
    """
    Return list of branches in the repostory
    """
    if not cache or repository not in BRANCHES_CACHE:
        headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64)'}
        with ConnectionWrapper('https://api.github.com') as conn:
            response = conn.api('GET', f'/repos/{repository}/branches', headers=headers)

        response = json.loads(response.decode('utf-8'))
        logger = logging.getLogger()
        branches = [b['name'] for b in response if b.get('name')]
        logger.debug('Found %s branches in %s', len(branches), repository)
        BRANCHES_CACHE[repository] = branches

    return BRANCHES_CACHE[repository]


def get_available_campaigns(cache=True):
    """
    Get campaigns and campaign templates
    """
    global CAMPAIGNS_CACHE
    if not cache or not CAMPAIGNS_CACHE:
        CAMPAIGNS_CACHE = {}
        campaigns_dir = os.path.join(Config.get('gridpack_files_path'), 'Campaigns')
        campaigns = [c for c in listdir(campaigns_dir) if isdir(path_join(campaigns_dir, c))]
        for name in campaigns:
            campaign_path = os.path.join(campaigns_dir, name)
            generators = [g for g in listdir(campaign_path) if isdir(path_join(campaign_path, g))]
            with open(path_join(campaign_path, f'{name}.json')) as campaign_json:
                campaign_dict = json.load(campaign_json)

            CAMPAIGNS_CACHE[name] = {'generators': generators,
                                     'tune': campaign_dict.get('tune', '')}

    return CAMPAIGNS_CACHE


def get_available_cards(cache=True):
    """
    Get generators, processes and datasets
    """
    global CARDS_CACHE
    if not cache or not CARDS_CACHE:
        CARDS_CACHE = {}
        cards_dir = os.path.join(Config.get('gridpack_files_path'), 'Cards')
        generators = [c for c in listdir(cards_dir) if isdir(path_join(cards_dir, c))]
        for generator in generators:
            generator_path = os.path.join(cards_dir, generator)
            processes = [p for p in listdir(generator_path) if isdir(path_join(generator_path, p))]
            for process in processes:
                process_path = os.path.join(generator_path, process)
                datasets = [d for d in listdir(process_path) if isdir(path_join(process_path, d))]
                CARDS_CACHE.setdefault(generator, {})[process] = datasets

    return CARDS_CACHE


def get_available_tunes(cache=True):
    """
    Get list of available tunes
    """
    global TUNES_CACHE
    if not cache or not TUNES_CACHE:
        imports_path = os.path.join(Config.get('gridpack_files_path'), 'Fragments', 'imports.json')
        if not os.path.isfile(imports_path):
            TUNES_CACHE = []
            return TUNES_CACHE

        with open(imports_path) as imports_file:
            imports = json.load(imports_file)

        TUNES_CACHE = sorted(list(set(imports.get('tune', []))))

    return TUNES_CACHE


def get_indentation(phrase, text):
    """
    Return indentation (number of spaces in the beginning of the line) for the
    first line in text that has a "phrase"
    """
    lines = [l for l in text.split('\n') if phrase in l]
    if not lines:
        return 0

    line = lines[0]
    return len(line) - len(line.lstrip())
