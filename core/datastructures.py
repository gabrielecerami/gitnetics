import sys
import os
import yaml
import re
from colorlog import log
from utils import *


class DecodeError(Exception):
    pass

class UploadError(Exception):
    pass

class SubmitError(Exception):
    pass

class PushMergeError(Exception):
    pass

class AttemptError(Exception):
    pass

class RecombinationFailed(Exception):
    pass

class Change(object):

    def __init__(self, remote=None, infos=None):
        if infos:
            self.load_infos(infos)
        else:
            self.branch = None
            self.topic = None

        self.remote = None
        if remote:
            self.remote = remote

    def load_infos(self, infos):
        self.revision = infos['revision']
        self.branch = infos['branch']
        if 'id' in infos:
            self.uuid = infos['id']
        elif 'uuid' in infos:
            self.uuid = infos['uuid']
        self.parent = infos['parent']
        self.previous_commit = infos['parent']
        if 'number' in infos:
            self.number = infos['number']
        if 'status' in infos:
            self.status = infos['status']
        self.project_name = infos['project-name']
        if 'topic' in infos:
            self.topic = infos['topic']
        if 'patchset_number' in infos:
            self.patchset_number = infos['patchset_number']
        if 'patchset_revision' in infos:
            self.patchset_revision = infos['patchset_revision']
        if 'url' in infos:
            self.url = infos['url']
        if 'commit-message' in infos:
            self.commit_message = infos['commit-message']

    def submit(self):
        return self.remote.submit_change(self.number, self.patchset_number)

    def approve(self):
        return self.remote.approve_change(self.number, self.patchset_number)

    def reject(self):
        return self.remote.reject_change(self.number, self.patchset_number)

    def upload(self):
        result_change = self.remote.upload_change(self.branch, self.topic)
        if result_change:
            self.number = result_change.number
            self.uuid = result_change.uuid
            self.status = result_change.status
            self.patchset_number = result_change.patchset_number
            log.info("Recombination with Change-Id %s uploaded in replica gerrit with number %s" % (self.uuid, self.number))
        else:
            return False
        return True

    def abandon(self):
        if self.status == "DRAFT":
            self.publish(self.number, self.patchset_number)
        self.remote.abandon(self.number, self.patchset_number)

    def comment(self, comment_message, verified=None, code_review=None):
        self.remote.comment_change(self.number, self.patchset_number, comment_message, verified=verified, code_review=code_review)

class Recombination(Change):

    def __init__(self, underlayer, replication_strategy='change-by-change', recomb_type=None, remote=None, replica_remote=None, original_remote=None, patches_remote=None, infos=None):
        self.underlayer = underlayer
        self.removed_commits = None
        self.backportid = None
        if original_remote:
            self.original_remote = original_remote
        if replica_remote:
            self.replica_remote = replica_remote
        if patches_remote:
            self.patches_remote = patches_remote
        if infos:
            if 'metadata' not in infos or infos['metadata'] is None:
                raise DecodeError
            else:
                self.metadata = infos['metadata']
            super(Recombination, self).__init__(remote=remote, infos=infos)
            self.load_metadata(original_remote=original_remote, replica_remote=replica_remote, patches_remote=patches_remote)
        else:
            super(Recombination, self).__init__(remote=remote)
            self.recomb_type = recomb_type
            self.commit_message = None
            self.patches_queue = None
            self.own_merge_commit = None
            self.replica_revision = None
            if self.recomb_type == 'replica-mutation':
                try:
                    self.replica_change = Change(remote=replica_remote)
                    self.mutation_change = Change(remote=patches_remote)
                except NameError:
                    raise MissingInfoError
            elif self.recomb_type == 'original-diversity':
                try:
                    self.original_change = Change(remote=original_remote)
                    self.diversity_change = Change(remote=patches_remote)
                except NameError:
                    raise MissingInfoError
            elif self.recomb_type == 'evolution-diversity':
                try:
                    self.evolution_change = Change(remote=original_remote)
                    self.diversity_change = Change(remote=patches_remote)
                except NameError:
                    raise MissingInfoError
            self.replication_strategy = replication_strategy
            self.recombine_status = "UNATTEMPTED"
        ch['comments'][-4]['message'].split('\n'):


    def load_metadata(self, original_remote=None, replica_remote=None, patches_remote=None):
        log.debug(self.commit_message)
        recomb_sources = self.metadata['sources']
        header = self.metadata['Recombination']

        recomb_header = header.split('/')[0]
        self.recomb_type = re.sub(':[a-zA-Z0-9]{6}', '',recomb_header)
        self.replication_strategy = self.metadata['replication-strategy']
        if self.recomb_type == 'replica-mutation':
            self.replica_change = self.underlayer.get_changes_by_id([recomb_sources['main']['id']], branch=recomb_sources['main']['branch'])[recomb_sources['main']['id']]
            self.mutation_change = self.patches_remote.get_changes_by_id([recomb_sources['patches']['id']])[recomb_sources['patches']['id']]
        elif self.recomb_type == 'original-diversity':
            self.original_change = self.original_remote.get_changes_by_id([recomb_sources['main']['id']], branch=recomb_sources['main']['branch'])[recomb_sources['main']['id']]
            # Set real commit as revision
            self.original_change.revision = recomb_sources['main']['revision']
            self.diversity_change = self.underlayer.get_changes_by_id([recomb_sources['patches']['id']], branch=recomb_sources['patches']['branch'])[recomb_sources['patches']['id']]
        elif self.recomb_type == 'evolution-diversity':
            self.evolution_change = self.original_remote.get_changes_by_id([recomb_sources['main']['id']], branch=recomb_sources['main']['branch'])[recomb_sources['main']['id']]
            # Set real commit as revision
            self.evolution_change.revision = recomb_sources['main']['revision']
            self.diversity_change = self.underlayer.get_changes_by_id([recomb_sources['patches']['id']], branch=recomb_sources['patches']['branch'])[recomb_sources['patches']['id']]

        if self.replication_strategy == 'change-by-change':
            if 'target-replacement-branch' not in self.metadata:
                self.metadata['target-replacement-branch'] = re.sub('recomb', 'target', self.branch)
            self.target_replacement_branch = self.metadata['target-replacement-branch']
        elif self.replication_strategy == 'lock-and-backports':
            self.patches_commit_message = self.metadata['sources']['patches']['commit-message']

        if 'recombine-status' in self.metadata:
            self.recombine_status = self.metadata['recombine-status']
            if self.metadata['recombine-status'] == "DISCARDED":
                if self.status == "ABANDONED":
                    pass

        if 'backportid' in self.metadata:
            self.backportid = self.metadata['backportid']


        self.set_recomb_data()

    def set_recomb_data(self):
        if self.recomb_type == 'original-diversity':
            main_source = self.original_change
            patches_source = self.diversity_change
            main_source_name = 'original'
            patches_source_name = 'diversity'
        elif self.recomb_type == 'replica-mutation':
            main_source = self.replica_change
            patches_source = self.mutation_change
            main_source_name = 'replica'
            patches_source_name = 'mutation'
        if self.recomb_type == 'evolution-diversity':
            main_source = self.evolution_change
            patches_source = self.diversity_change
            main_source_name = 'evolution'
            patches_source_name = 'diversity'
        else:
            log.critical("Unknown Recombination type")
            raise RecombinationTypeError

        self.recomb_data = {
            "sources": {
                "main": {
                    "name": str(main_source_name),
                    "branch": str(main_source.branch),
                    "revision": main_source.revision,
                    "id": str(main_source.uuid)
                },
                "patches" : {
                    "name": patches_source_name,
                    "branch": patches_source.branch,
                    "revision": patches_source.revision,
                    "id": patches_source.uuid
                },
            },
            "recombine-status": self.recombine_status,
        }
        if self.replication_strategy == "change-by-change":
            self.recomb_data['target-replacement-branch'] = self.target_replacement_branch
        self.recomb_data['replication-strategy'] = self.replication_strategy
        if 'commit-message' in self.metadata['sources']['patches']:
            self.recomb_data['sources']['patches']['commit-message'] = self.metadata['sources']['patches']['commit-message']

    def mangle_commit_message(self, commit_message):
        upstream_string = "\nUpstream-%s: %s\n" % (self.evolution_change.branch, self.evolution_change.url)
        commit_message = re.sub('(Change-Id: .*)', '%s\g<1>' % (upstream_string), commit_message)
        commit_message = commit_message + "\n(cherry picked from commit %s)" % (self.evolution_change.revision)
        return commit_message

    def attempt(self):
        # patches_revision = self.project.get_revision(self.patches.revision)
        self.set_recomb_data()
        if self.recomb_type == 'original-diversity':
            try:
                self.underlayer.merge_recombine(self.recomb_data, self.branch)
                log.debug("Merge check with master-patches successful, ready to create review")
            except AttemptError:
                raise AttemptError
        if self.recomb_type == 'evolution-diversity':
            self.recomb_data['sources']['patches']['commit-message'] = literal_unicode(self.mangle_commit_message(self.evolution_change.commit_message))
            try:
                self.underlayer.cherrypick_recombine(self.recomb_data, self.branch)
                log.debug("Merge check with master-patches successful, ready to create review")
            except RecombinationFailed as e:
                raise

    def sync_replica(self, replica_branch):
        if self.recomb_type == 'original-diversity':
            log.info("Advancing replica branch %s to %s " % (replica_branch, self.original_change.revision))
            self.underlayer.sync_replica(replica_branch, self.original_change.revision)
        else:
            raise RecombinationTypeError

    def amend(self):
        self.underlayer.amend(message=recomb_data)
        self.upload_change(self.number, self.patchset_number)

    def analyze_comments(self, info):
        comment_data = dict()
        if self.comments:
            for comment in self.comments:
                try:
                    data = yaml.load(self.comment())
                    comment_data['values'] = data
                except ScannerError, ParserError, ValueError:
                    for line in comment.split('\n')
                        for cc in comment_commands:
                            rs = re.search('^%s$' % cc, line)
                            if rs is not None:
                                comment_data['action'] == cc
        return comment_data

    def safe_abandon(self, reason):
        if not reason:
            log.error("you cannot abandon without recombine status")
        self.recomb_data['recombine_status'] = reason
        self.amend(recomb_data)
        super(Recombination, self).abandon()

    def handle_status(self):
        if self.status == "MISSING":
            if self.recomb_type == 'original-diversity':
                try:
                    self.attempt()
                except AttemptError:
                    log.error("Recombination attempt unsuccessful")
                    raise UploadError
                try:
                    self.upload()
                except UploadError:
                    log.error("upload of recombination with change %s did not succeed. Exiting" % self.uuid)
                    raise UploadError

            if self.recomb_type == 'evolution-diversity':
                try:
                    self.attempt()
                except RecombinationFailed as e:
                    self.upload()
                    status = e.args[0]
                    suggested_solution = e.args[1]
                    if not suggested_solution:
                        suggested_solution=" No clue why this may have happened."
                    message = '''Cherry pick failed with status:
    %s

%s

Manual conflict resolution is needed. Follow this steps to unblock this recombination:
    git review -d %s
    git cherry-pick -x %s

solve the conflicts, then

    git commit -a --amend

edit sources.main.body *ONLY*, then

git review -D

If you decide to discard this pick instead, please comment to this change with a single line: DISCARD''' % (status, suggested_solution, self.number, self.recomb_data['sources']['main']['revision'] )
                    self.comment(message, verified="-1")
                else:
                    self.upload()

        if self.status == "APPROVED":
            if self.recomb_type == 'original-diversity':
                try:
                    self.sync_replica(replica_branch)
                except RecombinationSyncReplicaError:
                    log.error("Replica could not be synced")
                self.underlayer.update_target_branch(self.target_replacement_branch, self.target_branch)
                try:
                    self.submit()
                except RecombinationSubmitError:
                    log.error("Recombination not submitted")
            elif self.recomb_type == 'evolution-diversity':
                if self.backportid:
                    backport = self.patches.get_changes_by_id(backportid)
                    if backport.status == "MERGED":
                        try:
                            self.submit()
                        except RecombinationSubmitError:
                            log.error("Recombination not submitted")
                    if backport.status == "ABANDONED":
                        try:
                            self.abandon()
                        except RecombinationAbandonedError:
                            log.error("Recombination not abandoned")
                else:
                    # A possible approach is to search original author/timestamp
                    # backportid = self.patches.search_backport()
                    backportid = None
                    if not backportid:
                        try:
                            self.underlayer.format_patch(self)
                            backport = self.patches_remote.upload_change(self.recomb_data['sources']['patches']['branch'],'automated_proposal', reviewers=["whayutin@redhat.com"], successremove=False)
                        except UploadError:
                            log.error("Mannaggai")
                        self.recomb_data['patches-review']  = backport.uuid
                        self.amend()
            elif self.recomb_type == 'replica-mutation':
                if self.mutation_change.status != "MERGED":
                    try:
                        self.mutation_change.approve()
                        self.mutation_change.submit()
                    except RecombinationApproveError:
                        log.error("Originating change approval failed")
                    except RecombinationSubmitError:
                        log.error("Originating change submission failed")
                self.underlayer.update_target_branch(self.target_replacement_branch, self.target_branch)
                if self.status != "MERGED":
                    self.submit()
                else:
                    log.warning("Recombination already submitted")
                # update existing recombination from upstream changes
                # for change in midstream_gerrit.gather_current_merges(patches_revision):
                #    local_repo.merge_fortests(change['upstream_revision'], patches_revision)
                #    upload new patchset with updated master-patches and updated message on midstream changes with old master_patches
        if self.status == "MERGED":
            if self.replication_strategy == "change-by-change":
                log.warning("branch is out of sync with original")
                self.sync_replica(replica_branch)
                self.underlayer.update_target_branch(self.target_replacement_branch, self.target_branch)
            elif self.replication_strategy == "lock-and-backports":
                pass
        elif self.status == "PRESENT":
            if self.replication_strategy == "lock-and-backports":
                if self.recombine_status == "BLOCKED":
                    comment_data = handle_comments()
                    if comment_data['action'] == "DISCARD":
                        self.safe_abandon(reason="DISCARDED by user")
                    self.check_metadata()
                elif self.recombine_status == "":
                    pass

