#!/usr/bin/python3
# -*- coding: utf-8 -*-
#
# GitHub Pull Requests for Elastic Search
#
# Copyright (C) 2015 Bitergia
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
#
# Authors:
#   Alvaro del Castillo San Felix <acs@bitergia.com>
#

'''Gerrit backend for Gerrit'''


from datetime import datetime
import json
import logging
import os
import re
import subprocess
import traceback
from perceval.utils import get_eta, remove_last_char_from_file

from perceval.backends.backend import Backend


class Gerrit(Backend):

    _name = "gerrit"

    def __init__(self, user, repository, nreviews,
                 use_cache = False, history = False):

        self.gerrit_user = user
        self.project = repository
        self.nreviews = nreviews
        self.reviews = []  # All reviews from gerrit
        self.projects = []  # All projects from gerrit
        self.cache = {}  # cache projects listing
        self.use_cache = use_cache
        self.use_history = history
        self.url = repository

        self.gerrit_cmd  = "ssh -p 29418 %s@%s" % (user, repository)
        self.gerrit_cmd += " gerrit "

        # self.max_reviews = 50000  # around 2 GB of RAM
        self.max_reviews = 1000 * 50


        # Create storage dir if it not exists
        dump_dir = self._get_storage_dir()
        if not os.path.isdir(dump_dir):
            os.makedirs(dump_dir)

        if self.use_cache:
            # Don't use history data. Will be generated from cache.
            self.use_history = False

        if self.use_history:
            self._restore()  # Load history

        else:
            if self.use_cache:
                logging.info("Getting all data from cache")
                try:
                    self._load_cache()
                except:
                    # If any error loading the cache, clean it
                    traceback.print_exc(file=os.sys.stdout)
                    logging.debug("Cache corrupted")
                    self.use_cache = False
                    self._clean_cache()
            else:
                self._clean_cache()  # Cache will be refreshed


    def _get_name(self):

        return Gerrit._name

    def get_id(self):
        ''' Return gerrit unique identifier '''

        return self._get_name() + "_" + self.url

    def get_url(self):

        return self.url

    def _restore(self):
        '''Restore JSON full data from storage '''

        restore_dir = self._get_storage_dir()

        if os.path.isdir(restore_dir):
            try:
                logging.debug("Restoring data from %s" % restore_dir)
                restore_file = os.path.join(restore_dir, "reviews.json")
                if os.path.isfile(restore_file):
                    with open(restore_file) as f:
                        data = f.read()
                        self.issues = json.loads(data)
                logging.debug("Restore completed")
            except ValueError:
                logging.warning("Restore failed. Wrong dump files in: %s" %
                                restore_file)


    def _dump(self):
        ''' Dump JSON full data to storage '''

        dump_dir = self._get_storage_dir()

        logging.debug("Dumping data to  %s" % dump_dir)
        dump_file = os.path.join(dump_dir, "reviews.json")
        with open(dump_file, "w") as f:
            f.write(json.dumps(self.issues))

        logging.debug("Dump completed")


    def _load_cache(self):
        ''' Load all cache files in memory '''

        fname = os.path.join(self._get_storage_dir(),
                             "cache_projects.json")
        with open(fname,"r") as f:
            self.cache['projects'] = json.loads(f.read())


        return  # Having all cache in memory does not scale

        self.cache['reviews'] = {}

        for project in self.cache['projects']:
            pname = project.replace("/","_")
            fname = os.path.join(self._get_storage_dir(),
                                 'cache_'+ pname +"-reviews.json")
            if not os.path.exists(fname):
                logging.debug("Cache incomplete. Not found: %s" % (fname))
                continue

            with open(fname,"r") as f:
                self.cache['reviews'][pname] = json.loads(f.read())

    def _load_cache_project(self, project):

        reviews = None

        pname = project.replace("/","_")
        fname = os.path.join(self._get_storage_dir(),
                             'cache_'+ pname +"-reviews.json")

        if not os.path.exists(fname):
            logging.debug("Cache incomplete. Not found: %s" % (fname))
        else:
            with open(fname,"r") as f:
                logging.debug("Loaded from cache: %s" % (project))
                reviews = json.loads(f.read())

        return reviews


    def _clean_cache(self):
        cache_files = ["cache_projects.json"]

        for name in cache_files:
            fname = os.path.join(self._get_storage_dir(), name)
            with open(fname,"w") as f:
                if name == "cache_projects.json":  # Just one array
                    f.write("")
                else:
                    f.write("[")

        cache_keys = ['projects']

        for _id in cache_keys:
            self.cache[_id] = []

    def _close_cache(self):
        cache_file = os.path.join(self._get_storage_dir(),
                                  "cache_reviews.json")

        remove_last_char_from_file(cache_file)
        with open(cache_file,"a") as f:
                f.write("]")

    def _projects_to_cache(self, projects):
        ''' Append to projects JSON cache '''

        cache_file = os.path.join(self._get_storage_dir(),
                                  "cache_projects.json")

        with open(cache_file, "w") as cache:  # Complete list always
            data_json = json.dumps(projects)
            cache.write(data_json)


    def _project_reviews_to_cache(self, project, reviews):
        ''' Append to reviews JSON cache '''

        project = project.replace("/","_")

        cache_file = os.path.join(self._get_storage_dir(),
                                  "cache_%s-reviews.json" % (project))

        with open(cache_file, "w") as cache:
            data_json = json.dumps(reviews)
            cache.write(data_json)

    def _get_version(self):
        gerrit_cmd_prj = self.gerrit_cmd + " version "

        raw_data = subprocess.check_output(gerrit_cmd_prj, shell = True)
        raw_data = str(raw_data, "UTF-8")

        # output: gerrit version 2.10-rc1-988-g333a9dd
        m = re.match("gerrit version (\d+)\.(\d+).*", raw_data)

        if not m:
            raise Exception("Invalid gerrit version %s" % raw_data)

        try:
            mayor = int(m.group(1))
            minor = int(m.group(2))
        except:
            raise Exception("Invalid gerrit version %s " %
                            (raw_data))

        return [mayor, minor]


    def _get_projects(self):
        """ Get all projects in gerrit """

        logging.debug("Getting list of gerrit projects")

        if self.use_cache:
            projects = self.cache['projects']
        else:
            gerrit_cmd_projects = self.gerrit_cmd + "ls-projects "
            projects_raw = subprocess.check_output(gerrit_cmd_projects, shell = True)


            projects_raw = str(projects_raw, 'UTF-8')
            projects = projects_raw.split("\n")
            projects.pop() # Remove last empty line

            self._projects_to_cache(projects)

        logging.debug("Done")


        return projects


    def _get_project_reviews(self, project):
        """ Get all reviews for a project """

        if self.use_cache:
            # reviews = self.cache['reviews'][pname]
            reviews = self._load_cache_project(project)

            if reviews:
                return reviews

        gerrit_version = self._get_version()
        last_item = None
        if gerrit_version[0] == 2 and gerrit_version[1] >= 9:
            last_item = 0

        gerrit_cmd_prj = self.gerrit_cmd + " query project:"+project+" "
        gerrit_cmd_prj += "limit:" + str(self.nreviews)
        gerrit_cmd_prj += " --all-approvals --comments --format=JSON"

        number_results = self.nreviews

        reviews = []

        while (number_results == self.nreviews or
               number_results == self.nreviews + 1):  # wikimedia gerrit returns limit+1

            cmd = gerrit_cmd_prj
            if last_item is not None:
                if gerrit_version[0] == 2 and gerrit_version[1] >= 9:
                    cmd += " --start=" + str(last_item)
                else:
                    cmd += " resume_sortkey:" + last_item

            raw_data = subprocess.check_output(cmd, shell = True)
            raw_data = str(raw_data, "UTF-8")
            tickets_raw = "[" + raw_data.replace("\n", ",") + "]"
            tickets_raw = tickets_raw.replace(",]", "]")

            tickets = json.loads(tickets_raw)

            for entry in tickets:
                if 'project' in entry.keys():
                    reviews.append(entry)
                    if gerrit_version[0] == 2 and gerrit_version[1] >= 9:
                        last_item += 1
                    else:
                        last_item = entry['sortKey']
                elif 'rowCount' in entry.keys():
                    # logging.info("CONTINUE FROM: " + str(last_item))
                    number_results = entry['rowCount']


            self._project_reviews_to_cache(project, reviews)

        logging.info("Total reviews: %i" % len(reviews))

        return reviews

    def _memory_usage(self):
        # return the memory usage in MB
        import psutil
        process = psutil.Process(os.getpid())
        mem = process.get_memory_info()[0] / float(2 ** 20)
        return mem


    def get_reviews(self):
        # First we need all projects
        projects = self._get_projects()

        total = len(projects)
        current_repo = 1


        for project in projects:
            # if repository != "openstack/cinder": continue
            task_init = datetime.now()

            self.reviews += self._get_project_reviews(project)

            task_time = (datetime.now() - task_init).total_seconds()
            eta_time = task_time * (total-current_repo)
            eta_min = eta_time / 60.0

            logging.info("Completed %s %i/%i (ETA: %.2f min)" \
                             % (project, current_repo, total, eta_min))




            if len(self.reviews) >= self.max_reviews:
                # 5 GB RAM memory usage
                logging.error("Max reviews reached: %i " % (self.max_reviews))
                break

            logging.debug ("Total reviews in memory: %i" % (len(self.reviews)))
            logging.debug ("Total memory: %i MB" % (self._memory_usage()))

            current_repo += 1

        return self.reviews

