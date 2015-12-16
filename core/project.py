import pprint
import re
import copy
import os
import yaml
from colorlog import log, logsummary
from collections import OrderedDict
from repotypes.git import Underlayer
from exceptions import *


class Project(object):

    status_impact = {
        "MERGED": 2,
        "APPROVED": 1,
        "PRESENT": 1,
        "MISSING": 0
    }

    def __init__(self, project_name, project_info, local_dir, fetch=True):
        self.project_name = project_name
        self.recombinations = dict()
        self.commits = dict()

        log.info('Current project:\n' + pprint.pformat(project_info))
        self.original_project = project_info['original']
        self.replica_project = project_info['replica']
        self.deploy_name = project_info['deploy-name']
        self.rev_deps = None
        if 'rev-deps' in project_info:
            self.rev_deps = project_info['rev-deps']

        self.test_types = []
        if "tests" in project_info['replica'] and project_info["replica"]["tests"] is not None:
            self.test_types = project_info["replica"]["tests"]

        self.replication_strategy = project_info['replication-strategy']
        self.test_minimum_score = 0

        self.patches_branch_suffix = "-patches"
        self.target_branch_suffix = "-tag"
        # Set up local repo
        self.underlayer = Underlayer(project_name, local_dir)

        # Set up remotes
        self.underlayer.set_replica(self.replica_project['location'], self.replica_project['name'], fetch=fetch)
        self.underlayer.set_original(self.original_project['type'], self.original_project['location'], self.original_project['name'], fetch=fetch)

        if "mirror" in project_info['replica']:
            self.underlayer.set_replica_mirror(project_info['replica']['mirror'], self.replica_project['name'],fetch=fetch)

        # Set up branches hypermap
        # get branches from original
        # self.original_branches = self.underlayer.list_branches('original')
        self.original_branches = project_info['original']['watch-branches']
        self.backports_startref = dict()
        for original_branch in self.original_branches:
            if 'backports-start' in  self.original_project:
                self.backports_startref[original_branch] = self.original_project['backports-start'][original_branch]
            # apply mapping to find target branch
            try:
                replica_branch = project_info['replica']['branch-mappings'][original_branch]
            except KeyError:
                replica_branch = original_branch
            target_branch = '%s%s' % (replica_branch, self.target_branch_suffix)
            patches_branch = '%s%s' % (replica_branch, self.patches_branch_suffix)
            self.underlayer.set_branch_maps(original_branch, replica_branch, target_branch, patches_branch)

            self.recombinations[replica_branch] = None
            self.commits[replica_branch] = {}

        self.ref_locks = dict()
        if 'ref-locks' in self.replica_project:
            for branch in self.replica_project['ref-locks']:
                # no advancement will be performed past this revision on this branch
                self.ref_locks[branch] = self.replica_project['ref-locks'][branch]

    def get_slices(self, recombinations):
        slices = {
            "MERGED": [],
            "APPROVED": [],
            "PRESENT": [],
            "MISSING": [],
        }
        previous_status = None
        previous_impact = None
        current_slice = {}

        # Slice
        if recombinations:
            recomb_list = list(recombinations)
        else:
            recomb_list = []

        for index, recomb_id in enumerate(recomb_list):
            replica_change = recombinations[recomb_id]

            # creates slices to apply to change list
            # every status may have multiple slices, but this situation is tolerated
            # only between PRESENT' and 'APPROVED' statuses
            # any other complicated mix is a violation of upstream order
            status = replica_change.status
            impact =  self.status_impact[status]
            previous_change_id = None
            # Handle current status slice, archive previous slice
            try:
                segment = current_slice[status]
            except KeyError:
                if previous_status:
                    slices[previous_status].append(copy.deepcopy(current_slice[previous_status]))
                    del(current_slice[previous_status])
                current_slice[status] = {}
                segment = current_slice[status]
                segment['start'] = index
                segment['end'] = index + 1
            # init/extend current slice
            if previous_status:
                if impact > previous_impact:
                    log.critical("Constraint violation error: status %s at index %d (change:%s) of changes list in interval is more advanced than previous status %s at index %d (change: %s)" % (status, index, recomb_id, previous_status, index-1, previous_change_id))
                    log.critical("This means that midstream is broken")
                    raise ConstrainViolationError
                if status == previous_status:
                    segment['end'] = segment['end'] + 1
            # end of status list
            if index == len(list(recombinations)) - 1:
                    slices[status].append(copy.deepcopy(current_slice[status]))
                    del(current_slice[status])

            previous_status = status
            previous_impact = impact
            previous_change_id = recomb_id

        return slices

    def scan_original_distance(self, original_branch):
        replica_branch = self.underlayer.branch_maps['original->replica'][original_branch]
        target_branch = self.underlayer.branch_maps['original->target'][original_branch]
        log.debug("Scanning distance from original branch %s" % original_branch)
#        if self.replication_strategy == "change-by-change" and revision_exists(self.ref_locks[replica_branch], replica_branch):
#                log.info("Cannot replicate branch past the specified lock")

        self.recombinations[original_branch] = self.get_recombinations_by_interval(original_branch)
        slices = self.get_slices(self.recombinations[original_branch])
        recombinations = self.recombinations[original_branch]


        log.debugvar('slices')
        # Master sync on merged changes
        # we really need only the last commit in the slice
        # we advance the master to that, and all the others will be merged too
        if slices['MERGED']:
            # one or more changes are merged in midstream, but missing in master
            # master is out of sync, changes need to be pushed
            # but check first if the change was changed with a merge commit
            # if yes, push THAT to master, if not, it's just a fast forward
            segment = slices['MERGED'][0]
            recomb_id = list(recombinations)[segment['end'] - 1]
            recombination = recombinations[recomb_id]
            recombination.handle_status()

        # Gerrit operations from approved changes
        # NOthing 'approved' can be merged if it has some "present" before in the history
        skip_list = set()
        for index, approved_segment in enumerate(slices['APPROVED']):
            for present_segment in slices['PRESENT']:
                if present_segment['start'] < approved_segment['start']:
                    skip_list.add(index)

        for index in list(skip_list)[::-1]:
            segment = slices['APPROVED'].pop(index)
            for recomb_id in list(recombinations)[segment['start']:segment['end']]:
                log.warning("Recombination %s is approved but waiting for previous unapproved changes, skipping" % recomb_id)

        # Merge what remains
        for segment in slices['APPROVED']:
            for recomb_id in list(recombinations)[segment['start']:segment['end']]:
                recombination = recombinations[recomb_id]
                recombination.handle_status()

        # Notify of presence
        for segment in slices['PRESENT']:
            for recomb_id in list(recombinations)[segment['start']:segment['end']]:
                recombination = recombinations[recomb_id]
                log.warning("Recombination %s already present in replica gerrit as change %s and waiting for approval" % (recomb_id, recombination.number))
                recombination.handle_status()

        # Gerrit operations for missing changes
        for segment in slices['MISSING']:
            for recomb_id in list(recombinations)[segment['start']:segment['end']]:
                log.warning("Recombination %s is missing from replica gerrit" % recomb_id)
                recombination = recombinations[recomb_id]
                recombination.handle_status()

        return True

    def poll_original_branches(self):
        for branch in self.original_branches:
            self.scan_original_distance(branch)

    def get_recombinations_by_interval(self, original_branch):
        ref_end = 'original/%s' % (original_branch)
        replica_branch = self.underlayer.branch_maps['original->replica'][original_branch]
        patches_branch = self.underlayer.branch_maps['original->patches'][original_branch]

        if self.replication_strategy == "change-by-change":
            ref_start = 'replica/%s' % (replica_branch)
            self.commits[replica_branch] = self.underlayer.get_commits(ref_start, ref_end)
        elif self.replication_strategy == "lock-and-backports":
            if original_branch in self.backports_startref:
                ref_start = self.backports_startref[original_branch]
            else:
                ref_start = self.ref_locks[replica_branch]
            self.commits[replica_branch] = self.underlayer.get_commits(ref_start, ref_end, first_parent=False, no_merges=True)

        commits = self.commits[replica_branch]

        diversity_refname = "replica/%s" % (patches_branch)
        original_ids = self.underlayer.get_original_ids(commits)

        replica_lock = None
        if replica_branch in self.ref_locks:
            replica_lock = self.ref_locks[replica_branch]

        if original_ids:
            recombinations = self.underlayer.get_recombinations_from_original(original_branch, original_ids, diversity_refname, self.replication_strategy, replica_lock)
            return recombinations
        return None

    def scan_replica_patches(self, patches_branch=None):
        # Mutations are only handled one at a time per branch
        if patches_branch:
            patches_branches = [patches_branch]
        else:
            patches_branches = list()
            for original_branch in self.original_branches:
                patches_branches.append(self.underlayer.branch_maps['original->patches'][original_branch])

        for patches_branch in patches_branches:
            recombination, remaining_changes = self.underlayer.get_recombination_from_patches(patches_branch)
            # TODO: handle new patchset on same branch-patches review.
            recomb = recombination.__dict__
            log.debugvar('recomb')
            if recombination:
                recombination.handle_status()
                if remaining_changes:
                    log.warning("Remaining mutation changes %s will be handled in order one at a time after recombination %s is completed " % (' '.join(remaining_changes), recombination.uuid))
            else:
                logsummary.info("Project %s no new patches in patches branch %s" % (self.project_name, patches_branch))

    def check_approved_recombinations(self, recomb_id=None):
        if recomb_id:
            recomb_type, branch = self.underlayer.get_scaninfo_by_recomb_id(recomb_id)
            if recomb_type == 'replica-mutation':
                patches_branch = self.underlayer.branch_maps['replica->patches'][branch]
                self.scan_replica_patches(patches_branch=patches_branch)
            elif recomb_type == 'original-diversity' or recomb_type == "evolution-diversity":
                return self.scan_original_distance(branch=branch)
        else:
            for branch in self.original_branches:
                patches_branch = self.underlayer.branch_maps['original->patches'][branch]
                self.scan_replica_patches(patches_branch=patches_branch)
                self.scan_original_distance(branch)

    def get_reverse_dependencies(self, tags=[]):
        rev_deps = dict()
        for project in self.rev_deps:
            for tag in tags:
                if tag in self.rev_deps[project]["tags"]:
                    rev_deps[project] = self.rev_deps[project]["tests"]
                    break
        return rev_deps

    def fetch_untested_recombinations(self, test_basedir, recomb_id=None):
        changes_infos = dict()
        dirlist = self.underlayer.fetch_recombinations(test_basedir, "untested", recomb_id=recomb_id)

        if not dirlist:
            logsummary.info("Project '%s': no untested recombinations" % self.project_name)

        if not self.test_types:
            logsummary.info("Project '%s': no tests specified" % self.project_name)
        else:
            for change_number in dirlist:
                tests = dict()
                projects = self.get_reverse_dependencies(tags=['included','contained','required','classes', 'functions'])
                projects[self.project_name] = self.test_types
                log.debugvar('projects')
                for name in projects:
                    tests[name] = dict()
                    tests[name]["types"] = dict()
                    for test_type in projects[name]:
                        result_file = "%s/%s/results/%s/%s_results.xml" % (self.project_name, change_number, test_type, name)
                        tests[name]["types"][test_type] = result_file
                changes_infos[change_number] = {
                    "target_project" : self.project_name,
                    'recombination_dir': dirlist[change_number],
                    "recombination_id" : change_number,
                    "tests": tests ,
                }
                logsummary.info("Fetched recombination %s on dir %s" % (change_number, dirlist[change_number]))

        return changes_infos

    def get_test_score(self, test_results):
        for project_name in test_results:
            for test_type in test_results[project_name]:
                test_output = test_results[project_name][test_type]
                if test_output is None:
                    return (0, "missing test results")
        return (100, None)

    def vote_recombinations(self, test_results, recomb_id=None):
        if recomb_id:
            recombs = [recomb_id]
        else:
            recombs = [recomb for recomb in test_results]

        for recomb_id in recombs:
            recombination = self.underlayer.get_recombination(recomb_id)
            test_score, test_analysis = self.get_test_score(test_results[recomb_id])
            if test_score > self.test_minimum_score:
                if self.replication_strategy == "lock-and-backports":
                    comment_data = dict()
                    comment_data['backport-test-results'] = dict()
                    build_url = os.environ.get('BUILD_URL')
                    if build_url:
                        comment_data['backport-test-results']['message'] = "test-link: %s" % build_url
                    else:
                        comment_data['backport-test-results']['message'] = ""
                    comment_data['backport-test-results']['Code-Review'] = 0
                    comment_data['backport-test-results']['Verified'] = "1"
                    comment_data['backport-test-results']['reviewers'] = self.replica_project['success_reviewers_list']
                    comment = yaml.dump(comment_data)
                    recombination.comment(comment)
                recombination.approve()
                logsummary.info("Recombination %s Approved" % recomb_id)
            else:
                recomb.reject()
                logsummary.info("Recombination %s Rejected: %s" % (recomb_id, test_analysis))

    def delete_service_branches(self):
        # cleanup github repos from recomb branches WIP
        self.underlayer.delete_service_branches()

    def delete_stale_branches(self):
        recomb_active_branches = list()
        target_stale_branches = list()
        recomb_all_branches = self.underlayer.list_branches('replica', pattern='recomb*')
        infos = self.replica_remote.query_changes_json('"status:open AND project:%s"' % self.replica_project['name'])
        for info in infos:
            recomb_active_branches.append(info['branch'])

        log.debugvar('recomb_active_branches')
        recomb_stale_branches = list(set(recomb_all_branches) - set(recomb_active_branches))
        log.debugvar('recomb_stale_branches')
        self.underlayer.delete_remote_branches('replica', recomb_stale_branches)
        for recomb_branch in recomb_stale_branches:
            target_stale_branches.append(re.sub('recomb-','target-',recomb_branch))
        self.underlayer.delete_remote_branches('replica', target_stale_branches)

