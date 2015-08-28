import yaml
import sys
import re
import argparse
from core.colorlog import log
from core.polymerase import Polymerase


def projectname(project_name):
    return re.sub('.*/', '', project_name)

def dump(data, fd):
    yaml.safe_dump(data, stream=fd, explicit_start=True, default_flow_style=False, indent=4, canonical=False, default_style=False)


def parse_args(parser):
    # common arguments
    parser.add_argument('--projects-conf', '-f', dest='projects_path', type=argparse.FileType('r'), required=True,  help='path of the projects.yaml file')
    parser.add_argument('--base-dir','-d', dest='base_dir', action='store', required=True, help='base dir for local repos')
    parser.add_argument('--projects','-p', dest='projects', action='store', type=projectname, help='comma separated list of project')
    parser.add_argument('-m', '--watch-method', dest='watch_method', action='store', help='upstream branch to consider')
    parser.add_argument('-w', '--watch-branches', dest='watch_branches', action='store', help='upstream branch to consider')

    subparsers = parser.add_subparsers(dest='command')

    parser_new_replica_patch = subparsers.add_parser('poll-replica', help='poll replica', description='poll replica')
    parser_new_replica_patch.add_argument('-c','--change-id', dest='change_id', action='store', help='change id to handle')

    parser_merge_recombination = subparsers.add_parser('merge-recombinations')
    parser_merge_recombination.add_argument('-r','--recombination-id', dest='recomb_id', action='store', help='change id to handle')

    parser_new_original_change = subparsers.add_parser('poll-original')
    parser_new_original_change.add_argument('-b', '--original-branch', dest='original_branch', action='store',  help='upstream branch to consider')

    parser_download_untested_recombinations = subparsers.add_parser('download-untested-recombinations')
    parser_download_untested_recombinations.add_argument('-v','--var-file', dest='var_file', type=argparse.FileType('w'), required=True, help='path to the file to be generated')
    parser_download_untested_recombinations.add_argument('-t','--tests-info-dir', dest='tests_info_dir', action='store', required=True, help='path to the file to be generated')
    parser_download_untested_recombinations.add_argument('-r','--recombination-id', dest='recomb_id', action='store', help='change id to handle')
    parser_download_untested_recombinations.add_argument('-w','--download-dir', dest='download_dir', action='store', help='change id to handle')

    parser_cleanup = subparsers.add_parser('cleanup')

    args = parser.parse_args()

    return args



if __name__=="__main__":

    parser = argparse.ArgumentParser(description='Map the git out of upstream')
    args = parse_args(parser)
    log.debugvar('args')

    projects = yaml.load(args.projects_path.read())
    try:
        gitnetic = Polymerase(projects, args.base_dir, filter_projects=args.projects, filter_method=args.watch_method, filter_branches=args.watch_branches)
    except ValueError:
        log.critical('No projects to handle')
        sys.exit(1)

    ## actions

    if args.command == 'download-untested-recombinations':
        tester_vars = gitnetic.download_untested_recombinations(args.download_dir, recomb_id=args.recomb_id)
        projects_info = tester_vars.pop('projects')
        dump(projects_info, args.var_file)
        for test_id in tester_vars:
            info_file_name = '%s/%s.yaml' % (args.tests_info_dir, test_id)
            with open(info_file_name, 'w') as change_file:
                dump(tester_vars[test_id], change_file)

    elif args.command == 'poll-replica':
        gitnetic.poll_replica(patches_change_id=args.change_id)

    elif args.command == 'merge-recombinations':
        gitnetic.check_approved_recombinations(recomb_id=args.recomb_id)

    elif args.command == 'poll-original':
        gitnetic.poll_original()

    elif args.command == 'cleanup':
        gitnetic.janitor()
