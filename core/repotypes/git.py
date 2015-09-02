import re
import sys
import os
import tempfile
import yaml
from shellcommand import shell
from collections import OrderedDict
from ..datastructures import Change
from gerrit import Gerrit
from ..colorlog import log

class Git(object):

    def get_revision(self, revision_name):
        cmd = shell('git rev-parse %s' % revision_name)
        revision = cmd.output[0].rstrip('\n')
        return revision

    def get_commits(self, revision_start, revision_end, first_parent=True, reverse=True):
        options = ''
        commit_list = list()
        log.debug("Interval: %s..%s" % (revision_start, revision_end))

        os.chdir(self.directory)
        shell('git checkout parking')
        if reverse:
            options = '%s --reverse' % options
        if first_parent:
            options = '%s --first-parent' % options
        cmd = shell('git rev-list %s --pretty="%%H" %s..%s | grep -v ^commit' % (options, revision_start, revision_end))

        for commit_hash in cmd.output:
            commit = dict()
            commit['hash'] = commit_hash
            cmd = shell('git show -s --pretty="%%P" %s' % commit_hash)
            commit['parents'] = cmd.output[0].split(' ')
            cmd = shell('git show -s --pretty="%%B" %s' % commit_hash)
            commit['body'] = cmd.output
            if len(commit['parents']) > 1:
                commit['subcommits'] = self.get_commits(commit['parents'][0], commit['parents'][1], first_parent=False, reverse=False)

            commit_list.append(commit)

        return commit_list

    def get_changes_by_id(self, search_values, search_field='commit', key_field='revision', branch=None):
        changes = dict()
        os.chdir(self.directory)
        for revision in search_values:
            infos = {}
            cmd = shell('git show -s --pretty=format:"%%H %%P" %s' % (revision))
            infos['id'], infos['parent'] = cmd.output[0].split(' ')[0:2]
            infos['revision'] = infos['id']
            if not branch:
                log.error("for git repositories you must specify a branch")
                sys.exit(1)
            else:
                infos['branch'] = branch
            infos['project-name'] = self.project_name
            change = Change(infos=infos, remote=self)
            changes[infos[key_field]] = change
        return changes


class LocalRepo(Git):

    def __init__(self, project_name, directory):
        self.directory = directory
        self.project_name = project_name
        self.remotes = {}
        try:
            os.mkdir(self.directory)
        except OSError:
            pass
        os.chdir(self.directory)
        shell('git init')
        shell('git checkout --orphan parking')
        shell('git commit --allow-empty -a -m "parking"')
        shell('scp -p gerrithub:hooks/commit-msg .git/hooks/')

    def addremote(self, name, url):
        os.chdir(self.directory)
        shell('git remote add -f %s %s' % (name, url))

    def add_gerrit_remote(self, name, location, project_name):
        self.remotes[name] = Gerrit(name, location, project_name)
        self.addremote(name, self.remotes[name].url)

    def add_git_remote(self, name, location, project_name):
        self.remotes[name] = RemoteGit(name, location, self.directory, project_name)
        self.addremote(name, self.remotes[name].url)

    def list_branches(self, remote_name, pattern=''):
        cmd = shell('git for-each-ref --format="%%(refname)" refs/remotes/%s/%s | sed -e "s/refs\/remotes\/%s\///"' % (remote_name, pattern, remote_name))
        return cmd.output

    def track_branch(self, branch, remote_branch):
        shell('git checkout parking')
        shell('git branch --track %s %s' % (branch, remote_branch))

    def delete_branch(self, branch):
        shell('git checkout parking')
        cmd = shell('git branch -D %s' % branch)

    def delete_remote_branches(self, remote_name, branches):
        for branch in branches:
            shell('git push %s :%s' % (remote_name,branch))

    def extract_recomb_data(self, recomb_data):
        pick_revision = recomb_data['sources']['main']['revision']
        #pick_branch = main_source.branch
        cmd = shell('git rev-parse %s~1' % pick_revision)
        starting_revision = cmd.output[0]
        merge_revision = recomb_data['sources']['patches']['revision']

        # if the patches revision to be merged is a merge commit
        # select the second parent instead
        # or the merge will fail
        cmd = shell('git show -s --pretty=format:"%%P" %s' % merge_revision)
        merge_revision_parents = cmd.output[0].split(' ')
        if len(merge_revision_parents) > 1:
            merge_revision = merge_revision_parents[1]
        # self.track_branch(pick_branch, 'remotes/%s/%s' % (main_source_name, pick_branch))

        return pick_revision, starting_revision, merge_revision

    def recombine(self, recomb_data, recombination_branch):

        pick_revision, starting_revision, merge_revision = self.extract_recomb_data(recomb_data)
        fd, commit_message_filename = tempfile.mkstemp(prefix="recomb-", suffix=".yaml", text=True)
        os.close(fd)
        with open(commit_message_filename, 'w') as commit_message_file:
            # We have to be sure this is the first line in yaml document
            commit_message_file.write("recombination: %s-%s/%s\n\n" % (recomb_data['sources']['main']['name'], recomb_data['sources']['patches']['name'], recomb_data['sources']['main']['branch']))
            yaml.safe_dump(recomb_data, commit_message_file, default_flow_style=False, indent=4, canonical=False, default_style=False)

        shell('git fetch replica')
        shell('git fetch original')
        retry_merge = True
        first_try = True
        while retry_merge:
            # shell('git checkout %s' % pick_branch)

            shell('git checkout -B %s %s' % (recombination_branch, starting_revision))

            # TODO: handle exception: two identical changes in row creates no
            # diff, so no commit can be created
            log.info("Creating remote disposable branch on replica")
            shell('git push replica HEAD:%s' % recombination_branch)

            cmd = shell("git merge --squash --no-commit %s %s" % (pick_revision, merge_revision))

            shell('git status')

            if cmd.returncode != 0:
                log.warning("Merge check with master-patches failed")
                resolution = False
                if first_try:
                    log.warning("Trying automatic resolution")
                    resolution = self.resolve_conflicts(cmd.output)
                    first_try = False
                    if not resolution:
                        shell('git push replica :%s' % recombination_branch)
                        log.error("Resolution failed. Exiting")
                        os.unlink(commit_message_filename)
                        sys.exit(1)
                    else:
                        # reset, resolve, and retry
                        shell('git reset --hard %s' % recombination_branch)
                        shell('git checkout %s' % pick_branch)
                        shell('git branch -D %s' % recombination_branch)
                        shell('git push replica :%s' % recombination_branch)
                else:
                    shell('git push replica :%s' % recombination_branch)
                    os.unlink(commit_message_filename)
                    log.critical("Merge failed even after resolution. You're on your own, sorry. Exiting")
                    sys.exit(1)
            else:
                retry_merge = False

        cmd = shell("git commit -F %s" % (commit_message_filename))
        # If two changes with the exact content are merged upstream
        # the above command will succeed but nothing will be committed.
        # and recombination upload will fail due to no change.
        # this assures that we will always commit something to upload
        for line in cmd.output:
            if 'nothing to commit' in line:
                shell("git commit --allow-empty -F %s" % (commit_message_filename))
                break

        os.unlink(commit_message_filename)
        # shell('git checkout %s' % pick_branch)
        # self.delete_branch(pick_branch)

    def sync_replica(self, replica_branch, revision):
        os.chdir(self.directory)
        shell('git fetch replica')
        shell('git branch --track replica-%s remotes/replica/%s' % (replica_branch, replica_branch))
        shell('git checkout replica-%s' % replica_branch)
        cmd = shell('git merge --ff-only %s' % revision)
        if cmd.returncode != 0:
            log.debug(cmd.output)
            log.critical("Error merging. Exiting")
            raise MergeError
        cmd = shell('git push replica HEAD:%s' % replica_branch)
        if cmd.returncode != 0:
            log.debug(cmd.output)
            log.critical("Error pushing the merge. Exiting")
            raise PushError
        shell('git checkout parking')
        shell('git branch -D replica-%s' % replica_branch)

    def push_merge(self, recomb_data, target_branch):
        pick_revision, starting_revision, merge_revision = self.extract_recomb_data(recomb_data)
        shell('git fetch replica')
        #shell('git branch --track replica-%s remotes/replica/%s' % (target_branch, target_branch))
        #shell('git checkout replica-%s' % target_branch)
        shell('git checkout -B %s %s' % (target_branch, starting_revision))
        shell("git merge %s" % (merge_revision))

        shell('git push -f replica HEAD:%s' % (target_branch))

        shell('git checkout parking')
        shell('git branch -D %s' % target_branch)
        #shell('git branch -D replica-%s' % target_branch)

    def resolve_conflicts(self, output):
        return True


class RemoteGit(Git):

    def __init__(self, name, location, directory, project_name):
        self.name = name
        self.url = "git@%s:%s" % (location, project_name)
        self.directory = directory
        self.project_name = project_name

    def get_original_ids(self, commits):
        ids = list()
        for commit in commits:
            ids.append(commit['hash'])
        return ids


