import os
import logging
import shutil
import pathlib
import json
import time
from copy import deepcopy
from config import Config
from utils import get_available_campaigns, get_available_cards, get_git_branches
from user import User


CORES = 8
MEMORY = CORES * 2000


class Gridpack():

    schema = {
        '_id': '',
        'last_update': 0,
        'campaign': '',
        'generator': '',
        'process': '',
        'dataset': '',
        'tune': '',
        'events': 0,
        'genproductions': '',
        'status': '',
        'condor_status': '',
        'condor_id': 0,
        'archive': '',
        'dataset_name': '',
        'history': [],
        'prepid': '',
    }

    def __init__(self, data):
        if self.__class__ is Gridpack:
            raise TypeError('Gridpack is an abstract class. Instantiate it with a subclass.')

        self.logger = logging.getLogger()
        self.data = data

    @staticmethod
    def make(data):
        """
        Make gridpack of appropriate subclass given data
        """
        generator = data['generator']
        if generator == "MadGraph5_aMCatNLO":
            from madgraph_gridpack import MadgraphGridpack
            return MadgraphGridpack(data)

        if generator == 'Powheg':
            from powheg_gridpack import PowhegGridpack
            return PowhegGridpack(data)

        raise Exception(f'Could not make gridpack for generator {generator}')

    def validate(self):
        for key, value in self.schema.items():
            if key not in self.data:
                self.data[key] = deepcopy(value)

        data_keys = set(self.data.keys())
        schema_keys = set(self.schema.keys())
        missing_keys = schema_keys - data_keys
        if missing_keys:
            return f'Missing keys {",".join(list(missing_keys))}'

        unknown_keys = data_keys - schema_keys
        if unknown_keys:
            return f'Unknown keys {",".join(list(unknown_keys))}'

        branches = get_git_branches(Config.get('gen_repository'), cache=True)
        genproductions = self.data['genproductions']
        if genproductions not in branches:
            return f'Bad GEN productions branch "{genproductions}"'

        events = self.data['events']
        if events <= 0:
            return f'Bad events "{events}"'

        campaigns = get_available_campaigns()
        campaign = self.data['campaign']
        if campaign not in campaigns:
            return f'Bad campaign "{campaign}"'

        generator = self.data['generator']
        if generator not in campaigns[campaign]['generators']:
            return f'Bad generator "{generator}"'
        
        cards = get_available_cards()
        process = self.data['process']
        if process not in cards[generator]:
            return f'Bad process "{process}"'

        dataset = self.data['dataset']
        if dataset not in cards[generator][process]:
            return f'Bad dataset "{dataset}"'

        return None

    def reset(self):
        self.set_status('new')
        self.data['archive'] = ''
        self.data['dataset_name'] = self.get_dataset_name()
        self.set_condor_status('')
        self.set_condor_id(0)

    def get_id(self):
        return self.data['_id']

    def get_status(self):
        return self.data['status']

    def set_status(self, status):
        """
        Setter for status
        """
        self.data['status'] = status

    def get_condor_status(self):
        return self.data['condor_status']

    def set_condor_status(self, condor_status):
        """
        Setter for condor status
        """
        self.data['condor_status'] = condor_status

    def get_condor_id(self):
        return self.data['condor_id']

    def set_condor_id(self, condor_id):
        """
        Setter for condor id
        """
        self.data['condor_id'] = condor_id

    def set_prepid(self, prepid):
        """
        Setter for prepid in McM
        """
        self.data['prepid'] = prepid

    def get(self, key):
        """
        Return a value from data dictionary
        """
        return self.data[key]

    def get_json(self):
        return deepcopy(self.data)

    def get_dataset_dict(self):
        """
        Return a dictionary from Cards directory
        """
        if hasattr(self, 'dataset_dict'):
            return self.dataset_dict

        dataset_name = self.data['dataset']
        cards_path = self.get_cards_path()
        dataset_dict_file = os.path.join(cards_path, f'{dataset_name}.json')
        self.logger.debug('Reading %s', dataset_dict_file)
        with open(dataset_dict_file) as input_file:
            dataset_dict = json.load(input_file)

        self.dataset_dict = dataset_dict
        return dataset_dict

    def get_campaign_dict(self):
        """
        Return a dictionary from Campaigns directory
        """
        if hasattr(self, 'campaign_dict'):
            return self.campaign_dict

        campaign = self.data['campaign']
        campaign_path = self.get_campaign_path()
        campaign_dict_file = os.path.join(campaign_path, f'{campaign}.json')
        self.logger.debug('Reading %s', campaign_dict_file)
        with open(campaign_dict_file) as input_file:
            campaign_dict = json.load(input_file)

        self.campaign_dict = campaign_dict
        return campaign_dict

    def get_cards_path(self):
        """
        Return path to relevant cards directory
        """
        generator = self.data['generator']
        process = self.data['process']
        dataset_name = self.data['dataset']
        files_dir = Config.get('gridpack_files_path')
        cards_path = os.path.join(files_dir, 'Cards', generator, process, dataset_name)
        return cards_path

    def get_campaign_path(self):
        """
        Return path to relevant campaign directory
        """
        campaign = self.data['campaign']
        files_dir = Config.get('gridpack_files_path')
        campaign_path = os.path.join(files_dir, 'Campaigns', campaign)
        return campaign_path

    def get_templates_path(self):
        """
        Return path to templates directory
        """
        campaign_path = self.get_campaign_path()
        generator = self.data['generator']
        template_path = os.path.join(campaign_path, generator, 'Templates')
        return template_path

    def get_model_params_path(self):
        """
        Return path to model params directory
        """
        campaign_path = self.get_campaign_path()
        generator = self.data['generator']
        model_params_path = os.path.join(campaign_path, generator, 'ModelParams')
        return model_params_path

    def get_job_files_path(self):
        """
        Return path of local job files
        """
        local_dir = self.local_dir()
        job_files = os.path.join(local_dir, 'input_files')
        return job_files

    def mkdir(self):
        """
        Make local directory of gridpack
        """
        gridpack_id = self.get_id()
        local_directory = f'gridpacks/{gridpack_id}'
        pathlib.Path(local_directory).mkdir(parents=True, exist_ok=True)

    def rmdir(self):
        """
        Remove local directory of gridpack
        """
        gridpack_id = self.get_id()
        local_directory = f'gridpacks/{gridpack_id}'
        shutil.rmtree(local_directory, ignore_errors=True)

    def local_dir(self):
        """
        Return path to local directory of gridpack files
        """
        gridpack_id = self.get_id()
        return os.path.abspath(f'gridpacks/{gridpack_id}')

    def add_history_entry(self, entry):
        """
        Add a simple string history entry
        """
        user = User().get_username()
        timestamp = int(time.time())
        entry = entry.strip()
        self.data.setdefault('history', []).append({'user': user,
                                                    'time': timestamp,
                                                    'action': entry})

    def get_users(self):
        """
        Return a list of unique usernames of users in history
        """
        users = set(x['user'] for x in self.data['history'] if x['user'] != 'automatic')
        return sorted(list(users))

    def prepare_job_archive(self):
        """
        Make an archive with all necessary card files
        """
        raise NotImplementedError('prepare_job_archive() must be implemented in subclass')

    def customize_file(self, input_file_name, user_additions, replacements):
        """
        Return a file customized with additional lines and variable replacements
        """
        # Initial file
        self.logger.debug('Reading file %s', input_file_name)
        with open(input_file_name) as input_file:
            contents = input_file.read()

        # Append user settings
        if user_additions:
            contents = contents.strip() + '\n\n# User settings\n'
            for user_line in user_additions:
                self.logger.debug('Appeding %s', user_line)
                contents += f'{user_line}\n'

        # Variable replacement
        if replacements:
            for variable, value in replacements.items():
                self.logger.debug('Replacing $%s with "%s"', variable, value)
                contents = contents.replace(f'${variable}', str(value))

        return contents.strip() + '\n'

    def prepare_script(self):
        """
        Make a bash script that will run in condor
        """
        repository = Config.get('gen_repository')
        generator = self.data['generator']
        dataset_name = self.data['dataset']
        genproductions = self.data['genproductions']
        command = ['#!/bin/sh',
                   'export HOME=$(pwd)',
                   'export ORG_PWD=$(pwd)',
                   f'export NB_CORE={CORES}',
                   f'wget https://github.com/{repository}/tarball/{genproductions} -O genproductions.tar.gz',
                   'tar -xzf genproductions.tar.gz',
                   f'GEN_FOLDER=$(ls -1 | grep {repository.replace("/", "-")}- | head -n 1)',
                   'echo $GEN_FOLDER',
                   'mv $GEN_FOLDER genproductions',
                   'cd genproductions',
                   'git init',
                   'cd ..',
                   f'mv input_files.tar.gz genproductions/bin/{generator}/',
                   f'cd genproductions/bin/{generator}',
                   'tar -xzf input_files.tar.gz',
                   'echo "Input files:"',
                   'ls -lha input_files/',
                   'echo "Running gridpack_generation.sh"',
                   # Set "pdmv" queue
                   f'./gridpack_generation.sh {dataset_name} input_files pdmv',
                   'echo ".t*z archives after gridpack_generation.sh:"',
                   'ls -lha *.t*z',
                   f'mv *{dataset_name}*.t*z $ORG_PWD']

        script_name = f'GRIDPACK_{self.get_id()}.sh'
        script_path = os.path.join(self.local_dir(), script_name)
        self.logger.debug('Writing sh script to %s', script_path)
        with open(script_path, 'w') as script_file:
            script_file.write('\n'.join(command))

        os.system(f"chmod a+x {script_path}")

    def prepare_jds_file(self):
        """
        Make condor job description file
        """
        gridpack_id = self.get_id()
        script_name = f'GRIDPACK_{gridpack_id}.sh'
        jds = [f'executable              = {script_name}',
               'transfer_input_files    = input_files.tar.gz',
               'when_to_transfer_output = on_exit',
               'should_transfer_files   = yes',
               '+JobFlavour             = "testmatch"',
               # '+JobFlavour             = "longlunch"',
               'output                  = output.log',
               'error                   = error.log',
               'log                     = job.log',
               f'RequestCpus             = {CORES}',
               f'RequestMemory           = {MEMORY}',
               '+accounting_group       = highprio',
               '+AccountingGroup        = "highprio.pdmvserv"',
               '+AcctGroup              = "highprio"',
               '+AcctGroupUser          = "pdmvserv"',
               '+DESIRED_Sites          = "T2_CH_CERN"',
               '+REQUIRED_OS            = "rhel7"',
               'leave_in_queue          = JobStatus == 4 && (CompletionDate =?= UNDEFINED || ((CurrentTime - CompletionDate) < 7200))',
               '+CMS_Type               = "test"',
               '+CMS_JobType            = "PdmVGridpack"',
               '+CMS_TaskType           = "PdmVGridpack"',
               '+CMS_SubmissionTool     = "Condor_SI"',
               '+CMS_WMTool             = "Condor_SI"',
               'queue']

        jds_name = f'GRIDPACK_{gridpack_id}.jds'
        jds_path = os.path.join(self.local_dir(), jds_name)
        self.logger.debug('Writing JDS to %s', jds_path)
        with open(jds_path, 'w') as jds_file:
            jds_file.write('\n'.join(jds))

    def get_dataset_name(self):
        """
        Make a full dataset name out of dataset, tune and beam energy
        """
        dataset = self.data['dataset']
        tune = self.data['tune']
        campaign_dict = self.get_campaign_dict()
        energy = float(campaign_dict.get('beam', 0) * 2)
        energy = ('%.2f' % (energy / 1000)).rstrip('.0').replace('.', 'p')
        tune_energy = f'Tune{tune}_{energy}TeV'
        dataset_name = dataset.split('_')
        dataset_name.insert(-1, tune_energy)
        dataset_name = '_'.join(dataset_name)
        self.logger.debug('Dataset name for %s is %s', self, dataset_name)
        return dataset_name

    def __str__(self) -> str:
        gridpack_id = self.get_id()
        campaign = self.data['campaign']
        dataset = self.data['dataset']
        generator = self.data['generator']
        status = self.get_status()
        condor_status = self.get_condor_status()
        condor_id = self.get_condor_id()
        return (f'Gridpack <{gridpack_id}> campaign={campaign} dataset={dataset} '
                f'generator={generator} status={status} condor={condor_status} ({condor_id})')
