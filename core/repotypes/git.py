import sys
import os
import tempfile
import yaml
from shellcommand import shell
from collections import OrderedDict
from ..datastructures import Change
from gerrit import Gerrit
from ..colorlog import log, logsummary

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
        # TODO: remove all local branches
        # git for-each-ref --format="%(refname)" refs/heads | sed -e "s/refs\/heads//"
        # for branch in local_branches:
        #    shell('git branch -D %s' % branch)
        cmd = shell('git checkout parking')
        if cmd.returncode != 0:
            shell('git checkout --orphan parking')
            shell('git commit --allow-empty -a -m "parking"')


    def addremote(self, name, url):
        os.chdir(self.directory)
        cmd = shell('git remote | grep ^%s$' % name)
        if cmd.returncode != 0:
            shell('git remote add %s %s' % (name, url))
        cmd = shell('git fetch %s' % (name))
        if cmd.returncode != 0:
            raise RemoteFetchError

    def add_gerrit_remote(self, name, location, project_name):
        self.remotes[name] = Gerrit(name, location, project_name)
        self.addremote(name, self.remotes[name].url)
        shell('git fetch %s +refs/changes/*:refs/remotes/%s/changes/*' % (name, name))
        shell('scp -p %s:hooks/commit-msg .git/hooks/' % location)

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
        #cmd = shell('git show -s --pretty=format:"%%P" %s' % merge_revision)
        #merge_revision_parents = cmd.output[0].split(' ')
        #if len(merge_revision_parents) > 1:
        #    merge_revision = merge_revision_parents[1]

        return pick_revision, starting_revision, merge_revision

    def recombine(self, recomb_data, recombination_branch):

        shell('git fetch replica')
        shell('git fetch original')

        pick_revision, starting_revision, merge_revision = self.extract_recomb_data(recomb_data)
        fd, commit_message_filename = tempfile.mkstemp(prefix="recomb-", suffix=".yaml", text=True)
        os.close(fd)
        main_source_name = recomb_data['sources']['main']['name']
        patches_source_name = recomb_data['sources']['patches']['name']
        branch = recomb_data['sources']['main']['branch']
        with open(commit_message_filename, 'w') as commit_message_file:
            # We have to be sure this is the first line in yaml document
            commit_message_file.write("Recombination: %s:%s-%s:%s/%s\n\n" % (main_source_name, pick_revision[:6], patches_source_name, merge_revision[:6], recomb_data['sources']['main']['branch']))
            yaml.safe_dump(recomb_data, commit_message_file, default_flow_style=False, indent=4, canonical=False, default_style=False)

        retry_merge = True
        first_try = True
        while retry_merge:

            shell('git checkout -B %s %s' % (recombination_branch, starting_revision))

            log.info("Creating remote disposable branch on replica")
            cmd = shell('git push replica HEAD:%s' % recombination_branch)
            if cmd.returncode != 0:
                raise PushError

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
                        logsummary.error("Recombination attempt failed")
                        raise ResolutionFailedError
                    else:
                        # reset, resolve, and retry
                        shell('git reset --hard %s' % recombination_branch)
                        shell('git checkout parking')
                        shell('git branch -D %s' % recombination_branch)
                        shell('git push replica :%s' % recombination_branch)
                else:
                    shell('git push replica :%s' % recombination_branch)
                    os.unlink(commit_message_filename)
                    log.critical("Merge failed even after resolution. You're on your own, sorry. Exiting")
                    raise MergeFailedError
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
                logsummary.warning('Contents in commit %s have been merged twice in upstream' % pick_revision)
                break

        os.unlink(commit_message_filename)

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

    def update_target_branch(self, replica_branch, patches_branch, target_branch):
        shell('git fetch replica')
        shell('git checkout -B new-%s remotes/replica/%s' % (target_branch, replica_branch))
        shell("git merge remotes/replica/%s" % (patches_branch))

        shell('git push -f replica HEAD:%s' % (target_branch))

        shell('git checkout parking')
        shell('git branch -D new-%s' % target_branch)

    def resolve_conflicts(self, output):
        return True

    def fetch_recomb(self, fetch_dir, untested_recombs, remote_name):
        dirlist = dict()
        os.chdir(self.directory)
        shell('git checkout parking')
        if not untested_recombs:
            return None
        else:
            for recomb in untested_recombs:
                recomb_dir = "%s/%s" % (fetch_dir, recomb['number'])
                try:
                    os.makedirs(recomb_dir)
                except OSError:
                    pass
                recomb_branch = 'remotes/%s/changes/%s/%s/%s' % (remote_name, recomb['number'][-2:], recomb['number'], recomb['currentPatchSet']['number'])
                shell('git checkout %s' % recomb_branch)
                shell('cp -a . %s' % recomb_dir)
                shell('git checkout parking')
                dirlist[recomb['number']] = recomb_dir
        return dirlist



class RemoteGit(Git):

    def __init__(self, name, location, directory, project_name):
        self.name = name
        self.url = "git@%s:%s" % (location, project_name)
        self.directory = directory
        self.project_name = project_name

    def get_original_ids(self, commits):
        ids = dict()
        for commit in commits:
            ids[commit['hash']] = commit['hash']
        return ids


