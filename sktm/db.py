# Copyright (c) 2017 Red Hat, Inc. All rights reserved. This copyrighted
# material is made available to anyone wishing to use, modify, copy, or
# redistribute it subject to the terms and conditions of the GNU General
# Public License v.2 or later.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.

from __future__ import print_function
import logging
import os
import sqlite3
import time
import sktm


class skt_db(object):
    def __init__(self, db):
        if not os.path.isfile(db):
            self.createdb(db)

        self.conn = sqlite3.connect(db)
        self.cur = self.conn.cursor()

    def __del__(self):
        self.conn.close()

    def createdb(self, db):
        tc = sqlite3.connect(db)
        c = tc.cursor()

        # FIXME The "patchsource_id" field should be a part of the primary key
        #       for "pendingpatches" and "patch" tables.
        c.executescript("""
                PRAGMA foreign_keys = on;

                CREATE TABLE baserepo(
                  id INTEGER PRIMARY KEY,
                  url TEXT UNIQUE
                );

                CREATE TABLE patchsource(
                  id INTEGER PRIMARY KEY,
                  baseurl TEXT,
                  project_id INTEGER
                );

                CREATE TABLE patch(
                  id INTEGER PRIMARY KEY,
                  name TEXT,
                  url TEXT,
                  date TEXT,
                  patchsource_id INTEGER,
                  series_id INTEGER,
                  FOREIGN KEY(patchsource_id) REFERENCES patchsource(id)
                );

                CREATE TABLE pendingpatches(
                  id INTEGER PRIMARY KEY,
                  pdate TEXT,
                  patchsource_id INTEGER,
                  timestamp INTEGER,
                  FOREIGN KEY(patchsource_id) REFERENCES patchsource(id)
                );

                CREATE TABLE testrun(
                  id INTEGER PRIMARY KEY,
                  result_id INTEGER,
                  build_id INTEGER
                );

                CREATE TABLE baseline(
                  id INTEGER PRIMARY KEY,
                  baserepo_id INTEGER,
                  commitid TEXT,
                  commitdate INTEGER,
                  testrun_id INTEGER,
                  FOREIGN KEY(baserepo_id) REFERENCES baserepo(id),
                  FOREIGN KEY(testrun_id) REFERENCES testrun(id)
                );

                CREATE TABLE patchtest(
                  id INTEGER PRIMARY KEY,
                  patch_series_id INTEGER,
                  baseline_id INTEGER,
                  testrun_id INTEGER,
                  FOREIGN KEY(baseline_id) REFERENCES baseline(id),
                  FOREIGN KEY(patch_series_id) REFERENCES patch(series_id),
                  FOREIGN KEY(testrun_id) REFERENCES testrun(id)
                );""")

        tc.commit()
        c.close()
        tc.close()

    def create_repoid(self, baserepo):
        """Create a repoid for a git repo URL.

        Args:
            baserepo:   URL of the git repo.

        """
        self.cur.execute('INSERT OR IGNORE INTO baserepo(url) VALUES(?)',
                         (baserepo,))
        self.conn.commit()

        return self.cur.lastrowid

    def get_repoid(self, baserepo):
        """Fetch a repoid for a git repo URL.

        Args:
            baserepo:   URL of the git repo.

        """
        self.cur.execute(
            'SELECT id FROM baserepo WHERE url=?',
            (baserepo,)
        )
        result = self.cur.fetchone()

        if not result:
            return self.create_repoid(baserepo)

        return result[0]

    def create_sourceid(self, baseurl, project_id):
        """Create a patchsource record that links a baseurl and project_id.

        Args:
            baseurl:    Base URL of the Patchwork instance.
            project_id: Project ID in Patchwork.

        """
        self.cur.execute('INSERT INTO patchsource(baseurl, project_id) '
                         'VALUES(?,?)',
                         (baseurl, project_id))
        self.conn.commit()

        return self.cur.lastrowid

    def get_sourceid(self, baseurl, project_id):
        """Fetch a patchsource id that links a baseurl and project_id.

        Args:
            baseurl:    Base URL of the Patchwork instance.
            project_id: Project ID in Patchwork.

        """
        self.cur.execute('SELECT id FROM patchsource WHERE '
                         'baseurl=? AND '
                         'project_id=?',
                         (baseurl, project_id))

        result = self.cur.fetchone()

        if not result:
            return self.create_sourceid(baseurl, project_id)

        return result[0]

    def get_last_checked_patch(self, baseurl, project_id):
        """Get the patch id of the last patch that was checked.

        Args:
            baseurl:    Base URL of the Patchwork instance.
            project_id: Project ID in Patchwork.

        """
        sourceid = self.get_sourceid(baseurl, project_id)

        self.cur.execute('SELECT patch.id FROM patch WHERE '
                         'patchsource_id = ? '
                         'ORDER BY id DESC LIMIT 1',
                         (sourceid,))
        result = self.cur.fetchone()

        if not result:
            return None

        return result[0]

    def get_last_pending_patch(self, baseurl, project_id):
        """Get the patch id of the last patch in the pending list.

        Args:
            baseurl:    Base URL of the Patchwork instance.
            project_id: Project ID in Patchwork.

        """
        sourceid = self.get_sourceid(baseurl, project_id)

        self.cur.execute('SELECT id FROM pendingpatches WHERE '
                         'patchsource_id = ? '
                         'ORDER BY id DESC LIMIT 1',
                         (sourceid,))
        result = self.cur.fetchone()

        if not result:
            return None

        return result[0]

    def get_last_checked_patch_date(self, baseurl, project_id):
        """Get date of last checked patch.

        Args:
            baseurl:    Base URL of the Patchwork instance.
            project_id: Project ID in Patchwork.

        """
        sourceid = self.get_sourceid(baseurl, project_id)

        self.cur.execute('SELECT patch.date FROM patch WHERE '
                         'patchsource_id = ? '
                         'ORDER BY date DESC LIMIT 1',
                         (sourceid,))
        result = self.cur.fetchone()

        if not result:
            return None

        return result[0]

    def get_last_pending_patch_date(self, baseurl, project_id):
        """Get date of last pending patch.

        Args:
            baseurl:    Base URL of the Patchwork instance.
            project_id: Project ID in Patchwork.

        """
        sourceid = self.get_sourceid(baseurl, project_id)

        self.cur.execute('SELECT pdate FROM pendingpatches WHERE '
                         'patchsource_id = ? '
                         'ORDER BY pdate DESC LIMIT 1',
                         (sourceid,))
        result = self.cur.fetchone()

        if not result:
            return None

        return result[0]

    def get_expired_pending_patches(self, baseurl, projid, exptime=86400):
        """
        Get a list of IDs of patches set as pending for longer than the
        specified time, for a combination of a Patchwork base URL and
        Patchwork project ID.

        Args:
            baseurl:    Base URL of Patchwork instance the project and patches
                        belong to.
            projid:     ID of the Patchwork project the patches belong to.
            exptime:    The longer-than time the returned patches should have
                        been staying in the "pending" list.
                        Default is anything longer than 24 hours.

        Returns:
            List of patch IDs.
        """
        patchlist = list()
        sourceid = self.get_sourceid(baseurl, projid)
        tstamp = int(time.time()) - exptime

        self.cur.execute('SELECT id FROM pendingpatches WHERE '
                         'patchsource_id = ? AND '
                         'timestamp < ?',
                         (sourceid, tstamp))
        for res in self.cur.fetchall():
            patchlist.append(res[0])

        if len(patchlist):
            logging.info("expired pending patches for %s (%d): %s", baseurl,
                         projid, patchlist)

        return patchlist

    def get_baselineid(self, baserepo_id, commithash):
        """Get the baseline_id for a particular baserepo_id and commithash.

        Args:
            baserepo_id:    ID of the git repository.
            commithash:     Commit SHA of the baseline commit.

        """
        self.cur.execute('SELECT id FROM baseline WHERE '
                         'baserepo_id = ? AND commitid = ?',
                         (baserepo_id, commithash))
        result = self.cur.fetchone()

        if not result:
            return None

        return result[0]

    def get_commitdate(self, baserepo, commithash):
        """Get the date of a commit in a baseline.

        Args:
            baserepo:   The base repo URL.
            commithash: Commit SHA of the baseline commit.

        Returns:
            Date string or None if the commithash is not found.

        """
        baserepo_id = self.get_repoid(baserepo)

        self.cur.execute('SELECT commitdate FROM baseline WHERE '
                         'commitid = ? AND '
                         'baserepo_id = ?',
                         (commithash, baserepo_id))
        result = self.cur.fetchone()

        if not result:
            return None

        return result[0]

    def get_baselineresult(self, baserepo, commithash):
        """Get the result of a baseline testrun.

        Args:
            baserepo:   The base repo URL.
            commithash: Commit SHA of the baseline commit.

        Returns:
            Result ID of a baseline test run, or None if the test run does not
            exist.

        """
        baserepo_id = self.get_repoid(baserepo)

        self.cur.execute('SELECT testrun.result_id FROM baseline, testrun '
                         'WHERE baseline.commitid = ? AND '
                         'baseline.baserepo_id = ? AND '
                         'baseline.testrun_id = testrun.id '
                         'ORDER BY baseline.commitdate DESC LIMIT 1',
                         (commithash, baserepo_id))
        result = self.cur.fetchone()

        if not result:
            return None

        return sktm.tresult(result[0])

    def get_stable(self, baserepo):
        """Get the latest stable commit ID for a baseline Git repo URL.

        Args:
            baserepo:   Baseline Git repo URL.

        Returns:
            Latest stable commit ID, or None, if there are no stable commits.

        """
        baserepo_id = self.get_repoid(baserepo)

        self.cur.execute('SELECT commitid FROM baseline, testrun WHERE '
                         'baseline.baserepo_id = ? AND '
                         'baseline.testrun_id = testrun.id AND '
                         'testrun.result_id = 0 '
                         'ORDER BY baseline.commitdate DESC LIMIT 1',
                         (baserepo_id, ))

        result = self.cur.fetchone()

        if not result:
            return None

        return result[0]

    def get_latest(self, baserepo):
        """Get the commit hash of the latest baseline.

        Args:
            baserepo:   Baseline Git repo URL.

        Returns:
            Commit SHA of latest baseline, or None, if the baseline does not
            exist.

        """
        baserepo_id = self.get_repoid(baserepo)

        self.cur.execute('SELECT commitid FROM baseline WHERE '
                         'baserepo_id = ? '
                         'ORDER BY baseline.commitdate DESC LIMIT 1',
                         (baserepo_id, ))
        result = self.cur.fetchone()

        if not result:
            return None

        return result[0]

    def set_patchset_pending(self, baseurl, project_id, patchset):
        """Add a patch to pendingpatches or update an existing entry.

        Add each specified patch to the list of "pending" patches, with
        specifed patch date, for specified Patchwork base URL and project ID,
        and marked with current timestamp. Replace any previously added
        patches with the same ID (bug: should be "same ID, project ID and
        base URL").

        Args:
            baseurl:    Base URL of the Patchwork instance the project ID and
                        patch IDs belong to.
            poject_id:  ID of the Patchwork project the patch IDs belong to.
            patchset:   List of info tuples for patches to add to the list,
                        where each tuple contains the patch ID and a free-form
                        patch date string.

        """
        patchset_id = self.get_sourceid(baseurl, project_id)
        tstamp = int(time.time())

        logging.debug("setting patches as pending: %s", patchset)
        self.cur.executemany('INSERT OR REPLACE INTO '
                             'pendingpatches(id, pdate, patchsource_id, '
                             'timestamp) '
                             'VALUES(?, ?, ?, ?)',
                             [(patch_id, patch_date, patchset_id, tstamp) for
                              (patch_id, patch_date) in patchset])
        self.conn.commit()

    def unset_patchset_pending(self, baseurl, project_id, patchset):
        """Remove a patch from the list of pending patches.

        Remove each specified patch from the list of "pending" patches, for
        the specified Patchwork base URL and project ID.

        Args:
            baseurl:    Base URL of the Patchwork instance the project ID and
                        patch IDs belong to.
            project_id: ID of the Patchwork project the patch IDs belong to.
            patchset:   List of IDs of patches to be removed from the list.

        """
        patchset_id = self.get_sourceid(baseurl, project_id)

        logging.debug("removing patches from pending list: %s", patchset)

        self.cur.executemany('DELETE FROM pendingpatches WHERE id = ? '
                             'AND patchsource_id = ?',
                             [(patch_id, patchset_id) for
                              patch_id in patchset])
        self.conn.commit()

    def update_baseline(self, baserepo, commithash, commitdate,
                        result, build_id):
        """Update the baseline commit for a repo.

        Args:
            baserepo:   Baseline Git repo URL.
            commithash: Commit SHA of the baseline commit.
            commitdate: Date of the commit.
            result:     Result ID of the test run.
            build_id:   The build ID of the test run.

        """
        baserepo_id = self.get_repoid(baserepo)

        testrun_id = self.commit_testrun(result, build_id)

        prev_res = self.get_baselineresult(baserepo, commithash)
        logging.debug("previous result: %s", prev_res)

        if prev_res is None:
            logging.debug("creating baseline: repo=%s; commit=%s; result=%s",
                          baserepo, commithash, result)
            self.cur.execute('INSERT INTO '
                             'baseline(baserepo_id, commitid, commitdate, '
                             'testrun_id) VALUES(?,?,?,?)',
                             (baserepo_id, commithash, commitdate,
                              testrun_id))
            self.conn.commit()
        elif result >= prev_res:
            logging.debug("updating baseline: repo=%s; commit=%s; result=%s",
                          baserepo, commithash, result)
            self.cur.execute('UPDATE baseline SET testrun_id = ? '
                             'WHERE commitid = ? AND baserepo_id = ?',
                             (testrun_id, commithash, baserepo_id))
            self.conn.commit()

    # FIXME: There is a chance of series_id collisions between different
    # patchwork instances
    def get_series_result(self, series_id):
        """Get a result_id from a testrun of a patch series.

        Args:
            series_id:  Series ID from Patchwork.

        """
        self.cur.execute('SELECT testrun.result_id FROM patchtest, testrun '
                         'WHERE patchtest.patch_series_id = ? '
                         'AND patchtest.testrun_id = testrun.id '
                         'LIMIT 1',
                         (series_id, ))
        result = self.cur.fetchone()

        if not result:
            return None

        return result[0]

    def commit_patchtest(self, baserepo, commithash, patches, result,
                         build_id, series=None):
        """Add a patchtest for a patch.

        Args:
            baserepo:   Baseline Git repo URL.
            commithash: Commit SHA of the baseline commit.
            patches:    List of patches that were tested
            result:     Result ID of the test run.
            build_id:   The build ID of the test run.
            series:     Series ID from patchwork.

        """
        logging.debug("commit_patchtest: repo=%s; commit=%s; patches=%d; "
                      "result=%s", baserepo, commithash, len(patches), result)
        baserepo_id = self.get_repoid(baserepo)
        baseline_id = self.get_baselineid(baserepo_id, commithash)
        testrun_id = self.commit_testrun(result, build_id)
        series_id = self.commit_series(patches, series)

        for (patch_id, patch_name, patch_url, baseurl, project_id,
             patch_date) in patches:
            # TODO: Can accumulate per-project list instead of doing it one by
            # one
            self.unset_patchset_pending(baseurl, project_id, [patch_id])

        self.cur.execute('INSERT INTO '
                         'patchtest(patch_series_id, baseline_id, testrun_id) '
                         'VALUES(?,?,?)',
                         (series_id, baseline_id, testrun_id))
        self.conn.commit()

    def commit_testrun(self, result, buildid):
        """Add a test run to the database.

        Args:
            result:     Result of the test run.
            build_id:   The build ID of the test run.

        """
        logging.debug("commit_testrun: result=%s; buildid=%d", result, buildid)
        self.cur.execute('INSERT INTO testrun(result_id, build_id) '
                         'VALUES(?,?)',
                         (result.value, buildid))
        self.conn.commit()
        return self.cur.lastrowid

    def commit_patch(self, patch_id, patch_name, patch_url, series_id,
                     baseurl, project_id, patch_date):
        """Create/update a patch record in the database.

        Args:
            patch_id:       Patch ID.
            patch_name:     Patch name (subject line).
            patch_url:      URL to the patch in Patchwork.
            series_id:      The ID of the series that contains the patch.
            baseurl:        URL of the git repo.
            project_id:     ID of the project in Patchwork.
            patch_date:     Timestamp.

        """
        # pylint: disable=too-many-arguments
        logging.debug("commit_patch: pid=%s; sid=%s", patch_id, series_id)
        source_id = self.get_sourceid(baseurl, project_id)
        self.cur.execute('INSERT OR REPLACE INTO patch(id, name, url, '
                         'patchsource_id, series_id, date) '
                         'VALUES(?,?,?,?,?,?)',
                         (patch_id, patch_name, patch_url, source_id,
                          series_id, patch_date))
        self.conn.commit()

    def commit_series(self, patches, series_id=None):
        """Create patch records for a list of patches.

        Args:
            patches:    List of patches to insert into the database.
            series_id:  Series ID from patchwork that contains the patches.

        """
        logging.debug("commit_series: %s (%s)", patches, series_id)

        if series_id is None:

            # Set a starting series_id in case the database is empty
            series_id = 1

            # Find the last series_id in the database
            self.cur.execute('SELECT series_id FROM patch '
                             'ORDER BY series_id DESC LIMIT 1')
            result = self.cur.fetchone()

            # Set the series_id to the next id
            if result:
                series_id = 1 + result[0]

        for (patch_id, patch_name, patch_url, baseurl, project_id,
             patch_date) in patches:
            # If the source_id doesn't exist, this method will create it.
            self.get_sourceid(baseurl, project_id)

            # Add the patches to the database
            self.commit_patch(patch_id, patch_name, patch_url, series_id,
                              baseurl, project_id, patch_date)

        self.conn.commit()

        return series_id

    def dump_baseline_tests(self):  # pragma: no cover
        """Dump all of the current baseline tests from the database."""
        self.cur.execute('SELECT baserepo.url, baseline.commitid, '
                         'testrun.result_id, testrun.build_id '
                         'FROM baseline, baserepo, testrun '
                         'WHERE baseline.baserepo_id = baserepo.id AND '
                         'baseline.testrun_id = testrun.id')

        for (burl, commit, res, buildid) in self.cur.fetchall():
            print("repo url:", burl)
            print("commit id:", commit)
            print("result:", sktm.tresult(res).name)
            print("build id: #", buildid, sep='')
            print("---")

    def dump_baserepo_info(self):  # pragma: no cover
        """Dump all of the information about baserepos."""
        self.cur.execute('SELECT url FROM baserepo')

        for (burl,) in self.cur.fetchall():
            print("repo url:", burl)
            stable = self.get_stable(burl)
            latest = self.get_latest(burl)
            print("most recent stable commit: {} ({})".format(
                  stable, self.get_commitdate(burl, stable)))
            print("most recent stable commit: {} ({})".format(
                  latest, self.get_commitdate(burl, latest)))
            print("---")
