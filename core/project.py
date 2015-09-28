import pprint
import re
import copy
from colorlog import log, logsummary
from collections import OrderedDict
from datastructures import Change, Recombination
from repotypes.git import LocalRepo

class TestError(Exception):
    pass
class RecombinationApproveError(object):
    pass
class RecombinationSubmitError(object):
    pass
class RecombinationSyncReplicaError(object):
    pass


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
        self.test_types = project_info["replica"]["tests"]
        self.test_minimum_score = 0

        if 'revision_lock' in self.replica_project:
            for branch in self.replica_project['revision_lock']:
                # no advancement will be performed past this revision on this branch
                self.branch_limit[branch] = self.replica_project['revision_lock'][branch]

        # Set up local repo
        self.underlayer = LocalRepo(project_name, local_dir)

        # Set up remotes
        self.underlayer.add_gerrit_remote('replica', self.replica_project['location'], self.replica_project['name'], fetch=fetch)

        self.replica_remote = self.underlayer.remotes['replica']

        if self.original_project['type'] == 'gerrit':
            self.underlayer.add_gerrit_remote('original', self.original_project['location'], self.original_project['name'], fetch=fetch)

        elif self.original_project['type'] == 'git':
            self.underlayer.add_git_remote('original', self.original_project['location'], self.original_project['name'], fetch=fetch)

        self.original_remote = self.underlayer.remotes['original']
        self.recomb_remote = self.replica_remote
        self.patches_remote = self.replica_remote

        self.underlayer.add_git_remote('replica-mirror', 'github', self.replica_project['name'],fetch=fetch)


        # Set up branches hypermap
        # get branches from original
        #self.original_branches = self.underlayer.list_branches('original')
        self.original_branches = project_info['original']['watch-branches']
        self.replica_branches = dict()
        self.target_branches = dict()
        self.patches_branches = dict()
        for original_branch in self.original_branches:
            # apply mapping to find target branch
            try:
                replica_branch = project_info['replica']['branch-mappings'][original_branch]
            except KeyError:
                replica_branch = original_branch
            target_branch = '%s-tag' % replica_branch
            patches_branch = '%s-patches' % replica_branch

            self.replica_branches['original:' + original_branch] = replica_branch
            self.replica_branches['patches:' + patches_branch] = replica_branch
            self.replica_branches['target:' + target_branch] = replica_branch

            self.target_branches['original:' + original_branch] = target_branch
            self.target_branches['replica:' + replica_branch] = target_branch
            self.target_branches['patches:' + patches_branch] = target_branch

            self.patches_branches['original:' + original_branch] = patches_branch
            self.patches_branches['replica:' + replica_branch] = patches_branch
            self.patches_branches['target:' + target_branch] = patches_branch

            self.recombinations[replica_branch] = None
            self.commits[replica_branch] = {}

    def update_target_branch(self, recombination, replica_branch):
        target_branch = self.target_branches['replica:' + replica_branch]
        self.underlayer.update_target_branch(recombination.target_replacement_branch, target_branch)

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
        for index, recomb_id in enumerate(list(recombinations)):
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
        log.debug("Scanning distance from original branch %s" % original_branch)
        self.recombinations[original_branch] = self.get_recombinations_by_interval(original_branch)
        slices = self.get_slices(self.recombinations[original_branch])
        replica_branch = self.replica_branches['original:'+ original_branch]
        target_branch = self.target_branches['original:' + original_branch]
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
            log.warning("branch is out of sync with original")
            segment = slices['MERGED'][0]
            recomb_id = list(recombinations)[segment['end'] - 1]
            recombination = recombinations[recomb_id]
            recombination.sync_replica(replica_branch)
            self.update_target_branch(recombination, replica_branch)

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
                log.warning("Change %s is approved but waiting for previous unapproved changes, skipping" % recomb_id)

        # Merge what remains
        for segment in slices['APPROVED']:
            for recomb_id in list(recombinations)[segment['start']:segment['end']]:
                recombination = recombinations[recomb_id]
                try:
                    recombination.sync_replica(replica_branch)
                except RecombinationSyncReplicaError:
                    log.error("Replica could not be synced")
                self.update_target_branch(recombination, replica_branch)
                try:
                    recombination.submit()
                except RecombinationSubmitError:
                    log.error("Recombination not submitted")

        # Notify of presence
        for segment in slices['PRESENT']:
            for recomb_id in list(recombinations)[segment['start']:segment['end']]:
                recombination = recombinations[recomb_id]
                log.warning("Change %s already present in midstream gerrit as change %s and waiting for approval" % (recomb_id, recombination.number))

        # Gerrit operations for missing changes
        for segment in slices['MISSING']:
            for recomb_id in list(recombinations)[segment['start']:segment['end']]:
                log.warning("Change %s is missing from midstream gerrit" % recomb_id)
                recombination = recombinations[recomb_id]
                try:
                    recombination.test()
                except TestError:
                    log.error("Recombination attempt unsuccessful")
                    raise UploadError
                try:
                    recombination.upload()
                except UploadError:
                    log.error("upload of recombination with change %s did not succeed. Exiting" % self.uuid)
                    raise UploadError

        return True

    def poll_original_branches(self):
        for branch in self.original_branches:
            self.scan_original_distance(branch)

    def get_recombinations_by_interval(self, original_branch):
        revision_start = 'remotes/replica/%s' % (original_branch)
        replica_branch = self.replica_branches['original:' + original_branch]
        revision_end = 'remotes/original/%s' % (replica_branch)
        patches_branch = self.patches_branches['original:' + original_branch]
        diversity_refname = "remotes/replica/%s" % (patches_branch)
        self.commits[replica_branch] = self.underlayer.get_commits(revision_start, revision_end)
        commits = self.commits[replica_branch]
        ids = self.original_remote.get_original_ids(commits)

        recombinations = OrderedDict()
        if ids:
            # Just sets the right order
            for recomb_id in ids:
                recombinations[recomb_id] = None

            original_changes = self.original_remote.get_changes_by_id(list(ids), branch=original_branch)
            recomb_infos = self.recomb_remote.get_changes_info(list(ids), search_field='topic', key_field='topic')
            diversity_revision = self.underlayer.get_revision(diversity_refname)
            diversity_change = self.underlayer.get_changes_by_id([diversity_revision], branch=patches_branch)[diversity_revision]

            for recomb_id in ids:
                if recomb_id in recomb_infos:
                    # relative recombination exists, load informations
                    recombinations[recomb_id] = Recombination(self.underlayer, recomb_type='original-diversity', remote=self.recomb_remote, infos=recomb_infos[recomb_id], original_remote=self.original_remote)
                else:
                    # relative recombination missing, creating empty one
                    # Set real commit as revision
                    original_changes[recomb_id].revision = ids[recomb_id]
                    recombinations[recomb_id] = Recombination(self.underlayer, recomb_type='original-diversity', remote=self.recomb_remote)
                    recombinations[recomb_id].status = "MISSING"
                    recombinations[recomb_id].branch = "recomb-original-%s-%s" % (original_branch, original_changes[recomb_id].revision)
                    recombinations[recomb_id].target_replacement_branch = "target-original-%s-%s" % (original_branch, original_changes[recomb_id].revision)
                    recombinations[recomb_id].topic = recomb_id

                    recombinations[recomb_id].original_change = original_changes[recomb_id]

                    recombinations[recomb_id].diversity_change = diversity_change

            for recomb_id in ids:
                log.debugvar('recomb_id')
                recomb = recombinations[recomb_id].__dict__
                log.debugvar('recomb')

        return recombinations

    def get_recombination_by_patch_change(self, patches_change_id):
        infos = self.patches_remote.get_changes_info([patches_change_id], search_field='topic', key_field='topic')
        if patches_change_id in infos:
            recombination = Recombination(self.underlayer, recomb_type='replica-mutation', remote=self.recomb_remote, patches_remote=self.patches_remote, infos=infos[patches_change_id])
        else:
            recombination = Recombination(self.underlayer, recomb_type='replica-mutation', remote=self.recomb_remote)
            mutation_change = self.patches_remote.get_changes_by_id([patches_change_id])[patches_change_id]
            patches_branch = mutation_change.branch

            recombination.mutation_change = mutation_change
            recombination.mutation_change.remote = self.patches_remote

            change = Change(remote=self.replica_remote)
            change.branch = self.replica_branches['patches:' + patches_branch]
            change.revision = self.underlayer.get_revision("remotes/replica/%s" % change.branch)
            change.parent = self.underlayer.get_revision("remotes/replica/%s~1" % change.branch)
            change.uuid = change.revision

            recombination.replica_change = change

            recombination.branch = "recomb-patches-%s-%s" % (recombination.replica_change.branch, recombination.replica_change.revision)
            recombination.target_replacement_branch = "target-patches-%s-%s" % (recombination.replica_change.branch, recombination.replica_change.revision)
            recombination.topic = patches_change_id
            recombination.status = "MISSING"

        return recombination

    def scan_replica_patches(self):
        for original_branch in self.original_branches:
            patches_branch = self.patches_branches['original:' + original_branch]
            patches_changes = self.patches_remote.get_changes_by_id([patches_branch], search_field='branch', branch=patches_branch )
            for patches_change_id in patches_changes:
                recombination = self.get_recombination_by_patch_change(patches_change_id)
                if recombination.status == "MISSING":
                    recombination.test()
                    # log.error("Recombination attempt unsuccessful")
                    try:
                        recombination.upload()
                    except UploadError:
                        log.error("upload of recombination with change %s did not succeed. Exiting" % self.uuid)
                        raise UploadError
                elif recombination.status == "APPROVED":
                    log.warning("Master patches recombination approved as number %s and waiting for submission" % recombination.number)
                else:
                    log.warning("Master patches recombination present as number %s and waiting for approval" % recombination.number)

    def scan_patches_branch(self, replica_branch):
        branch_patches = 'recomb-patches-%s.*' % replica_branch
        infos = self.replica_remote.get_approved_change_infos(branch_patches)
        for change_number in infos:
            recombination = Recombination(self.underlayer, recomb_type='replica-mutation', remote=self.recomb_remote, patches_remote=self.patches_remote, infos=infos[change_number])
            self.merge_replica_mutation_recombination(recombination, replica_branch)

    def merge_replica_mutation_recombination(self, recombination, replica_branch):
        if recombination.mutation_change.status != "MERGED":
            try:
                recombination.mutation_change.approve()
                recombination.mutation_change.submit()
            except RecombinationApproveError:
                log.error("Originating change approval failed")
            except RecombinationSubmitError:
                log.error("Originating change submission failed")
        self.update_target_branch(recombination, replica_branch)
        if recombination.status != "MERGED":
            recombination.submit()
        else:
            log.warning("Recombination already submitted")
        # update existing recombination from upstream changes
        # for change in midstream_gerrit.gather_current_merges(patches_revision):
        #    local_repo.merge_fortests(change['upstream_revision'], patches_revision)
        #    upload new patchset with updated master-patches and updated message on midstream changes with old master_patches

    def check_approved_recombinations(self, recomb_id=None):
        if recomb_id:
            infos = self.recomb_remote.get_changes_info([recomb_id], key_field='number')[recomb_id]
            recomb = Recombination(self.underlayer, infos=infos, original_remote=self.original_remote, remote=self.recomb_remote, replica_remote=self.replica_remote, patches_remote=self.patches_remote)
            if recomb.recomb_type == 'replica-mutation':
                self.merge_replica_mutation_recombination(recomb)
            elif recomb.recomb_type == 'original-diversity':
                return self.scan_original_distance(branch=recomb.original.branch)
        else:
            for branch in self.original_branches:
                self.scan_patches_branch(branch)
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
        untested_recombs = self.recomb_remote.get_untested_recombs_infos(recomb_id=recomb_id)
        if not untested_recombs:
            dirlist =dict()
            logsummary.info("Project '%s': no untested recombinations" % self.project_name)
        else:
            dirlist = self.underlayer.fetch_recomb(test_basedir, untested_recombs, self.recomb_remote.name)
        for change_number in dirlist:
            tests = dict()
            projects = self.get_reverse_dependencies(tags=['included','contained','required','classes', 'functions'])
            projects[self.project_name] = self.test_types
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
                    # FIXME: until we have all the tests uploaded
                    # it's bettere to always approve a recombination
                    #return (0, "missing test results")
                    # Anyway,This shoudl really give a score to the testing infrastructure
                    # not the test themselves
                    return (100, None)
        return (100, None)

    def vote_recombinations(self, test_results, recomb_id=None):
        if recomb_id:
            recombs = [recomb_id]
        else:
            recombs = [recomb for recomb in test_results]

        for recomb_id in recombs:
            recomb = self.recomb_remote.get_changes_by_id([recomb_id], key_field='number')[recomb_id]
            test_score, test_analysis = self.get_test_score(test_results[recomb_id])
            if test_score > self.test_minimum_score:
                recomb.approve()
                logsummary.info("Recombination %s Approved" % recomb_id)
            else:
                recomb.reject()
                logsummary.info("Recombination %s Rejected: %s" % (recomb_id, test_analysis))

    def delete_service_branches(self):
        # cleanup github repos from recomb branches WIP
        log.info("Deleting recomb branches from mirror for project %s" % self.project_name)
        service_branches = self.underlayer.list_branches('replica-mirror', pattern='recomb*')
        self.underlayer.delete_remote_branches('replica-mirror', service_branches)
        service_branches = self.underlayer.list_branches('replica-mirror', pattern='target-*')
        self.underlayer.delete_remote_branches('replica-mirror', service_branches)

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

