import sys
import os
import yaml
import tempfile
from colorlog import log

class Change(object):

    def __init__(self, repo=None, infos=None):
        if infos:
            self.revision = infos['revision']
            self.branch = infos['branch']
            if 'id' in infos:
                self.uuid = infos['id']
            elif 'uuid' in infos:
                self.uuid = infos['uuid']
            self.parent = infos['parent']
            self.previous_commit = infos['parent']
            if 'status' in infos:
                self.status = infos['status']
            if 'subject' in infos:
                self.subject = infos['subject']
            self.project_name = infos['project-name']
            if 'topic' in infos:
                self.topic = infos['topic']
            if 'number' in infos:
                self.number = infos['number']
            if 'patchet_number' in infos:
                self.patchset_number = infos['patchet_number']
            if 'patchset_revision' in infos:
                self.patchset_revision = infos['patchset_revision']
        else:
            self.branch = None
            self.topic = None
        self.merge_commit = None

        self.repo = None
        if repo:
            self.repo = repo

    def find_merge(self, merge_commits):
        # TODO: implement better git-find-merge to find to which merge a commit belongs
        # in gerrit is simple, merged branches are always formed by 1 commit
        # in git things may be more difficult
        # in git we must wait for ALL the commits in a merged branch before
        # committing the merge commit
        for merge_commit in merge_commits:
            if self.revision in merge_commit['parents'][1]:
                log.info("%s is part of merge commit %s" % (self.revision, merge_commit['commit']))
                self.previous_commit = merge_commit['parents'][0]
                self.merge_commit = merge_commit['commit']
                break

    def submit(self):
        return self.repo.submit_change(self.number, self.patchset_number)

    def approve(self):
        return self.repo.approve_change(self.number, self.patchset_number)

    def upload(self):
        result_change = self.repo.upload_change(self.branch, self.topic)
        if result_change:
            self.number = result_change.number
            self.uuid = result_change.uuid
            log.info("Recombination with Change-Id %s uploaded in replica gerrit with number %s" % (self.uuid, self.number))
        else:
            shell('git push replica :%s' % self.branch)
            return False

        return True



class Recombination(Change):

    def __init__(self, project, infos=None):
        self.project = project
        if infos:
            super(Recombination, self).__init__(repo=self.project.replica, infos=infos)
            self.decode_subject()
        else:
            super(Recombination, self).__init__(repo=self.project.replica)
            self.subject = None
            self.patches_queue = None
            self.own_merge_commit = None
            self.replica_revision = None
            self.original = Change(repo=self.project.original)
            self.patches = Change(repo=self.project.replica)
            self.replica = Change(repo=self.project.replica)

    def decode_subject(self):
        log.debug(self.subject)
        try:
            data = yaml.load(self.subject)
        except ValueError:
            log.error("Subject not in yaml")
            exit(1)
        recomb_data = data['recombination']
        if 'mutation' in recomb_data:
            self.patches = self.project.replica.get_changes_by_id([recomb_data['mutation']['id']])[recomb_data['mutation']['id']]
            self.replica = self.project.underlayer.get_changes_by_id([recomb_data['replica']['id']], branch=recomb_data['replica']['branch'])[recomb_data['replica']['id']]
            main_source = self.replica
            merge_commits = self.project.underlayer.get_merge_commits(self.replica.parent, self.replica.revision)
            self.replica.find_merge(merge_commits)
        elif 'diversity' in recomb_data:
            self.patches = self.project.underlayer.get_changes_by_id([recomb_data['diversity']['id']], branch=recomb_data['diversity']['branch'])[recomb_data['diversity']['id']]
            self.original = self.project.original.get_changes_by_id([recomb_data['original']['id']], branch=recomb_data['original']['branch'])[recomb_data['original']['id']]
            main_source = self.original
            merge_commits = self.project.underlayer.get_merge_commits(self.original.parent, self.original.revision)
            self.original.find_merge(merge_commits)

        merge_revision = self.patches.revision
        if main_source.merge_commit:
            starting_revision = main_source.merge_commit
        else:
            starting_revision = main_source.revision
        self.recombination_attempt = (data['target-branch'], starting_revision, merge_revision)

    def attempt(self, main_source_name, patches_source_name):
        # patches_revision = self.project.get_revision(self.patches.revision)
        if main_source_name == 'original' and patches_source_name == 'diversity':
            main_source = self.original
            patches_source = self.patches
        elif main_source_name == 'replica' and patches_source_name == 'mutation':
            main_source = self.replica
            patches_source = self.patches
        else:
            log.critical("I don't know how to attempt this recombination")
            sys.exit(1)
        pick_revision = main_source.revision
        pick_branch = main_source.branch
        starting_revision = main_source.previous_commit
        merge_revision = patches_source.revision
        merge_branch = patches_source.branch
        recombination_branch = self.branch
        log.info("Checking compatibility between %s and %s-patches" % (self.original.branch, self.original.branch))
        subject = {
            "target-branch": self.original.branch,
            "recombination": {
                main_source_name : {
                    "branch": pick_branch,
                    "revision": pick_revision,
                    "id": main_source.uuid
                },
                patches_source_name: {
                    "branch": merge_branch,
                    "revision": merge_revision,
                    "id": patches_source.uuid
                }
            }
        }
        fd, commit_message_filename = tempfile.mkstemp(prefix="recomb-", suffix=".yaml", text=True)
        os.close(fd)
        with open(commit_message_filename, 'w') as commit_message_file:
            # We have to be sure this is the first line in yaml document
            commit_message_file.write("Recombination: %s-%s/%s\n" % (main_source_name, patches_source_name, pick_branch))
            yaml.safe_dump(subject, commit_message_file, default_flow_style=False, indent=4, canonical=False, default_style=False)
        self.project.underlayer.track_branch(pick_branch, 'remotes/%s/%s' % (main_source_name, pick_branch))
        self.project.underlayer.recombine(commit_message_filename, pick_branch, recombination_branch, starting_revision, pick_revision, merge_revision)
        self.recombination_attempt = (self.original.branch, pick_revision, merge_revision)
        self.project.underlayer.delete_branch(pick_branch)
        return True

    def test(self, main_source, patches_source):
        if not self.attempt(main_source, patches_source):
            return False
        log.debug("Merge check with master-patches successful, ready to create review")
        if not self.upload():
            log.error("upload of recombination with change %s did not succeed. Exiting" % recomb_id)
            return False
        return True

    def submit(self):
        recomb = self.__dict__
        log.debugvar('recomb')
        log.info("Approved replica recombination %s is about to be submitted for merge" % self.number)
        if super(Recombination, self).submit():
            log.success("Submission of recombination %s succeeded" % self.number)
        else:
            log.error("Submission of recombination %s failed" % self.number)
            return False
        self.generate_tag_branch()
        return True

    def generate_tag_branch(self):
        self.project.underlayer.push_merge(self.recombination_attempt)

    def sync_replica(self):
        if self.original.merge_commit:
            commit = self.original.merge_commit
        else:
            commit = self.original.revision
        log.info("Advancing replica branch %s to %s " % (self.original.branch, commit))
        if not self.project.underlayer.sync_replica(self.original.branch, commit):
            return False
        return True

