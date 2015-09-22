import yaml
import sys
import re
import argparse
import os
from core.colorlog import log,logsummary
from core.polymerase import Polymerase
import xml.etree.ElementTree as ET


def projectname(project_name):
    return re.sub('.*/', '', project_name)

def dump(data, path):
    with open(path, "w") as dump_file:
        yaml.safe_dump(data, stream=dump_file, explicit_start=True, default_flow_style=False, indent=4, canonical=False, default_style=False)


def parse_args(parser):
    # common arguments
    parser.add_argument('--projects-conf', '-f', dest='projects_path', type=argparse.FileType('r'), required=True,  help='path of the projects.yaml file')
    parser.add_argument('--base-dir','-d', dest='base_dir', action='store', required=True, help='base dir for local repos')
    parser.add_argument('--projects','-p', dest='projects', action='store', type=projectname, help='comma separated list of project')
    parser.add_argument('-m', '--watch-method', dest='watch_method', action='store', help='upstream branch to consider')
    parser.add_argument('-w', '--watch-branches', dest='watch_branches', action='store', help='upstream branch to consider')
    parser.add_argument('--no-fetch', dest='fetch', action='store_false', help='upstream branch to consider')

    subparsers = parser.add_subparsers(dest='command')

    parser_new_replica_patch = subparsers.add_parser('poll-replica', help='poll replica', description='poll replica')
    parser_new_replica_patch.add_argument('-c','--change-id', dest='change_id', action='store', help='change id to handle')

    parser_merge_recombination = subparsers.add_parser('merge-recombinations')
    parser_merge_recombination.add_argument('-r','--recombination-id', dest='recomb_id', action='store', help='change id to handle')

    parser_new_original_change = subparsers.add_parser('poll-original')
    parser_new_original_change.add_argument('-b', '--original-branch', dest='original_branch', action='store',  help='upstream branch to consider')

    parser_prepare_tests = subparsers.add_parser('prepare-tests')
    parser_prepare_tests.add_argument('-t','--tests-base-dir', dest='tests_basedir', action='store', required=True, help='path to the file to be generated')
    parser_prepare_tests.add_argument('-r','--recombination-id', dest='recomb_id', action='store', help='change id to handle')

    parser_cleanup = subparsers.add_parser('cleanup')

    parser_vote_recombinations = subparsers.add_parser('vote-recombinations', help='Vote on Recombinations', description='poll replica')
    parser_vote_recombinations.add_argument('-r','--recombination-id', dest='recomb_id', action='store', help='change id to handle')
    parser_vote_recombinations.add_argument('-t','--tests-base-dir', dest='tests_basedir', action='store', required=True, help='path to the file to be generated')

    args = parser.parse_args()

    return args



if __name__=="__main__":

    parser = argparse.ArgumentParser(description='Map the git out of upstream')
    args = parse_args(parser)
    log.debugvar('args')

    projects = yaml.load(args.projects_path.read())
    try:
        gitnetic = Polymerase(projects, args.base_dir, filter_projects=args.projects, filter_method=args.watch_method, filter_branches=args.watch_branches, fetch=args.fetch)
    except ValueError:
        log.critical('No projects to handle')
        sys.exit(1)

    ## actions

    if args.command == 'prepare-tests':
        try:
            os.makedirs(args.tests_basedir)
        except OSError:
            pass
        tester_vars = gitnetic.prepare_tests(args.tests_basedir, recomb_id=args.recomb_id)
        projects_info = tester_vars.pop('projects_conf')
        project_vars_path = "%s/project-vars.yaml" % (args.tests_basedir)
        dump(projects_info, project_vars_path)
        log.info("Written projects infos in %s" % (project_vars_path))
        for change_number in tester_vars:
            target_project = tester_vars[change_number]["target_project"]
            info_file_name = '%s/%s/%s/vars.yaml' % (args.tests_basedir, target_project, change_number)
            dump(tester_vars[change_number], info_file_name)
            log.info("Written test info for recombination %s in %s" % (change_number, info_file_name))

    if args.command == 'vote-recombinations':
        test_results = dict()
        for root, dirs, files in os.walk(args.tests_basedir):
            if 'vars.yaml' in files:
                with open(os.path.join(root, "vars.yaml")) as var_file:
                    test_vars = yaml.load(var_file)
                target_project = test_vars['target_project']
                try:
                    exists = test_results[target_project]
                except KeyError:
                    test_results[target_project] = dict()
                recombination_id = test_vars['recombination_id']
                test_results[target_project][recombination_id] = dict()
                for project_name in test_vars['tests']:
                    test_results[target_project][recombination_id][project_name] = dict()
                    for test_type in test_vars['tests'][project_name]["types"]:
                        test_results_file = test_vars['tests'][project_name]["types"][test_type]
                        try:
                            os.stat(args.tests_basedir + "/" + test_results_file)
                            test_results[target_project][recombination_id][project_name][test_type] = []
                            # TODO: load test results from xml format
                        except OSError:
                           test_results[target_project][recombination_id][project_name][test_type] = None
                           logsummary.error("Recombination id: %s , mIssing test result file %s" % (recombination_id, test_results_file))
        log.debugvar('test_results')
        if test_results:
            gitnetic.vote_recombinations(test_results, recomb_id=args.recomb_id)
        else:
            logsummary.info("No test results to vote")

    elif args.command == 'poll-replica':
        gitnetic.poll_replica(patches_change_id=args.change_id)

    elif args.command == 'merge-recombinations':
        gitnetic.check_approved_recombinations(recomb_id=args.recomb_id)

    elif args.command == 'poll-original':
        gitnetic.poll_original()

    elif args.command == 'cleanup':
        gitnetic.janitor()
